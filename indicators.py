import math

def ema(values,n):
    if not values: return 0.0
    a=2/(n+1); out=float(values[0])
    for v in values[1:]: out=a*float(v)+(1-a)*out
    return out

def rsi(values,n=14):
    if len(values)<n+1: return 50.0
    ds=[float(values[i])-float(values[i-1]) for i in range(1,len(values))]
    gains=[max(x,0) for x in ds[-n:]]; losses=[max(-x,0) for x in ds[-n:]]
    ag=sum(gains)/n; al=sum(losses)/n
    if al==0: return 100.0
    rs=ag/al; return 100-(100/(1+rs))

def atr(candles,n=14):
    if len(candles)<2: return 0.0
    trs=[]
    for i in range(1,len(candles)):
        h,l,pc=float(candles[i][2]),float(candles[i][3]),float(candles[i-1][4])
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(trs[-n:])/max(1,len(trs[-n:]))

def vwap(candles,n=30):
    rows=candles[-n:]; pv=0.0; vol=0.0
    for c in rows:
        h,l,cl,v=map(float,[c[2],c[3],c[4],c[5]])
        typ=(h+l+cl)/3; pv+=typ*v; vol+=v
    return pv/vol if vol else float(rows[-1][4])

def fib_pivots(day_candle):
    h,l,c=map(float,[day_candle[2],day_candle[3],day_candle[4]])
    p=(h+l+c)/3; rng=h-l
    return {'P':p,'R1':p+.382*rng,'R2':p+.618*rng,'S1':p-.382*rng,'S2':p-.618*rng}
