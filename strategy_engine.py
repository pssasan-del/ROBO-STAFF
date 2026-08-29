import asyncio,time,json,math
from collections import defaultdict
from config import settings,logger
from delta_market_service import delta_market_service
from strategy_store import strategy_store


def ema(vals,n):
    if not vals:return 0.0
    a=2/(n+1); out=float(vals[0])
    for v in vals[1:]:out=a*float(v)+(1-a)*out
    return out

def sma(vals,n):
    r=vals[-n:] if vals else []; return sum(map(float,r))/len(r) if r else 0.0

def rsi(vals,n=14):
    if len(vals)<n+1:return 50.0
    ds=[float(vals[i])-float(vals[i-1]) for i in range(1,len(vals))]
    g=sum(max(x,0) for x in ds[-n:])/n; l=sum(max(-x,0) for x in ds[-n:])/n
    return 100.0 if l==0 else 100-(100/(1+g/l))

def atr(rows,n=14):
    if len(rows)<2:return 0.0
    tr=[]
    for i in range(1,len(rows)):
        h,l,pc=rows[i]['high'],rows[i]['low'],rows[i-1]['close']; tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sma(tr,n)

def vwap(rows,n=30):
    rs=rows[-n:]; pv=sum(((x['high']+x['low']+x['close'])/3)*x['volume'] for x in rs); vol=sum(x['volume'] for x in rs)
    return pv/vol if vol else rs[-1]['close']

class StrategyEngine:
    def __init__(self): self.alert_cb=None; self.last_alert={}; self.last_scan={}; self.running=True; self.last_loop_heartbeat=0.0; self.last_scan_at=0.0
    def set_alert_callback(self,cb):self.alert_cb=cb

    def _indicator(self,spec,rows,offset=0):
        rs=rows[:-offset] if offset else rows
        if not rs: raise ValueError('no candle history')
        ind=spec.get('indicator'); p=int(spec.get('period') or 0); mult=float(spec.get('multiplier') or 1)
        closes=[x['close'] for x in rs]; vols=[x['volume'] for x in rs]
        if ind=='close':v=rs[-1]['close']
        elif ind=='open':v=rs[-1]['open']
        elif ind=='high':v=rs[-1]['high']
        elif ind=='low':v=rs[-1]['low']
        elif ind=='ema':v=ema(closes,p)
        elif ind=='sma':v=sma(closes,p)
        elif ind=='rsi':v=rsi(closes,p or 14)
        elif ind=='vwap':v=vwap(rs,p or 30)
        elif ind=='volume':v=rs[-1]['volume']
        elif ind=='volume_sma':v=sma(vols,p or 20)
        elif ind=='atr':v=atr(rs,p or 14)
        elif ind=='highest':
            # breakout benchmark excludes current candle
            base=rs[:-1] if len(rs)>1 else rs; v=max(x['high'] for x in base[-p:])
        elif ind=='lowest':
            base=rs[:-1] if len(rs)>1 else rs; v=min(x['low'] for x in base[-p:])
        elif ind=='previous_high':v=rs[-2]['high'] if len(rs)>=2 else rs[-1]['high']
        elif ind=='previous_low':v=rs[-2]['low'] if len(rs)>=2 else rs[-1]['low']
        else:raise ValueError(f'unsupported indicator {ind}')
        return float(v)*mult

    def _right(self,spec,rows,offset=0):
        if spec.get('type')=='value':return float(spec['value'])
        return self._indicator(spec,rows,offset)

    def _rule(self,rule,rows):
        op=rule['op']; left=self._indicator(rule['left'],rows); right=self._right(rule['right'],rows)
        if op=='>':ok=left>right
        elif op=='>=':ok=left>=right
        elif op=='<':ok=left<right
        elif op=='<=':ok=left<=right
        elif op=='==':ok=math.isclose(left,right,rel_tol=1e-6,abs_tol=1e-8)
        elif op in ('cross_above','cross_below'):
            lp=self._indicator(rule['left'],rows,1); rp=self._right(rule['right'],rows,1)
            ok=(lp<=rp and left>right) if op=='cross_above' else (lp>=rp and left<right)
        else:raise ValueError(f'unsupported op {op}')
        return ok,left,right

    async def evaluate(self,row,candles=None):
        data=json.loads(row['rules_json']) if isinstance(row.get('rules_json'),str) else row['rules_json']
        maxp=max([int(x.get('left',{}).get('period') or 0) for x in data['rules']]+[int(x.get('right',{}).get('period') or 0) for x in data['rules']]+[60])
        candles=candles or await delta_market_service.get_candles(data['symbol'],data['timeframe'],min(600,maxp+15))
        if len(candles)<max(20,min(maxp+2,60)):return {'status':'INSUFFICIENT_HISTORY','matched':False,'candles':len(candles)}
        checks=[]
        for r in data['rules']:
            ok,lft,rgt=self._rule(r,candles); checks.append({'ok':ok,'left':lft,'right':rgt,'op':r['op']})
        matched=all(x['ok'] for x in checks); px=candles[-1]['close']
        return {'status':'MATCH' if matched else 'NO_MATCH','matched':matched,'price':px,'checks':checks,'strategy':data}

    async def scan_once(self,owner_id=None):
        self.last_scan_at=time.time()
        rows=strategy_store.list_active()
        if owner_id is not None: rows=[r for r in rows if int(r['owner_id'])==int(owner_id)]
        grouped=defaultdict(list)
        for r in rows:
            d=json.loads(r['rules_json']); grouped[(d['symbol'],d['timeframe'])].append(r)
        results={}
        for (symbol,tf),group in grouped.items():
            try:candles=await delta_market_service.get_candles(symbol,tf,600)
            except Exception as e:
                logger.warning('[STRATEGY_ENGINE] candles failed %s %s: %s',symbol,tf,e)
                for r in group:results[r['id']]={'status':'ERROR','error':str(e)[:150]}
                continue
            for r in group:
                try:
                    meta=await self.evaluate(r,candles); results[r['id']]=meta; self.last_scan[r['id']]=meta
                    if meta['matched']:
                        key=f"{r['owner_id']}:{r['id']}"; now=time.time(); cool=settings.ALERT_COOLDOWN_MINUTES*60
                        if now-self.last_alert.get(key,0)>=cool:
                            self.last_alert[key]=now
                            if self.alert_cb:await self.alert_cb(int(r['owner_id']),self.format_signal(r,meta))
                except Exception as e:
                    logger.exception('[STRATEGY_ENGINE] strategy %s failed: %s',r['id'],e); results[r['id']]={'status':'ERROR','error':str(e)[:150]}
        return results

    @staticmethod
    def format_signal(row,meta):
        d=meta['strategy']; return (f"🚨 *DELTA STRATEGY MATCH*\n\n*{d['name']}*\n{d['symbol']} • {d['timeframe']} • `{d['side']}`\nPrice: `{meta['price']:.8g}`\nRules matched: `{len(meta['checks'])}/{len(meta['checks'])}`\n\nPaper signal only • No auto-trading")

    async def loop(self):
        while self.running:
            self.last_loop_heartbeat=time.time()
            try:
                if strategy_store.list_active():await self.scan_once()
            except asyncio.CancelledError:raise
            except Exception as e:logger.exception('[STRATEGY_ENGINE] loop error: %s',e)
            await asyncio.sleep(max(10,settings.SCAN_INTERVAL_SECONDS))

engine=StrategyEngine()
