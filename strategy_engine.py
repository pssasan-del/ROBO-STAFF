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

def ema_series(vals,n):
    if not vals:return []
    a=2/(n+1); out=[float(vals[0])]
    for v in vals[1:]:out.append(a*float(v)+(1-a)*out[-1])
    return out

def smma_series(vals,n):
    if not vals:return []
    out=[]
    for i,v in enumerate(vals):
        v=float(v)
        if i==0:out.append(v)
        elif i<n:out.append(sum(map(float,vals[:i+1]))/(i+1))
        elif i==n-1:out.append(sum(map(float,vals[:n]))/n)
        else:out.append((out[-1]*(n-1)+v)/n)
    return out

def sma(vals,n):
    r=vals[-n:] if vals else []; return sum(map(float,r))/len(r) if r else 0.0

def rsi(vals,n=14):
    if len(vals)<n+1:return 50.0
    ds=[float(vals[i])-float(vals[i-1]) for i in range(1,len(vals))]
    g=sum(max(x,0) for x in ds[-n:])/n; l=sum(max(-x,0) for x in ds[-n:])/n
    return 100.0 if l==0 else 100-(100/(1+g/l))

def rsi_series(vals,n=14):
    if not vals:return []
    out=[]
    for i in range(len(vals)):
        if i<n: out.append(50.0)
        else: out.append(rsi(vals[:i+1],n))
    return out

def atr(rows,n=14):
    if len(rows)<2:return 0.0
    tr=[]
    for i in range(1,len(rows)):
        h,l,pc=rows[i]['high'],rows[i]['low'],rows[i-1]['close']; tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sma(tr,n)

def true_ranges(rows):
    tr=[]
    for i,x in enumerate(rows):
        if i==0:tr.append(x['high']-x['low'])
        else:
            pc=rows[i-1]['close'];tr.append(max(x['high']-x['low'],abs(x['high']-pc),abs(x['low']-pc)))
    return tr

def vwap(rows,n=30):
    rs=rows[-n:]; pv=sum(((x['high']+x['low']+x['close'])/3)*x['volume'] for x in rs); vol=sum(x['volume'] for x in rs)
    return pv/vol if vol else rs[-1]['close']

def macd_values(vals,fast=12,slow=26,signal=9):
    ef=ema_series(vals,fast); es=ema_series(vals,slow); m=[a-b for a,b in zip(ef,es)]; s=ema_series(m,signal); return m[-1],s[-1],m[-1]-s[-1]

def directional_values(rows,n=14):
    if len(rows)<n+2:return 0.0,0.0,0.0
    trs=[]; plus=[]; minus=[]
    for i in range(1,len(rows)):
        up=rows[i]['high']-rows[i-1]['high']; dn=rows[i-1]['low']-rows[i]['low']
        plus.append(up if up>dn and up>0 else 0.0); minus.append(dn if dn>up and dn>0 else 0.0)
        pc=rows[i-1]['close']; trs.append(max(rows[i]['high']-rows[i]['low'],abs(rows[i]['high']-pc),abs(rows[i]['low']-pc)))
    def wilder(xs,p):
        if len(xs)<p:return sum(xs)
        acc=sum(xs[:p]); out=[acc]
        for x in xs[p:]: acc=acc-(acc/p)+x;out.append(acc)
        return out
    trw=wilder(trs,n); pw=wilder(plus,n); mw=wilder(minus,n)
    m=min(len(trw),len(pw),len(mw)); dx=[]; pdi=mdi=0.0
    for i in range(m):
        den=trw[i] or 1e-12;pdi=100*pw[i]/den;mdi=100*mw[i]/den; dx.append(100*abs(pdi-mdi)/(pdi+mdi) if pdi+mdi else 0.0)
    adx=sma(dx,n) if dx else 0.0
    return adx,pdi,mdi

def williams_r(rows,n=14):
    rs=rows[-n:];hh=max(x['high'] for x in rs);ll=min(x['low'] for x in rs);c=rs[-1]['close']
    return -50.0 if hh==ll else -100*(hh-c)/(hh-ll)

def roc(vals,n=12):
    if len(vals)<=n:return 0.0
    b=float(vals[-n-1]);return 0.0 if b==0 else (float(vals[-1])-b)/b*100

def trix(vals,n=15):
    if len(vals)<n+3:return 0.0
    e1=ema_series(vals,n);e2=ema_series(e1,n);e3=ema_series(e2,n)
    if len(e3)<2 or e3[-2]==0:return 0.0
    return (e3[-1]-e3[-2])/e3[-2]*100

def stoch_rsi(vals,n=14):
    rs=rsi_series(vals,n);win=rs[-n:];lo=min(win);hi=max(win)
    return 50.0 if hi==lo else (rs[-1]-lo)/(hi-lo)*100

def bollinger(vals,n=20,k=2):
    rs=list(map(float,vals[-n:]));mid=sum(rs)/len(rs);var=sum((x-mid)**2 for x in rs)/len(rs);sd=math.sqrt(var)
    return mid+k*sd,mid,mid-k*sd

