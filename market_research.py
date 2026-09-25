import json, os, threading, time
from collections import deque
from datetime import datetime, timezone

from config import settings, logger
from delta_market_service import delta_market_service
from strategy_engine import ema, atr, vwap, directional_values


class ResearchStore:
    """Compact research telemetry only: no raw candle arrays, prompts, chat, or credentials.
    PostgreSQL keeps the newest 500 signal rows. RAM fallback is bounded to 200 rows.
    """
    def __init__(self):
        self.lock=threading.RLock(); self.rows=deque(maxlen=200); self.pg=False; self.conn=None
        try:
            if settings.DATABASE_URL:
                import psycopg
                self.conn=psycopg.connect(settings.DATABASE_URL,autocommit=True); self.pg=True
                with self.conn.cursor() as cur:
                    cur.execute('''CREATE TABLE IF NOT EXISTS delta_research_signals(
                        signal_key TEXT PRIMARY KEY, created_at DOUBLE PRECISION NOT NULL,
                        underlying TEXT, action TEXT, direction TEXT, option_symbol TEXT,
                        entry DOUBLE PRECISION, sl DOUBLE PRECISION, t1 DOUBLE PRECISION,
                        score INTEGER, ai_status TEXT, features_json TEXT,
                        outcome TEXT, outcome_seconds DOUBLE PRECISION, outcome_price DOUBLE PRECISION,
                        sl_later_t1 BOOLEAN DEFAULT FALSE, updated_at TEXT NOT NULL)''')
                logger.info('[RESEARCH] compact PostgreSQL telemetry enabled')
        except Exception as exc:
            logger.warning('[RESEARCH] PostgreSQL unavailable; bounded RAM fallback: %s',exc);self.pg=False;self.conn=None

    def add(self,key,candidate,features):
        row={'signal_key':key,'created_at':candidate.created,'underlying':candidate.underlying,'action':candidate.action,
             'direction':candidate.direction,'option_symbol':candidate.option_symbol,'entry':candidate.premium,'sl':candidate.sl,
             't1':candidate.t1,'score':candidate.score,'ai_status':candidate.ai_status,'features':features,'outcome':'OPEN'}
        with self.lock:
            if self.pg:
                with self.conn.cursor() as cur:
                    cur.execute('''INSERT INTO delta_research_signals(signal_key,created_at,underlying,action,direction,option_symbol,entry,sl,t1,score,ai_status,features_json,outcome,updated_at)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'OPEN',%s)
                        ON CONFLICT(signal_key) DO NOTHING''',(key,candidate.created,candidate.underlying,candidate.action,candidate.direction,candidate.option_symbol,candidate.premium,candidate.sl,candidate.t1,candidate.score,candidate.ai_status,json.dumps(features,separators=(',',':')),datetime.now(timezone.utc).isoformat()))
                    cur.execute('''DELETE FROM delta_research_signals WHERE signal_key IN (SELECT signal_key FROM delta_research_signals ORDER BY created_at DESC OFFSET 500)''')
            else:self.rows.append(row)

    def resolve(self,key,outcome,seconds,price):
        with self.lock:
            if self.pg:
                with self.conn.cursor() as cur:cur.execute('UPDATE delta_research_signals SET outcome=%s,outcome_seconds=%s,outcome_price=%s,updated_at=%s WHERE signal_key=%s',(outcome,float(seconds),float(price),datetime.now(timezone.utc).isoformat(),key))
            else:
                for r in reversed(self.rows):
                    if r['signal_key']==key:r.update(outcome=outcome,outcome_seconds=float(seconds),outcome_price=float(price));break

    def mark_recovery(self,key):
        with self.lock:
            if self.pg:
                with self.conn.cursor() as cur:cur.execute('UPDATE delta_research_signals SET sl_later_t1=TRUE,updated_at=%s WHERE signal_key=%s',(datetime.now(timezone.utc).isoformat(),key))
            else:
                for r in reversed(self.rows):
                    if r['signal_key']==key:r['sl_later_t1']=True;break

    def summary(self):
        with self.lock:
            if self.pg:
                with self.conn.cursor() as cur:
                    cur.execute("SELECT underlying,action,outcome,COUNT(*),AVG(outcome_seconds) FROM delta_research_signals WHERE outcome IN ('T1','SL') GROUP BY underlying,action,outcome")
                    grouped=cur.fetchall()
                    cur.execute("SELECT COUNT(*) FROM delta_research_signals WHERE outcome='SL' AND sl_later_t1=TRUE")
                    recovered=int(cur.fetchone()[0])
                    cur.execute("SELECT COUNT(*) FROM delta_research_signals")
                    total=int(cur.fetchone()[0])
            else:
                grouped=[]; recovered=sum(bool(r.get('sl_later_t1')) for r in self.rows); total=len(self.rows)
                acc={}
                for r in self.rows:
                    if r.get('outcome') not in {'T1','SL'}:continue
                    k=(r['underlying'],r['action'],r['outcome']);q=acc.setdefault(k,[0,0.0]);q[0]+=1;q[1]+=float(r.get('outcome_seconds') or 0)
                grouped=[(*k,v[0],v[1]/v[0] if v[0] else 0) for k,v in acc.items()]
        buckets={}
        for und,action,outcome,count,avgsec in grouped:
            q=buckets.setdefault((und,action),{'w':0,'l':0,'t1_sec':0,'sl_sec':0})
            if outcome=='T1':q['w']=int(count);q['t1_sec']=float(avgsec or 0)
            else:q['l']=int(count);q['sl_sec']=float(avgsec or 0)
        return {'total':total,'recovered':recovered,'buckets':buckets}


