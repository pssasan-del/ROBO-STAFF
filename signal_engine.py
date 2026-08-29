import asyncio, time
from dataclasses import dataclass
from typing import Callable, Awaitable, Dict
from config import settings, logger
from mudrex_service import mudrex_service
from indicators import ema,rsi,atr,vwap,fib_pivots

@dataclass
class Signal:
    symbol:str; side:str; entry:float; sl:float; target:float; rr:float; score:int; reason:str

class CryptoSignalEngine:
    def __init__(self):
        self.running=False; self.alert_cb=None; self.last_alert:Dict[str,float]={}; self.last_scan={}
    def set_alert_callback(self,cb): self.alert_cb=cb
    def start(self): self.running=True
    def stop(self): self.running=False

    async def analyze(self,symbol):
        batches=await mudrex_service.get_klines([symbol],'5m',90)
        daily=await mudrex_service.get_klines([symbol],'1d',3)
        c=batches.get(symbol,[]); d=daily.get(symbol,[])
        if len(c)<60 or len(d)<2: return None, {'status':'INSUFFICIENT_HISTORY','candles':len(c)}
        # Use prior completed daily candle for pivots when possible.
        piv=fib_pivots(d[-2] if len(d)>=2 else d[-1])
        closes=[float(x[4]) for x in c]; vols=[float(x[5]) for x in c]
        px=closes[-1]; e20=ema(closes[-60:],20); e50=ema(closes[-80:],50); rv=rsi(closes,14); vw=vwap(c,30); a=atr(c,14)
        avgv=sum(vols[-21:-1])/20 if len(vols)>=21 else sum(vols)/len(vols)
        vol_ok=vols[-1] >= avgv*1.10
        high20=max(float(x[2]) for x in c[-21:-1]); low20=min(float(x[3]) for x in c[-21:-1])
        bull=[px>piv['P'],e20>e50,px>vw,rv>=55,vol_ok,px>=high20]
        bear=[px<piv['P'],e20<e50,px<vw,rv<=45,vol_ok,px<=low20]
        side=None; checks=None
        if sum(bull)>=5 and bull[0] and bull[1]: side='LONG'; checks=bull
        elif sum(bear)>=5 and bear[0] and bear[1]: side='SHORT'; checks=bear
        if not side:
            return None, {'status':'NO_TRADE','price':px,'rsi':round(rv,2),'ema20':e20,'ema50':e50,'pivot':piv['P']}
        risk=max(a*1.15,px*0.002)
        if side=='LONG': sl=px-risk; target=px+risk*settings.MIN_RR
        else: sl=px+risk; target=px-risk*settings.MIN_RR
        score=min(100,55+sum(checks)*7)
        sig=Signal(symbol,side,px,sl,target,settings.MIN_RR,score,f"Fib P + EMA20/50 + VWAP + RSI + volume + 20-candle breakout")
        return sig, {'status':'SIGNAL','rsi':rv,'pivot':piv['P']}

    async def scan_once(self):
        results={}
        for s in settings.symbols():
            try:
                sig,meta=await self.analyze(s); results[s]=meta; self.last_scan[s]=meta
                if sig:
                    key=f'{s}:{sig.side}'; now=time.time(); cool=settings.ALERT_COOLDOWN_MINUTES*60
                    if now-self.last_alert.get(key,0)>=cool:
                        self.last_alert[key]=now
                        if self.alert_cb:
                            await self.alert_cb(self.format_signal(sig))
            except Exception as e:
                logger.exception('[ENGINE] %s scan failed: %s',s,e); results[s]={'status':'ERROR','error':str(e)[:140]}
        return results

    @staticmethod
    def format_signal(s:Signal):
        return (f"🚨 *MUDREX PAPER SIGNAL*\n\n"
                f"{s.symbol} — *{s.side}*\n"
                f"Entry: `{s.entry:.6g}`\nSL: `{s.sl:.6g}`\nTarget: `{s.target:.6g}`\n"
                f"R:R: `1:{s.rr:.2f}` | Score: `{s.score}/100`\n"
                f"Logic: {s.reason}\n\nSignal only • No auto-trading")

    async def loop(self):
        while True:
            try:
                if self.running: await self.scan_once()
            except asyncio.CancelledError: raise
            except Exception as e: logger.exception('[ENGINE] loop error: %s',e)
            await asyncio.sleep(max(10,settings.SCAN_INTERVAL_SECONDS))

engine=CryptoSignalEngine()