def obv(rows):
    v=0.0
    for i in range(1,len(rows)):
        if rows[i]['close']>rows[i-1]['close']:v+=rows[i]['volume']
        elif rows[i]['close']<rows[i-1]['close']:v-=rows[i]['volume']
    return v

def donchian(rows,n=20):
    rs=rows[-n:];up=max(x['high'] for x in rs);lo=min(x['low'] for x in rs);return up,(up+lo)/2,lo

def alligator(rows):
    med=[(x['high']+x['low'])/2 for x in rows]
    jaw=smma_series(med,13);teeth=smma_series(med,8);lips=smma_series(med,5)
    def shifted(s,shift):return s[-1-shift] if len(s)>shift else s[-1]
    return shifted(jaw,8),shifted(teeth,5),shifted(lips,3)

def supertrend(rows,n=10,mult=3.0):
    if len(rows)<n+2:return rows[-1]['close'] if rows else 0.0
    trs=true_ranges(rows); atrs=[]
    for i in range(len(rows)):atrs.append(sma(trs[:i+1],n))
    final_u=[];final_l=[];st=[]
    for i,x in enumerate(rows):
        hl2=(x['high']+x['low'])/2;bu=hl2+mult*atrs[i];bl=hl2-mult*atrs[i]
        if i==0:fu,fl=bu,bl;cur=fl
        else:
            fu=bu if bu<final_u[-1] or rows[i-1]['close']>final_u[-1] else final_u[-1]
            fl=bl if bl>final_l[-1] or rows[i-1]['close']<final_l[-1] else final_l[-1]
            prev=st[-1]
            if prev==final_u[-1]:cur=fu if x['close']<=fu else fl
            else:cur=fl if x['close']>=fl else fu
        final_u.append(fu);final_l.append(fl);st.append(cur)
    return st[-1]

def fibonacci_pivots(row):
    h,l,c=float(row['high']),float(row['low']),float(row['close']);p=(h+l+c)/3;r=h-l
    return {'pivot':p,'fib_r1':p+0.382*r,'fib_r2':p+0.618*r,'fib_r3':p+r,'fib_s1':p-0.382*r,'fib_s2':p-0.618*r,'fib_s3':p-r}

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
            base=rs[:-1] if len(rs)>1 else rs; v=max(x['high'] for x in base[-(p or 20):])
        elif ind=='lowest':
            base=rs[:-1] if len(rs)>1 else rs; v=min(x['low'] for x in base[-(p or 20):])
        elif ind=='previous_high':v=rs[-2]['high'] if len(rs)>=2 else rs[-1]['high']
        elif ind=='previous_low':v=rs[-2]['low'] if len(rs)>=2 else rs[-1]['low']
        elif ind in {'macd','macd_signal','macd_hist'}:
            m,s,h=macd_values(closes);v={'macd':m,'macd_signal':s,'macd_hist':h}[ind]
        elif ind in {'adx','plus_di','minus_di'}:
            a,di1,di2=directional_values(rs,p or 14);v={'adx':a,'plus_di':di1,'minus_di':di2}[ind]
        elif ind=='williams_r':v=williams_r(rs,p or 14)
        elif ind=='trix':v=trix(closes,p or 15)
        elif ind=='stoch_rsi':v=stoch_rsi(closes,p or 14)
        elif ind in {'bollinger_upper','bollinger_middle','bollinger_lower'}:
            u,m,l=bollinger(closes,p or 20,float(spec.get('stddev') or 2));v={'bollinger_upper':u,'bollinger_middle':m,'bollinger_lower':l}[ind]
        elif ind=='obv':v=obv(rs)
        elif ind in {'donchian_upper','donchian_middle','donchian_lower'}:
            u,m,l=donchian(rs,p or 20);v={'donchian_upper':u,'donchian_middle':m,'donchian_lower':l}[ind]
        elif ind=='roc':v=roc(closes,p or 12)
        elif ind in {'alligator_jaw','alligator_teeth','alligator_lips'}:
            j,t,l=alligator(rs);v={'alligator_jaw':j,'alligator_teeth':t,'alligator_lips':l}[ind]
        elif ind=='supertrend':v=supertrend(rs,p or 10,float(spec.get('multiplier') or 3))
        elif ind in {'pivot','fib_r1','fib_r2','fib_r3','fib_s1','fib_s2','fib_s3'}:
            base=rs[-2] if len(rs)>=2 else rs[-1];v=fibonacci_pivots(base)[ind]
        else:raise ValueError(f'unsupported indicator {ind}')
        # multiplier is a rule multiplier except for supertrend, where it is the ATR factor.
        return float(v) if ind=='supertrend' else float(v)*mult

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
        maxp=max([int(x.get('left',{}).get('period') or 0) for x in data['rules']]+[int(x.get('right',{}).get('period') or 0) for x in data['rules']]+[100])
        candles=candles or await delta_market_service.get_candles(data['symbol'],data['timeframe'],min(600,maxp+80))
        if len(candles)<max(30,min(maxp+5,100)):return {'status':'INSUFFICIENT_HISTORY','matched':False,'candles':len(candles)}
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