class MarketReplay:
    """Historical underlying replay. Exact historical option premium is never fabricated."""
    @staticmethod
    def _features(rows):
        closes=[r['close'] for r in rows]; px=closes[-1]; e5,e9,e20=ema(closes,5),ema(closes,9),ema(closes,20); adx,pdi,mdi=directional_values(rows,14); a=atr(rows,14); vw=vwap(rows,30)
        prev=rows[-21:-1]; ph=max(r['high'] for r in prev);pl=min(r['low'] for r in prev);avg=sum(r['volume'] for r in prev)/max(1,len(prev));rvol=rows[-1]['volume']/avg if avg else 0
        breakout='UP' if px>ph else ('DOWN' if px<pl else 'NONE')
        trend='BULLISH' if e5>e9>e20 and px>vw and pdi>=mdi else ('BEARISH' if e5<e9<e20 and px<vw and mdi>=pdi else 'MIXED')
        return {'price':px,'breakout':breakout,'trend':trend,'adx':adx,'rvol':rvol,'atr':a,'ema_gap_pct':abs(e5-e20)/max(px,1)*100}

    async def run(self,symbol,limit=600):
        rows=await delta_market_service.get_candles(symbol,'5m',max(120,min(int(limit),600)))
        events=[]
        for i in range(40,len(rows)-7):
            f=self._features(rows[:i+1])
            aligned=(f['breakout']=='UP' and f['trend']=='BULLISH') or (f['breakout']=='DOWN' and f['trend']=='BEARISH')
            if not aligned:continue
            entry=rows[i]['close'];risk=max(f['atr'],entry*.0005);side=f['breakout'];out='OPEN';bars=0
            sl=entry-risk if side=='UP' else entry+risk;t1=entry+risk*settings.RR_T1 if side=='UP' else entry-risk*settings.RR_T1
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
        return {'events':len(events),'resolved':len(done),'w':w,'l':l,'rate':round(100*w/(w+l),1) if w+l else 0.0,
                'avg_bars':round(sum(e[1] for e in done)/len(done),1) if done else 0.0,
                'avg_adx':round(sum(e[2] for e in done)/len(done),1) if done else 0.0,
                'avg_rvol':round(sum(e[3] for e in done)/len(done),2) if done else 0.0}

research_store=ResearchStore();market_replay=MarketReplay()
