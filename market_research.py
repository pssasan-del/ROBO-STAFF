import json, threading
from collections import deque
from datetime import datetime, timezone
from config import settings, logger
from delta_market_service import delta_market_service
from strategy_engine import ema, atr, vwap, directional_values

RESEARCH_EPOCH='FRESH_V3.1_2026-09-27'
RESEARCH_TABLE='delta_research_signals_v31'

class ResearchStore:
    """Fresh V3.1 compact telemetry. Older research tables remain untouched and excluded."""
    def __init__(self):
        self.lock=threading.RLock();self.rows=deque(maxlen=250);self.pg=False;self.conn=None
        try:
            if settings.DATABASE_URL:
                import psycopg
                self.conn=psycopg.connect(settings.DATABASE_URL,autocommit=True);self.pg=True
                with self.conn.cursor() as cur:
                    cur.execute(f'''CREATE TABLE IF NOT EXISTS {RESEARCH_TABLE}(
                        signal_key TEXT PRIMARY KEY,created_at DOUBLE PRECISION NOT NULL,
                        underlying TEXT,action TEXT,direction TEXT,option_symbol TEXT,
                        entry DOUBLE PRECISION,sl DOUBLE PRECISION,t1 DOUBLE PRECISION,
                        score INTEGER,ai_status TEXT,features_json TEXT,outcome TEXT,
                        outcome_seconds DOUBLE PRECISION,outcome_price DOUBLE PRECISION,
                        sl_later_t1 BOOLEAN DEFAULT FALSE,mfe_pct DOUBLE PRECISION DEFAULT 0,
                        mae_pct DOUBLE PRECISION DEFAULT 0,updated_at TEXT NOT NULL)''')
                    cur.execute(f'ALTER TABLE {RESEARCH_TABLE} ADD COLUMN IF NOT EXISTS mfe_pct DOUBLE PRECISION DEFAULT 0')
                    cur.execute(f'ALTER TABLE {RESEARCH_TABLE} ADD COLUMN IF NOT EXISTS mae_pct DOUBLE PRECISION DEFAULT 0')
                logger.info('[RESEARCH] Fresh V3.1 PostgreSQL telemetry enabled; older epochs excluded')
        except Exception as exc:
            logger.warning('[RESEARCH] PostgreSQL unavailable; bounded RAM fallback: %s',exc);self.pg=False;self.conn=None

    def add(self,key,candidate,features):
        row={'signal_key':key,'created_at':candidate.created,'underlying':candidate.underlying,'action':candidate.action,'direction':candidate.direction,'option_symbol':candidate.option_symbol,'entry':candidate.premium,'sl':candidate.sl,'t1':candidate.t1,'score':candidate.score,'ai_status':candidate.ai_status,'features':features,'outcome':'OPEN','mfe_pct':0.0,'mae_pct':0.0}
        with self.lock:
            if self.pg:
                with self.conn.cursor() as cur:
                    cur.execute(f'''INSERT INTO {RESEARCH_TABLE}(signal_key,created_at,underlying,action,direction,option_symbol,entry,sl,t1,score,ai_status,features_json,outcome,mfe_pct,mae_pct,updated_at)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'OPEN',0,0,%s) ON CONFLICT(signal_key) DO NOTHING''',
                        (key,candidate.created,candidate.underlying,candidate.action,candidate.direction,candidate.option_symbol,candidate.premium,candidate.sl,candidate.t1,candidate.score,candidate.ai_status,json.dumps(features,separators=(',',':')),datetime.now(timezone.utc).isoformat()))
                    cur.execute(f'''DELETE FROM {RESEARCH_TABLE} WHERE signal_key IN (SELECT signal_key FROM {RESEARCH_TABLE} ORDER BY created_at DESC OFFSET 750)''')
            else:self.rows.append(row)

    def update_excursion(self,key,mfe_pct,mae_pct):
        mfe=max(0.0,float(mfe_pct or 0));mae=max(0.0,float(mae_pct or 0))
        with self.lock:
            if self.pg:
                with self.conn.cursor() as cur:
                    cur.execute(f'''UPDATE {RESEARCH_TABLE} SET mfe_pct=GREATEST(COALESCE(mfe_pct,0),%s),mae_pct=GREATEST(COALESCE(mae_pct,0),%s),updated_at=%s WHERE signal_key=%s''',(mfe,mae,datetime.now(timezone.utc).isoformat(),key))
            else:
                for r in reversed(self.rows):
                    if r['signal_key']==key:
                        r['mfe_pct']=max(float(r.get('mfe_pct') or 0),mfe);r['mae_pct']=max(float(r.get('mae_pct') or 0),mae);break

    def resolve(self,key,outcome,seconds,price):
        with self.lock:
            if self.pg:
                with self.conn.cursor() as cur:cur.execute(f'UPDATE {RESEARCH_TABLE} SET outcome=%s,outcome_seconds=%s,outcome_price=%s,updated_at=%s WHERE signal_key=%s',(outcome,float(seconds),float(price),datetime.now(timezone.utc).isoformat(),key))
            else:
                for r in reversed(self.rows):
                    if r['signal_key']==key:r.update(outcome=outcome,outcome_seconds=float(seconds),outcome_price=float(price));break

    def mark_recovery(self,key):
        with self.lock:
            if self.pg:
                with self.conn.cursor() as cur:cur.execute(f'UPDATE {RESEARCH_TABLE} SET sl_later_t1=TRUE,updated_at=%s WHERE signal_key=%s',(datetime.now(timezone.utc).isoformat(),key))
            else:
                for r in reversed(self.rows):
                    if r['signal_key']==key:r['sl_later_t1']=True;break

    @staticmethod
    def _acc_result(container,key,outcome):
        q=container.setdefault(str(key),{'w':0,'l':0})
        if outcome=='T1':q['w']+=1
        elif outcome=='SL':q['l']+=1

    def summary(self):
        with self.lock:
            records=[]
            if self.pg:
                with self.conn.cursor() as cur:
                    cur.execute(f"SELECT underlying,action,outcome,outcome_seconds,features_json,sl_later_t1,mfe_pct,mae_pct FROM {RESEARCH_TABLE} ORDER BY created_at DESC")
                    for und,action,outcome,seconds,features_json,recovered,mfe,mae in cur.fetchall():
                        try:features=json.loads(features_json or '{}')
                        except Exception:features={}
                        records.append({'underlying':und,'action':action,'outcome':outcome,'seconds':float(seconds or 0),'features':features,'recovered':bool(recovered),'mfe_pct':float(mfe or 0),'mae_pct':float(mae or 0)})
            else:
                for r in self.rows:
                    records.append({'underlying':r.get('underlying'),'action':r.get('action'),'outcome':r.get('outcome'),'seconds':float(r.get('outcome_seconds') or 0),'features':r.get('features') or {},'recovered':bool(r.get('sl_later_t1')),'mfe_pct':float(r.get('mfe_pct') or 0),'mae_pct':float(r.get('mae_pct') or 0)})

        buckets={};cross_bars={};daily_zones={};five_zones={};spreads={'T1':[],'SL':[]};mfe={'T1':[],'SL':[]};mae={'T1':[],'SL':[]};open_count=0;recovered=0
        for r in records:
            out=r['outcome']
            if out=='OPEN':open_count+=1
            if r['recovered']:recovered+=1
            if out not in {'T1','SL'}:continue
            k=(r['underlying'],r['action']);q=buckets.setdefault(k,{'w':0,'l':0,'t1_sec':0.0,'sl_sec':0.0})
            if out=='T1':q['w']+=1;q['t1_sec']+=r['seconds']
            else:q['l']+=1;q['sl_sec']+=r['seconds']
            f=r['features'];cross=(f.get('ema_cross_5m') or {}).get('bars_ago')
            if cross is not None:self._acc_result(cross_bars,cross,out)
            if f.get('daily_zone'):self._acc_result(daily_zones,f.get('daily_zone'),out)
            if f.get('five_zone'):self._acc_result(five_zones,f.get('five_zone'),out)
            try:
                sp=float(f.get('option_spread_pct'))
                if sp>=0:spreads[out].append(sp)
            except (TypeError,ValueError):pass
            mfe[out].append(r['mfe_pct']);mae[out].append(r['mae_pct'])
        for q in buckets.values():
            if q['w']:q['t1_sec']/=q['w']
            if q['l']:q['sl_sec']/=q['l']
        avg=lambda values:round(sum(values)/len(values),2) if values else 0.0
        return {'epoch':RESEARCH_EPOCH,'total':len(records),'open':open_count,'recovered':recovered,'buckets':buckets,'cross_bars':cross_bars,'daily_zones':daily_zones,'five_zones':five_zones,'avg_spread_pct':{k:avg(v) for k,v in spreads.items()},'avg_mfe_pct':{k:avg(v) for k,v in mfe.items()},'avg_mae_pct':{k:avg(v) for k,v in mae.items()}}

