"""MASTER MIND BTC 5m scalp signal engine — simple alert edition.

Separate from ROBO STAFF first strategy/cooldowns/research. Uses public Delta
market/options data only and never executes orders.

Locked stack: EMA9, EMA95, McGinley14, Fibonacci pivots, Momentum10, Volume.
"""
from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone

from config import logger, settings
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from strategy_engine import ema, fibonacci_pivots

MASTER_MIND_VERSION = "MASTER_MIND_BTC_5M_V2_SIMPLE_2026-09-29"
MASTER_MIND_SYMBOL = "BTCUSD"
MASTER_MIND_COOLDOWN_SECONDS = 10 * 60


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _ts(v):
    x = _f(v)
    return x / 1000.0 if x > 100_000_000_000 else x


def _closed(rows, seconds):
    out = list(rows or [])
    now = time.time()
    while out:
        t = _ts(out[-1].get('time'))
        if t <= 0 or t + seconds <= now - 2:
            break
        out.pop()
    return out


def _ema(values, period):
    return float(ema([float(x) for x in values], period))


def _mcginley(closes, period=14, k=0.6):
    vals = [float(x) for x in closes]
    if not vals:
        return []
    md = vals[0]
    out = [md]
    for px in vals[1:]:
        if md <= 0 or px <= 0:
            md = px
        else:
            ratio = max(0.25, min(4.0, px / md))
            md += (px - md) / max(k * period * ratio**4, 1e-9)
        out.append(md)
    return out


def _momentum(closes, period=10):
    vals = [float(x) for x in closes]
    return vals[-1] - vals[-1-period] if len(vals) > period else 0.0


def _pivot_map(p):
    return {
        'P': _f(p.get('pivot')),
        'R1': _f(p.get('fib_r1') or p.get('r1')),
        'R2': _f(p.get('fib_r2') or p.get('r2')),
        'R3': _f(p.get('fib_r3') or p.get('r3')),
        'S1': _f(p.get('fib_s1') or p.get('s1')),
        'S2': _f(p.get('fib_s2') or p.get('s2')),
        'S3': _f(p.get('fib_s3') or p.get('s3')),
    }


def _nearest(price, levels):
    vals = [(n,v) for n,v in levels.items() if v > 0]
    return min(vals, key=lambda x: abs(x[1]-price)) if vals else ('N/A', 0.0)


def _cross(prev_close, close, levels, up=True):
    hits=[]
    for n,v in levels.items():
        if v <= 0: continue
        if up and prev_close <= v < close: hits.append((n,v))
        if not up and prev_close >= v > close: hits.append((n,v))
    if not hits: return None
    return max(hits,key=lambda x:x[1]) if up else min(hits,key=lambda x:x[1])


def _next(price, levels, up=True, skip=None):
    vals=[(n,v) for n,v in levels.items() if v>0 and n!=skip]
    if up:
        q=sorted((n,v) for n,v in vals if v>price)
        return q[0] if q else ('EXT', price*1.004)
    q=sorted(((n,v) for n,v in vals if v<price), key=lambda x:x[1], reverse=True)
    return q[0] if q else ('EXT', price*0.996)


def _wick(row, bullish):
    o,h,l,c=(_f(row.get(k)) for k in ('open','high','low','close'))
    body=max(abs(c-o), max(c,1.0)*0.00015)
    lower=min(o,c)-l; upper=h-max(o,c)
    return lower>=1.2*body and c>=o if bullish else upper>=1.2*body and c<=o


def _near(price, level, pct=0.0025):
    return level>0 and abs(price-level)/max(price,1e-9)<=pct


def _fmt(v):
    return f"{v:,.1f}" if abs(v)>=1000 else f"{v:.4f}"


