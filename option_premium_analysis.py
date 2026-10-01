"""Pure analytics for ROBO STAFF V4.2 option-premium confirmation.

No network access and no order/execution code lives here. The helpers work on
Delta OHLC rows shaped as: time/open/high/low/close/volume.
"""
from __future__ import annotations

import math


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def ema(values, period):
    vals=[_f(x) for x in values]
    if not vals:
        return 0.0
    a=2.0/(float(period)+1.0)
    out=vals[0]
    for v in vals[1:]:
        out=a*v+(1.0-a)*out
    return out


def rsi(values, period=14):
    vals=[_f(x) for x in values]
    if len(vals)<period+1:
        return 50.0
    ds=[vals[i]-vals[i-1] for i in range(1,len(vals))]
    gains=sum(max(x,0.0) for x in ds[-period:])/period
    losses=sum(max(-x,0.0) for x in ds[-period:])/period
    if losses<=0:
        return 100.0 if gains>0 else 50.0
    rs=gains/losses
    return 100.0-(100.0/(1.0+rs))


def williams_r(rows, period=14):
    if len(rows)<2:
        return -50.0
    win=rows[-period:]
    hh=max(_f(x.get('high')) for x in win)
    ll=min(_f(x.get('low')) for x in win)
    close=_f(win[-1].get('close'))
    if hh<=ll:
        return -50.0
    return -100.0*(hh-close)/(hh-ll)


def atr(rows, period=14):
    if len(rows)<2:
        return 0.0
    tr=[]
    for i in range(1,len(rows)):
        h=_f(rows[i].get('high'));l=_f(rows[i].get('low'));pc=_f(rows[i-1].get('close'))
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    win=tr[-period:]
    return sum(win)/len(win) if win else 0.0


def recent_cross(values, fast=9, slow=18, lookback=3):
    vals=[_f(x) for x in values]
    if len(vals)<slow+3:
        return {'side':'NONE','bars_ago':None}
    for bars_ago in range(max(1,int(lookback))):
        end=len(vals)-bars_ago
        if end<slow+1:
            break
        now=vals[:end];prev=vals[:end-1]
        f_now,s_now=ema(now,fast),ema(now,slow)
        f_prev,s_prev=ema(prev,fast),ema(prev,slow)
        if f_prev<=s_prev and f_now>s_now:
            return {'side':'BULLISH','bars_ago':bars_ago}
        if f_prev>=s_prev and f_now<s_now:
            return {'side':'BEARISH','bars_ago':bars_ago}
    return {'side':'NONE','bars_ago':None}


def structure(rows):
    if len(rows)<12:
        return 'UNKNOWN'
    a,b=rows[-12:-6],rows[-6:]
    ah=max(_f(x.get('high')) for x in a);al=min(_f(x.get('low')) for x in a)
    bh=max(_f(x.get('high')) for x in b);bl=min(_f(x.get('low')) for x in b)
    if bh>ah and bl>al:
        return 'HH/HL'
    if bh<ah and bl<al:
        return 'LH/LL'
    return 'RANGE'


def _relative_volume(rows):
    if len(rows)<8:
        return 0.0
    hist=rows[-21:-1]
    avg=sum(_f(x.get('volume')) for x in hist)/max(1,len(hist))
    return _f(rows[-1].get('volume'))/avg if avg>0 else 0.0


