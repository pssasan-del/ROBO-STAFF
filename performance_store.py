import json, os, sqlite3, threading
from datetime import datetime, timedelta, timezone
from config import settings, logger

IST=timezone(timedelta(hours=5,minutes=30))
BASE_KEYS=('total','success','failed','unresolved','buy_success','buy_failed','sell_success','sell_failed','ai_confirmed','no_ai_confirmation','sl_later_t1','sl_later_t2')

class PerformanceStore:
    """Bounded aggregate-only statistics. No candles/order books/prompts or user chat are persisted."""
    def __init__(self,path=None):
        self.path=path or settings.DELTA_STATS_PATH; self.lock=threading.RLock(); self.data={'days':{}}
        self.pg=False; self.conn=None; self._init_persistent(); self._load(); self._prune()

    def _init_persistent(self):
        try:
            if settings.DATABASE_URL:
                import psycopg
                self.conn=psycopg.connect(settings.DATABASE_URL,autocommit=True); self.pg=True
                with self.conn.cursor() as cur:
                    cur.execute('''CREATE TABLE IF NOT EXISTS delta_signal_stats(day TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL)''')
                logger.info('[DELTA_STATS] PostgreSQL aggregate persistence enabled')
        except Exception as e:
            logger.warning('[DELTA_STATS] PostgreSQL unavailable; file fallback: %s',e); self.conn=None; self.pg=False

    def _load(self):
        try:
            if self.pg:
                with self.conn.cursor() as cur:
                    cur.execute("SELECT day,payload_json FROM delta_signal_stats WHERE day >= %s",((datetime.now(IST).date()-timedelta(days=35)).isoformat(),))
                    self.data={'days':{str(day):json.loads(payload) for day,payload in cur.fetchall()}}
            elif os.path.exists(self.path):
                with open(self.path,'r',encoding='utf-8') as f:self.data=json.load(f)
        except Exception as e:logger.warning('[DELTA_STATS] load failed safely: %s',e);self.data={'days':{}}

    def _prune(self):
        days=self.data.setdefault('days',{}); keep=sorted(days)[-35:]; self.data['days']={k:days[k] for k in keep}

    def _save_day(self,key):
        self._prune(); payload=json.dumps(self.data['days'][key],separators=(',',':'))
        if self.pg:
            with self.conn.cursor() as cur:
                cur.execute('''INSERT INTO delta_signal_stats(day,payload_json,updated_at) VALUES(%s,%s,%s)
                    ON CONFLICT(day) DO UPDATE SET payload_json=EXCLUDED.payload_json,updated_at=EXCLUDED.updated_at''',(key,payload,datetime.now(timezone.utc).isoformat()))
            return
        os.makedirs(os.path.dirname(self.path) or '.',exist_ok=True);tmp=self.path+'.tmp'
        with open(tmp,'w',encoding='utf-8') as f:json.dump(self.data,f,separators=(',',':'))
        os.replace(tmp,self.path)

    @staticmethod
    def _ai_group(ai_status):
        s=(ai_status or '').upper()
        if s.startswith('CONFIRM'):return 'confirm'
        if s.startswith('REJECT'):return 'reject'
        if s.startswith('WAIT'):return 'wait'
        return 'no_ai'

    def _bucket(self,day=None):
        key=day or datetime.now(IST).date().isoformat();d=self.data.setdefault('days',{}).setdefault(key,{})
        for k in BASE_KEYS:d.setdefault(k,0)
        d.setdefault('assets',{});d.setdefault('ai',{});d.setdefault('actions',{});d.setdefault('timing',{'sl_under_5m':0,'sl_5_15m':0,'sl_over_15m':0,'t1_under_5m':0,'t1_5_15m':0,'t1_over_15m':0})
        return key,d

    @staticmethod
    def _pair(container,key):
        p=container.setdefault(key,{'success':0,'failed':0});return p

    def new_signal(self,action,ai_status='',underlying='UNKNOWN'):
        with self.lock:
            key,d=self._bucket();d['total']+=1;d['unresolved']+=1
            d['ai_confirmed' if self._ai_group(ai_status)=='confirm' else 'no_ai_confirmation']+=1
            self._pair(d['actions'],action);self._pair(d['assets'],underlying);self._pair(d['ai'],self._ai_group(ai_status));self._save_day(key)

    def resolve(self,action,success,underlying='UNKNOWN',ai_status='',elapsed_seconds=None):
        with self.lock:
            key,d=self._bucket();d['unresolved']=max(0,d['unresolved']-1);d['success' if success else 'failed']+=1
            side='buy' if 'BUY' in action.upper() else 'sell';d[f'{side}_{"success" if success else "failed"}']+=1
            result='success' if success else 'failed'
            self._pair(d['actions'],action)[result]+=1;self._pair(d['assets'],underlying)[result]+=1;self._pair(d['ai'],self._ai_group(ai_status))[result]+=1
            if elapsed_seconds is not None:
                prefix='t1' if success else 'sl';mins=max(0,float(elapsed_seconds))/60
                band='under_5m' if mins<5 else ('5_15m' if mins<=15 else 'over_15m');d['timing'][f'{prefix}_{band}']+=1
            self._save_day(key)

    def mark_sl_recovery(self,target='t1'):
        with self.lock:
            key,d=self._bucket(); k='sl_later_t2' if str(target).lower()=='t2' else 'sl_later_t1';d[k]+=1;self._save_day(key)

    def report(self,days=1):
        with self.lock:
            today=datetime.now(IST).date(); keys=[(today-timedelta(days=i)).isoformat() for i in range(days)]
            out={k:0 for k in BASE_KEYS};out.update({'assets':{},'ai':{},'actions':{},'timing':{}})
            for day in keys:
                src=self.data.get('days',{}).get(day,{})
                for k in BASE_KEYS:out[k]+=int(src.get(k,0))
                for group in ('assets','ai','actions'):
                    for name,p in src.get(group,{}).items():
                        q=self._pair(out[group],name);q['success']+=int(p.get('success',0));q['failed']+=int(p.get('failed',0))
                for k,v in src.get('timing',{}).items():out['timing'][k]=out['timing'].get(k,0)+int(v)
            resolved=out['success']+out['failed'];out['success_rate']=round(out['success']*100/resolved,1) if resolved else 0.0;return out
performance_store=PerformanceStore()
