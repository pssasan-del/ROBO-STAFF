import json, os, threading
from datetime import datetime, timedelta, timezone
from config import settings, logger

IST=timezone(timedelta(hours=5,minutes=30))

class PerformanceStore:
    """Tiny bounded aggregate store. No candles/order books/AI prompts are persisted."""
    def __init__(self,path=None):
        self.path=path or settings.DELTA_STATS_PATH; self.lock=threading.RLock(); self.data={'days':{}}
        self._load()
    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path,'r',encoding='utf-8') as f:self.data=json.load(f)
        except Exception as e:logger.warning('[DELTA_STATS] load failed safely: %s',e);self.data={'days':{}}
        self._prune()
    def _prune(self):
        days=self.data.setdefault('days',{}); keep=sorted(days)[-35:]
        self.data['days']={k:days[k] for k in keep}
    def _save(self):
        os.makedirs(os.path.dirname(self.path) or '.',exist_ok=True);self._prune();tmp=self.path+'.tmp'
        with open(tmp,'w',encoding='utf-8') as f:json.dump(self.data,f,separators=(',',':'))
        os.replace(tmp,self.path)
    def _bucket(self,day=None):
        key=day or datetime.now(IST).date().isoformat();d=self.data.setdefault('days',{}).setdefault(key,{})
        for k in ('total','success','failed','unresolved','buy_success','buy_failed','sell_success','sell_failed','ai_confirmed','no_ai_confirmation'):d.setdefault(k,0)
        return d
    def new_signal(self,action,ai_confirmed=False):
        with self.lock:
            d=self._bucket();d['total']+=1;d['unresolved']+=1;d['ai_confirmed' if ai_confirmed else 'no_ai_confirmation']+=1;self._save()
    def resolve(self,action,success):
        with self.lock:
            d=self._bucket();d['unresolved']=max(0,d['unresolved']-1);d['success' if success else 'failed']+=1
            side='buy' if 'BUY' in action.upper() else 'sell';d[f'{side}_{"success" if success else "failed"}']+=1;self._save()
    def report(self,days=1):
        with self.lock:
            today=datetime.now(IST).date(); keys=[(today-timedelta(days=i)).isoformat() for i in range(days)]
            out={k:0 for k in ('total','success','failed','unresolved','buy_success','buy_failed','sell_success','sell_failed','ai_confirmed','no_ai_confirmation')}
            for key in keys:
                for k,v in self.data.get('days',{}).get(key,{}).items():
                    if k in out:out[k]+=int(v)
            resolved=out['success']+out['failed'];out['success_rate']=round(out['success']*100/resolved,1) if resolved else 0.0;return out
performance_store=PerformanceStore()