class MarketReplay:
    """Historical underlying replay. Exact historical option premium is never fabricated."""
    @staticmethod
    def _features(rows):
        closes=[r['close'] for r in rows];px=closes[-1];e5,e9,e20=ema(closes,5),ema(closes,9),ema(closes,20);adx,pdi,mdi=directional_values(rows,14);a=atr(rows,14);vw=vwap(rows,30);prev=rows[-21:-1];ph=max(r['high'] for r in prev);pl=min(r['low'] for r in prev);avg=sum(r['volume'] for r in prev)/max(1,len(prev));rvol=rows[-1]['volume']/avg if avg else 0;breakout='UP' if px>ph else ('DOWN' if px<pl else 'NONE');trend='BULLISH' if e5>e9>e20 and px>vw and pdi>=mdi else ('BEARISH' if e5<e9<e20 and px<vw and mdi>=pdi else 'MIXED');return {'price':px,'breakout':breakout,'trend':trend,'adx':adx,'rvol':rvol,'atr':a,'ema_gap_pct':abs(e5-e20)/max(px,1)*100}
    async def run(self,symbol,limit=600):
        rows=await delta_market_service.get_candles(symbol,'5m',max(120,min(int(limit),600)));events=[]
        for i in range(40,len(rows)-7):
            f=self._features(rows[:i+1]);aligned=(f['breakout']=='UP' and f['trend']=='BULLISH') or (f['breakout']=='DOWN' and f['trend']=='BEARISH')
            if not aligned:continue
            entry=rows[i]['close'];risk=max(f['atr'],entry*.0005);side=f['breakout'];out='OPEN';bars=0;sl=entry-risk if side=='UP' else entry+risk;t1=entry+risk*settings.RR_T1 if side=='UP' else entry-risk*settings.RR_T1
            for k in range(i+1,min(len(rows),i+7)):
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