def analyze_premium_rows(rows, overextended_atr=1.80):
    """Analyze the option premium itself as a long instrument.

    For both CE and PE buys, a healthy premium chart is bullish: close above
    premium EMA5 is the hard direction gate. EMA9/18, RSI, W%R, structure and
    recent cross contribute to the score. Very stretched premiums are held for
    a retest instead of being chased.
    """
    rows=list(rows or [])
    if len(rows)<24:
        return {'sufficient':False,'rows':len(rows),'gate_pass':False,'reason':'insufficient premium candles'}
    closes=[_f(x.get('close')) for x in rows]
    close=closes[-1];e5=ema(closes,5);e9=ema(closes,9);e18=ema(closes,18)
    a=max(atr(rows,14),1e-12)
    ext=(close-e5)/a
    cross=recent_cross(closes,9,18,3)
    rv=rsi(closes,14);wr=williams_r(rows,14);st=structure(rows);rvol=_relative_volume(rows)
    candle_above=close>e5
    alignment=e9>e18
    cross_ok=cross.get('side')=='BULLISH' and cross.get('bars_ago') is not None
    rsi_ok=rv>=50.0
    wr_ok=wr>=-50.0
    structure_ok=st=='HH/HL'
    overextended=ext>float(overextended_atr)

    score=0.0
    score+=30.0 if candle_above else 0.0
    score+=20.0 if alignment else 0.0
    score+=15.0 if cross_ok else 0.0
    score+=15.0 if rsi_ok else 0.0
    score+=10.0 if wr_ok else 0.0
    score+=10.0 if structure_ok else 0.0
    if overextended:
        score-=15.0
    score=max(0.0,min(100.0,score))

    lookback=min(3,len(closes)-1)
    base=closes[-1-lookback]
    change_pct=((close-base)/base*100.0) if base>0 else 0.0
    gate_pass=bool(candle_above and not overextended)
    reason='OK' if gate_pass else ('WAIT_RETEST_OVEREXTENDED' if overextended else 'PREMIUM_BELOW_EMA5')
    return {
        'sufficient':True,'rows':len(rows),'gate_pass':gate_pass,'reason':reason,
        'close':close,'ema5':e5,'ema9':e9,'ema18':e18,
        'candle_vs_ema5':'ABOVE' if close>e5 else ('BELOW' if close<e5 else 'AT'),
        'ema9_18_relation':'BULLISH' if e9>e18 else ('BEARISH' if e9<e18 else 'FLAT'),
        'cross_side':cross.get('side'),'cross_bars_ago':cross.get('bars_ago'),
        'rsi':rv,'williams_r':wr,'structure':st,'atr':a,'extension_atr':ext,
        'relative_volume':rvol,'momentum_score':score,'change_3bar_pct':change_pct,
        'overextended':overextended,
    }


def analyze_oi_rows(rows):
    rows=list(rows or [])
    if len(rows)<4:
        return {'sufficient':False,'rows':len(rows),'change_pct':None,'trend':'UNKNOWN'}
    closes=[_f(x.get('close')) for x in rows if _f(x.get('close'))>=0]
    if len(closes)<4:
        return {'sufficient':False,'rows':len(closes),'change_pct':None,'trend':'UNKNOWN'}
    current=closes[-1]
    baseline=sum(closes[-4:-1])/3.0
    change=((current-baseline)/baseline*100.0) if baseline>0 else 0.0
    if change>0.25:
        trend='UP'
    elif change<-0.25:
        trend='DOWN'
    else:
        trend='FLAT'
    return {'sufficient':True,'rows':len(closes),'current_hist':current,'baseline_3bar':baseline,'change_pct':change,'trend':trend}


def classify_premium_oi(premium_change_pct, oi_change_pct):
    """Heuristic only; OI does not uniquely identify trader intent."""
    p=_f(premium_change_pct);o=None if oi_change_pct is None else _f(oi_change_pct)
    if o is None:
        return {'label':'OI_HISTORY_UNAVAILABLE','score':50.0}
    p_up=p>0.25;p_down=p<-0.25;o_up=o>0.25;o_down=o<-0.25
    if p_up and o_up:
        return {'label':'PREMIUM_UP_OI_UP','score':100.0}
    if p_up and o_down:
        return {'label':'PREMIUM_UP_OI_DOWN','score':70.0}
    if p_down and o_up:
        return {'label':'PREMIUM_DOWN_OI_UP','score':25.0}
    if p_down and o_down:
        return {'label':'PREMIUM_DOWN_OI_DOWN','score':35.0}
    return {'label':'PREMIUM_OI_MIXED','score':50.0}
