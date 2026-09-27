import json
import math
import statistics
import threading
from collections import deque
from datetime import datetime, timezone, timedelta

from config import settings, logger
from delta_market_service import delta_market_service
from strategy_engine import ema, atr, vwap, directional_values
from polish_policy import ACCEPTANCE_CRITERIA

IST = timezone(timedelta(hours=5, minutes=30))
RESEARCH_EPOCH = 'FRESH_V3.2_2026-09-27'
RESEARCH_TABLE = 'delta_research_signals_v32'


class ResearchStore:
    """Bounded V3.2 telemetry. Research can propose tests but never changes live rules."""
    def __init__(self):
        self.lock = threading.RLock()
        self.rows = deque(maxlen=300)
        self.pg = False
        self.conn = None
        try:
            if settings.DATABASE_URL:
                import psycopg
                self.conn = psycopg.connect(settings.DATABASE_URL, autocommit=True)
                self.pg = True
                with self.conn.cursor() as cur:
                    cur.execute(f'''CREATE TABLE IF NOT EXISTS {RESEARCH_TABLE}(
                        signal_key TEXT PRIMARY KEY, created_at DOUBLE PRECISION NOT NULL,
                        underlying TEXT, action TEXT, direction TEXT, option_symbol TEXT,
                        entry DOUBLE PRECISION, sl DOUBLE PRECISION, t1 DOUBLE PRECISION,
                        score INTEGER, ai_status TEXT, features_json TEXT, outcome TEXT,
                        outcome_seconds DOUBLE PRECISION, outcome_price DOUBLE PRECISION,
                        outcome_r DOUBLE PRECISION DEFAULT 0,
                        sl_later_t1 BOOLEAN DEFAULT FALSE, sl_later_t2 BOOLEAN DEFAULT FALSE,
                        mfe_pct DOUBLE PRECISION DEFAULT 0, mae_pct DOUBLE PRECISION DEFAULT 0,
                        mfe_r DOUBLE PRECISION DEFAULT 0, mae_r DOUBLE PRECISION DEFAULT 0,
                        updated_at TEXT NOT NULL)''')
                logger.info('[RESEARCH] Fresh V3.2 PostgreSQL telemetry enabled; older epochs excluded')
        except Exception as exc:
            logger.warning('[RESEARCH] PostgreSQL unavailable; bounded RAM fallback: %s', exc)
            self.pg = False; self.conn = None

    @staticmethod
    def _row(key, candidate, features, outcome='OPEN'):
        return {
            'signal_key': key, 'created_at': candidate.created, 'underlying': candidate.underlying,
            'action': candidate.action, 'direction': candidate.direction, 'option_symbol': candidate.option_symbol,
            'entry': candidate.premium, 'sl': candidate.sl, 't1': candidate.t1, 'score': candidate.score,
            'ai_status': candidate.ai_status, 'features': features, 'outcome': outcome,
            'outcome_seconds': 0.0, 'outcome_price': 0.0, 'outcome_r': 0.0,
            'sl_later_t1': False, 'sl_later_t2': False,
            'mfe_pct': 0.0, 'mae_pct': 0.0, 'mfe_r': 0.0, 'mae_r': 0.0,
        }

    def _insert(self, key, candidate, features, outcome='OPEN'):
        row = self._row(key, candidate, features, outcome)
        if self.pg:
            with self.conn.cursor() as cur:
                cur.execute(f'''INSERT INTO {RESEARCH_TABLE}(
                    signal_key,created_at,underlying,action,direction,option_symbol,entry,sl,t1,score,ai_status,
                    features_json,outcome,outcome_seconds,outcome_price,outcome_r,sl_later_t1,sl_later_t2,mfe_pct,mae_pct,mfe_r,mae_r,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,0,FALSE,FALSE,0,0,0,0,%s)
                    ON CONFLICT(signal_key) DO NOTHING''', (
                    key,candidate.created,candidate.underlying,candidate.action,candidate.direction,candidate.option_symbol,
                    candidate.premium,candidate.sl,candidate.t1,candidate.score,candidate.ai_status,
                    json.dumps(features,separators=(',',':')),outcome,datetime.now(timezone.utc).isoformat()))
                cur.execute(f'''DELETE FROM {RESEARCH_TABLE} WHERE signal_key IN
                    (SELECT signal_key FROM {RESEARCH_TABLE} ORDER BY created_at DESC OFFSET 1000)''')
        else:
            self.rows.append(row)

    def add(self, key, candidate, features):
        with self.lock:self._insert(key,candidate,features,'OPEN')

    def add_suppressed(self, key, candidate, features, reason):
        f = dict(features or {}); f['suppression_reason'] = reason
        with self.lock:self._insert('SUPPRESSED:'+key,candidate,f,'SUPPRESSED')

    def update_excursion(self, key, mfe_pct, mae_pct, mfe_r=0.0, mae_r=0.0):
        vals=[max(0.0,float(x or 0)) for x in (mfe_pct,mae_pct,mfe_r,mae_r)]
        with self.lock:
            if self.pg:
                with self.conn.cursor() as cur:
                    cur.execute(f'''UPDATE {RESEARCH_TABLE} SET
                        mfe_pct=GREATEST(COALESCE(mfe_pct,0),%s),mae_pct=GREATEST(COALESCE(mae_pct,0),%s),
                        mfe_r=GREATEST(COALESCE(mfe_r,0),%s),mae_r=GREATEST(COALESCE(mae_r,0),%s),updated_at=%s
                        WHERE signal_key=%s''',(*vals,datetime.now(timezone.utc).isoformat(),key))
            else:
                for r in reversed(self.rows):
                    if r['signal_key']==key:
                        r['mfe_pct']=max(r['mfe_pct'],vals[0]);r['mae_pct']=max(r['mae_pct'],vals[1]);r['mfe_r']=max(r['mfe_r'],vals[2]);r['mae_r']=max(r['mae_r'],vals[3]);break

    def resolve(self, key, outcome, seconds, price, outcome_r=0.0):
        with self.lock:
            if self.pg:
                with self.conn.cursor() as cur:
                    cur.execute(f'''UPDATE {RESEARCH_TABLE} SET outcome=%s,outcome_seconds=%s,outcome_price=%s,
                        outcome_r=%s,updated_at=%s WHERE signal_key=%s''',
                        (outcome,float(seconds),float(price),float(outcome_r),datetime.now(timezone.utc).isoformat(),key))
            else:
                for r in reversed(self.rows):
                    if r['signal_key']==key:
                        r.update(outcome=outcome,outcome_seconds=float(seconds),outcome_price=float(price),outcome_r=float(outcome_r));break

    def mark_recovery(self, key, target='t1'):
        col='sl_later_t2' if str(target).lower()=='t2' else 'sl_later_t1'
        with self.lock:
            if self.pg:
                with self.conn.cursor() as cur:
                    cur.execute(f'UPDATE {RESEARCH_TABLE} SET {col}=TRUE,updated_at=%s WHERE signal_key=%s',(datetime.now(timezone.utc).isoformat(),key))
            else:
                for r in reversed(self.rows):
                    if r['signal_key']==key:r[col]=True;break

    def _records(self):
        records=[]
        if self.pg:
            with self.conn.cursor() as cur:
                cur.execute(f'''SELECT created_at,underlying,action,direction,outcome,outcome_seconds,outcome_r,features_json,
                    sl_later_t1,sl_later_t2,mfe_pct,mae_pct,mfe_r,mae_r FROM {RESEARCH_TABLE} ORDER BY created_at DESC''')
                for row in cur.fetchall():
                    created,und,action,direction,outcome,seconds,out_r,features_json,r1,r2,mfe,mae,mfer,maer=row
                    try:features=json.loads(features_json or '{}')
                    except Exception:features={}
                    records.append({'created_at':float(created),'underlying':und,'action':action,'direction':direction,'outcome':outcome,
                        'seconds':float(seconds or 0),'outcome_r':float(out_r or 0),'features':features,'recovered':bool(r1),'recovered_t2':bool(r2),
                        'mfe_pct':float(mfe or 0),'mae_pct':float(mae or 0),'mfe_r':float(mfer or 0),'mae_r':float(maer or 0)})
        else:
            for r in self.rows:
                records.append({'created_at':float(r.get('created_at') or 0),'underlying':r.get('underlying'),'action':r.get('action'),'direction':r.get('direction'),
                    'outcome':r.get('outcome'),'seconds':float(r.get('outcome_seconds') or 0),'outcome_r':float(r.get('outcome_r') or 0),'features':r.get('features') or {},
                    'recovered':bool(r.get('sl_later_t1')),'recovered_t2':bool(r.get('sl_later_t2')),'mfe_pct':float(r.get('mfe_pct') or 0),'mae_pct':float(r.get('mae_pct') or 0),
                    'mfe_r':float(r.get('mfe_r') or 0),'mae_r':float(r.get('mae_r') or 0)})
        return records

    @staticmethod
    def _pf(rs):
        pos=sum(x for x in rs if x>0);neg=abs(sum(x for x in rs if x<0))
        return round(pos/neg,2) if neg>0 else (99.0 if pos>0 else 0.0)

    @staticmethod
    def _rate(rows):
        w=sum(r['outcome']=='T1' for r in rows);l=sum(r['outcome']=='SL' for r in rows);n=w+l
        return round(100*w/n,1) if n else 0.0,n,w,l

    @staticmethod
    def _percentile(values,p):
        vals=sorted(values)
        if not vals:return 0.0
        k=(len(vals)-1)*p;f=math.floor(k);c=math.ceil(k)
        if f==c:return float(vals[int(k)])
        return float(vals[f]*(c-k)+vals[c]*(k-f))

    def _candidate_experiments(self, resolved):
        """Evidence-triggered A/B candidates only; this never changes live rules."""
        ideas=[]
        def compare(name, pred_a, label_a, pred_b, label_b):
            a=[r for r in resolved if pred_a(r)];b=[r for r in resolved if pred_b(r)]
            ra,na,_,_=self._rate(a);rb,nb,_,_=self._rate(b)
            if na>=30 and nb>=30 and abs(ra-rb)>=8:
                better=label_a if ra>rb else label_b
                ideas.append(f'A/B {name}: {label_a} {ra}% n={na} vs {label_b} {rb}% n={nb}; candidate={better}')
        compare('pattern',lambda r:r['features'].get('pattern')=='BREAKOUT','BREAKOUT',lambda r:r['features'].get('pattern')=='RETEST','RETEST')
        compare('ADX',lambda r:float(r['features'].get('adx5') or 0)>=25,'ADX>=25',lambda r:22<=float(r['features'].get('adx5') or 0)<25,'ADX22-25')
        compare('RVOL',lambda r:float(r['features'].get('rvol5') or 0)>=1.25,'RVOL>=1.25',lambda r:float(r['features'].get('rvol5') or 0)<1.25,'RVOL<1.25')
        compare('spread',lambda r:float(r['features'].get('option_spread_pct') or 99)<=2,'spread<=2%',lambda r:2<float(r['features'].get('option_spread_pct') or 99)<=4,'spread2-4%')
        return ideas[:6]

    def summary(self):
        with self.lock:records=self._records()
        alerted=[r for r in records if r['outcome']!='SUPPRESSED'];suppressed=[r for r in records if r['outcome']=='SUPPRESSED']
        binary=[r for r in alerted if r['outcome'] in {'T1','SL'}];special=[r for r in alerted if r['outcome'] in {'STALE','INVALIDATED'}]
        open_rows=[r for r in alerted if r['outcome']=='OPEN']
        rate,n_binary,w,l=self._rate(binary)
        all_resolved=binary+special
        outcome_rs=[r['outcome_r'] for r in all_resolved]
        pf=self._pf(outcome_rs);expectancy=round(sum(outcome_rs)/len(outcome_rs),2) if outcome_rs else 0.0
        t1_minutes=[r['seconds']/60 for r in binary if r['outcome']=='T1']
        fast_sl=sum(r['outcome']=='SL' and r['seconds']<300 for r in binary)
        fast_sl_pct=round(100*fast_sl/l,1) if l else 0.0
        recovered=sum(r['outcome']=='SL' and r['recovered'] for r in binary)
        recovery_pct=round(100*recovered/l,1) if l else 0.0
        stale_pct=round(100*len(special)/len(all_resolved),1) if all_resolved else 0.0
        days=len({datetime.fromtimestamp(r['created_at'],IST).date().isoformat() for r in alerted if r['created_at']})

        buckets={}
        for r in binary:
            k=(r['underlying'],r['action']);q=buckets.setdefault(k,{'w':0,'l':0,'t1_sec':0.0,'sl_sec':0.0,'rs':[]})
            q['rs'].append(r['outcome_r'])
            if r['outcome']=='T1':q['w']+=1;q['t1_sec']+=r['seconds']
            else:q['l']+=1;q['sl_sec']+=r['seconds']
        for q in buckets.values():
            if q['w']:q['t1_sec']/=q['w']
            if q['l']:q['sl_sec']/=q['l']
            q['pf']=self._pf(q.pop('rs'))

        c=ACCEPTANCE_CRITERIA
        bucket_pass=True;bucket_checks=[]
        for k,q in buckets.items():
            n=q['w']+q['l'];wr=100*q['w']/n if n else 0
            if n>=c['bucket_min_n']:
                ok=wr>=c['bucket_min_win_pct'] and q['pf']>=c['bucket_min_pf'];bucket_pass=bool(bucket_pass and ok)
                bucket_checks.append({'bucket':f'{k[0]} {k[1]}','n':n,'win_pct':round(wr,1),'pf':q['pf'],'pass':ok})
        acceptance={
            'resolved':len(all_resolved),'binary_resolved':n_binary,'calendar_days':days,'t1_success_pct':rate,'profit_factor':pf,'expectancy_r':expectancy,
            'median_t1_minutes':round(statistics.median(t1_minutes),1) if t1_minutes else 0.0,'p75_t1_minutes':round(self._percentile(t1_minutes,.75),1) if t1_minutes else 0.0,
            'fast_sl_pct':fast_sl_pct,'sl_later_t1_pct':recovery_pct,'stale_pct':stale_pct,'bucket_checks':bucket_checks,
        }
        acceptance['promotion_ready']=bool(
            len(all_resolved)>=c['min_resolved'] and days>=c['min_calendar_days'] and rate>=c['min_t1_success_pct'] and
            pf>=c['min_profit_factor'] and expectancy>=c['min_expectancy_r'] and
            (not t1_minutes or acceptance['median_t1_minutes']<=c['max_median_t1_minutes']) and
            (not t1_minutes or acceptance['p75_t1_minutes']<=c['max_p75_t1_minutes']) and
            fast_sl_pct<=c['max_fast_sl_pct'] and recovery_pct<=c['max_sl_later_t1_pct'] and stale_pct<=c['max_stale_pct'] and bucket_pass
        )

        return {
            'epoch':RESEARCH_EPOCH,'total':len(alerted),'open':len(open_rows),'suppressed':len(suppressed),'recovered':recovered,
            'buckets':buckets,'acceptance':acceptance,'candidate_rules':self._candidate_experiments(binary),
            'avg_mfe_r':round(sum(r['mfe_r'] for r in binary)/len(binary),2) if binary else 0.0,
            'avg_mae_r':round(sum(r['mae_r'] for r in binary)/len(binary),2) if binary else 0.0,
        }