class MasterMindScalpEngine:
    def __init__(self):
        self.running=True
        self.alert_cb=None
        self.last_alert_at=0.0
        self.last_alert_key=''
        self.last_scan_at=0.0
        self.last_status='INIT'
        self.last_reason=''

    def set_alert_callback(self, cb): self.alert_cb=cb

    async def _alert(self,text):
        if self.alert_cb: await self.alert_cb(text)

    async def _best_strike(self, direction, action, spot, pivots):
        try:
            rows=await delta_options_service.get_chain('BTC')
            parsed=[delta_options_service._snapshot(r) for r in rows]
            parsed=[x for x in parsed if x.get('strike') and x.get('expiry')]
            if not parsed: return 'N/A','chain unavailable'
            expiries=sorted({str(x['expiry']) for x in parsed})
            today=datetime.now(timezone.utc).date()
            expiry=next((e for e in expiries if datetime.fromisoformat(e).date()>=today),expiries[0])
            strikes=sorted({float(x['strike']) for x in parsed if str(x.get('expiry'))==expiry})
            if not strikes: return 'N/A',expiry
            if 'SELL OTM PUT' in action:
                supports=[v for n,v in pivots.items() if n in {'P','S1','S2','S3'} and 0<v<spot]
                anchor=max(supports) if supports else spot*0.995
                eligible=[s for s in strikes if s<=anchor and s<spot]
                strike=max(eligible) if eligible else min(strikes,key=lambda s:abs(s-spot))
                return f'P-{int(strike)}', expiry
            if 'SELL OTM CALL' in action:
                resist=[v for n,v in pivots.items() if n in {'P','R1','R2','R3'} and v>spot]
                anchor=min(resist) if resist else spot*1.005
                eligible=[s for s in strikes if s>=anchor and s>spot]
                strike=min(eligible) if eligible else min(strikes,key=lambda s:abs(s-spot))
                return f'C-{int(strike)}', expiry
            atm=min(strikes,key=lambda s:abs(s-spot))
            return f"{'C' if direction=='BULLISH' else 'P'}-{int(atm)}", expiry
        except Exception as exc:
            logger.debug('[MASTER_MIND] strike lookup failed: %s',exc)
            return 'N/A','chain unavailable'

    async def evaluate(self):
        rows=_closed(await delta_market_service.get_candles(MASTER_MIND_SYMBOL,'5m',180),300)
        days=_closed(await delta_market_service.get_candles(MASTER_MIND_SYMBOL,'1d',42),86400)
        if len(rows)<110 or len(days)<2:
            return None,'insufficient completed candles'

        closes=[_f(r.get('close')) for r in rows]
        cur,prev=rows[-1],rows[-2]
        close,prev_close=closes[-1],closes[-2]
        o,h,l=(_f(cur.get(k)) for k in ('open','high','low'))
        e9,e95=_ema(closes,9),_ema(closes,95)
        mc=_mcginley(closes,14); md,prev_md=mc[-1],mc[-2]
        mom,prev_mom=_momentum(closes,10),_momentum(closes[:-1],10)
        vols=[_f(r.get('volume')) for r in rows]
        vol=vols[-1]; sma20=sum(vols[-21:-1])/20 if len(vols)>=21 else max(vol,1.0)
        vr=vol/max(sma20,1e-9)
        green,red=close>o,close<o
        piv=_pivot_map(fibonacci_pivots(days[-1]))
        near_name,near_val=_nearest(close,piv)
        up_break,down_break=_cross(prev_close,close,piv,True),_cross(prev_close,close,piv,False)

        trend_long=close>e95 and close>e9>md
        trend_short=close<e95 and close<e9<md
        mom_up=mom>0 and mom>prev_mom
        mom_dn=mom<0 and mom<prev_mom
        vol_ok=vr>=1.15

        setup=direction=action=trigger=None
        reason=[]; sl=tp1=tp2=0.0; confidence=0

        if trend_long and up_break and green and vol_ok and mom_up:
            setup='Breakout'; direction='BULLISH'; action='FUTURE LONG + SELL OTM PUT'
            ln,lv=up_break; n1,t1=_next(close,piv,True,ln)
            trigger=f'5m close above {ln} {_fmt(lv)}'
            sl=lv*0.999; tp1=t1; tp2=_next(t1+1e-9,piv,True,n1)[1]
            reason=['EMA95 uptrend',f'{ln} breakout',f'Momentum {prev_mom:.0f}→{mom:.0f}',f'Volume {vr:.2f}x']
            confidence=9 if vr>=1.5 else 8
        elif trend_short and down_break and red and vol_ok and mom_dn:
            setup='Breakout'; direction='BEARISH'; action='FUTURE SHORT + SELL OTM CALL'
            ln,lv=down_break; n1,t1=_next(close,piv,False,ln)
            trigger=f'5m close below {ln} {_fmt(lv)}'
            sl=lv*1.001; tp1=t1; tp2=_next(t1-1e-9,piv,False,n1)[1]
            reason=['EMA95 downtrend',f'{ln} breakdown',f'Momentum {prev_mom:.0f}→{mom:.0f}',f'Volume {vr:.2f}x']
            confidence=9 if vr>=1.5 else 8

        if setup is None:
            refs=[('EMA9',e9),('McGinley14',md)]+list(piv.items())
            long_touch=[(n,v) for n,v in refs if v>0 and l<=v*1.0015 and close>=v]
            short_touch=[(n,v) for n,v in refs if v>0 and h>=v*0.9985 and close<=v]
            lr=min(long_touch,key=lambda x:abs(close-x[1])) if long_touch else None
            sr=min(short_touch,key=lambda x:abs(close-x[1])) if short_touch else None
            if trend_long and lr and _wick(cur,True) and mom>prev_mom:
                rn,rv=lr; setup='Pullback'; direction='BULLISH'; action='FUTURE LONG + SELL OTM PUT'
                trigger=f'Bullish rejection from {rn} {_fmt(rv)}'
                sl=min(rv,md)*0.999; n1,tp1=_next(close,piv,True); tp2=_next(tp1+1e-9,piv,True,n1)[1]
                reason=['EMA95 uptrend',f'{rn} pullback','Bullish rejection',f'Momentum {prev_mom:.0f}→{mom:.0f}',f'Volume {vr:.2f}x']
                confidence=8 if vr>=1 else 7
            elif trend_short and sr and _wick(cur,False) and mom<prev_mom:
                rn,rv=sr; setup='Pullback'; direction='BEARISH'; action='FUTURE SHORT + SELL OTM CALL'
                trigger=f'Bearish rejection from {rn} {_fmt(rv)}'
                sl=max(rv,md)*1.001; n1,tp1=_next(close,piv,False); tp2=_next(tp1-1e-9,piv,False,n1)[1]
                reason=['EMA95 downtrend',f'{rn} pullback','Bearish rejection',f'Momentum {prev_mom:.0f}→{mom:.0f}',f'Volume {vr:.2f}x']
                confidence=8 if vr>=1 else 7

        if setup is None:
            spike=vr>=1.20
            if prev_mom>200 and mom<prev_mom and _near(close,near_val) and _wick(cur,False) and spike:
                setup='Exhaustion Reversal'; direction='BEARISH'; action='SELL OTM CALL'
                trigger=f'Momentum reversal near {near_name} {_fmt(near_val)}'
                sl=h*1.001; tp1=e9; tp2=_next(tp1-1e-9,piv,False)[1]
                reason=[f'{near_name} rejection',f'Momentum {prev_mom:.0f}→{mom:.0f}',f'Volume {vr:.2f}x']
                confidence=9 if vr>=1.5 else 8
            elif prev_mom<-150 and mom>prev_mom and _near(close,near_val) and _wick(cur,True) and spike:
                setup='Exhaustion Reversal'; direction='BULLISH'; action='SELL OTM PUT'
                trigger=f'Momentum reversal near {near_name} {_fmt(near_val)}'
                sl=l*0.999; tp1=e9; tp2=_next(tp1+1e-9,piv,True)[1]
                reason=[f'{near_name} rejection',f'Momentum {prev_mom:.0f}→{mom:.0f}',f'Volume {vr:.2f}x']
                confidence=9 if vr>=1.5 else 8

        if setup is None:
            between=min(e9,e95)<=close<=max(e9,e95)
            flat=vr<0.90 and abs(mom)<50
            return None,'NO_TRADE_CHOP' if between and flat else 'WAIT_CONFLUENCE'

        strike,expiry=await self._best_strike(direction,action,close,piv)
        side='BUY' if direction=='BULLISH' else 'SELL'
        strength='STRONG' if confidence>=8 else 'VALID'
        score=confidence*10
        confirmations='\n'.join(f'• {x}' for x in reason[:5])
        alert=(
            '🔴🚨 MASTER MIND SIGNAL ALERT 🚨🔴\n\n'
            '📊 BTCUSD 5M\n'
            f'🎯 {side} | {strength}\n'
            f'⭐ Score: {score}/100\n'
            f'Setup: {setup}\n'
            f'Action: {action}\n'
            f'Strike: {strike} | Exp: {expiry}\n\n'
            f'Entry: {_fmt(close)}\n'
            f'SL: {_fmt(sl)}\n'
            f'T1: {_fmt(tp1)}\n'
            f'T2: {_fmt(tp2)}\n\n'
            'Confirmations:\n'
            f'{confirmations}\n\n'
            f'Trigger: {trigger}\n'
            '⚠️ SIGNAL ONLY — NO ORDER EXECUTED'
        )
        key=f'{setup}:{direction}:{cur.get("time")}:{strike}'
        return {'key':key,'alert':alert,'setup':setup,'direction':direction,'action':action},'SIGNAL'

    async def scan_once(self):
        self.last_scan_at=time.time()
        signal,status=await self.evaluate()
        self.last_status=status
        if not signal:
            self.last_reason=status
            return {'status':status}
        now=time.time()
        if signal['key']==self.last_alert_key:
            return {'status':'DUPLICATE_CANDLE'}
        if now-self.last_alert_at<MASTER_MIND_COOLDOWN_SECONDS:
            return {'status':'MASTER_MIND_COOLDOWN'}
        self.last_alert_key=signal['key']; self.last_alert_at=now; self.last_reason=signal['setup']
        await self._alert(signal['alert'])
        logger.info('[MASTER_MIND] %s %s %s',signal['setup'],signal['direction'],signal['action'])
        return {'status':'SIGNAL','setup':signal['setup'],'direction':signal['direction']}

    async def loop(self):
        while True:
            try:
                if self.running: await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_status='ERROR'; self.last_reason=str(exc)[:160]
                logger.warning('[MASTER_MIND] scan failed safely: %s',exc)
            await asyncio.sleep(max(30,settings.DELTA_SIGNAL_SCAN_SECONDS))


master_mind_scalp_engine=MasterMindScalpEngine()