class MarketReplay:
    """Underlying-only V3.2 diagnostic. Historical option premium is never fabricated."""
    @staticmethod
    def _features(rows):
        closes=[r['close'] for r in rows];px=closes[-1];e5,e9,e20=ema(closes,5),ema(closes,9),ema(closes,20)
        adx,pdi,mdi=directional_values(rows,14);a=atr(rows,14);vw=vwap(rows,30);prev=rows[-7:-1]
        avg=sum(r['volume'] for r in rows[-21:-1])/max(1,len(rows[-21:-1]));rv=rows[-1]['volume']/avg if avg else 0
        up=max(r['high'] for r in prev);dn=min(r['low'] for r in prev)
        direction='BULLISH' if e5>e9>e20 and px>vw and pdi>mdi else ('BEARISH' if e5<e9<e20 and px<vw and mdi>pdi else 'MIXED')
        breakout='UP' if px>up else ('DOWN' if px<dn else 'NONE')
        return {'price':px,'direction':direction,'breakout':breakout,'adx':adx,'rvol':rv,'atr':a}
    async def run(self,symbol,limit=600):
        rows=await delta_market_service.get_candles(symbol,'5m',max(120,min(int(limit),600)));events=[]
        for i in range(40,len(rows)-10):
            f=self._features(rows[:i+1]);aligned=(f['direction']=='BULLISH' and f['breakout']=='UP') or (f['direction']=='BEARISH' and f['breakout']=='DOWN')
            if not aligned or f['adx']<22 or f['rvol']<1.0:continue
            entry=rows[i]['close'];risk=max(f['atr'],entry*.0005);side=f['breakout'];out='OPEN';bars=0
            sl=entry-risk if side=='UP' else entry+risk;t1=entry+risk*1.85 if side=='UP' else entry-risk*1.85
            for k in range(i+1,min(len(rows),i+10)):
                bars=k-i;hi,lo=rows[k]['high'],rows[k]['low']
                if side=='UP':
                    if lo<=sl:out='SL';break
                    if hi>=t1:out='T1';break
                else:
                    if hi>=sl:out='SL';break
                    if lo<=t1:out='T1';break
            events.append((out,bars,f['adx'],f['rvol']))
        done=[e for e in events if e[0] in {'T1','SL'}];w=sum(e[0]=='T1' for e in done);l=sum(e[0]=='SL' for e in done)
        return {'events':len(events),'resolved':len(done),'w':w,'l':l,'rate':round(100*w/(w+l),1) if w+l else 0.0,'avg_bars':round(sum(e[1] for e in done)/len(done),1) if done else 0.0,'avg_adx':round(sum(e[2] for e in done)/len(done),1) if done else 0.0,'avg_rvol':round(sum(e[3] for e in done)/len(done),2) if done else 0.0}


research_store=ResearchStore();market_replay=MarketReplay()
