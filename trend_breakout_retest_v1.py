"""CRYPTO TREND-BREAKOUT RETEST SCALP V1.

Separate BTC/ETH perpetual-futures signal + paper outcome engine.
No order placement. Closed candles only for strategy decisions.

User-requested fast-start adaptation:
- minimum 18 completed candles per timeframe instead of waiting for 250
- always fetch/use more history when Delta provides it
- EMA50/ADX/volume statistics are marked WARMUP_18 until enough history exists
"""
from __future__ import annotations

import asyncio
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from config import settings, logger
from delta_market_service import delta_market_service
from trend_breakout_retest_stats import tbr_stats

STRATEGY = "CRYPTO_TREND_BREAKOUT_RETEST_SCALP_V1"
VERSION = "TBR_V1_18C_2026-10-02"
SYMBOLS = ("BTCUSD", "ETHUSD")
MIN_CANDLES = 18
FETCH_CANDLES = 120
BREAKOUT_LOOKBACK = 12
RETEST_BARS = 3
PAPER_RISK_PCT = 0.0025
MAX_TOTAL_RISK_PCT = 0.005
DAILY_LOSS_LIMIT_PCT = 0.01
MAX_HOLD_5M_BARS = 6
DUPLICATE_SECONDS = 300
QUOTE_STALE_SECONDS = 20
CANDLE_GRACE_SECONDS = 150


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _ts(v):
    x = _f(v, 0.0)
    if x > 1e15: return x / 1_000_000.0
    if x > 1e12: return x / 1000.0
    return x


def _ema_series(values: List[float], period: int) -> List[float]:
    if not values: return []
    alpha = 2.0 / (period + 1.0)
    out = [float(values[0])]
    for x in values[1:]: out.append(alpha * float(x) + (1.0 - alpha) * out[-1])
    return out


def _wilder_series(values: List[float], period: int) -> List[float]:
    if not values: return []
    out = [float(values[0])]
    for i, x in enumerate(values[1:], 1):
        n = min(period, i + 1)
        out.append((out[-1] * (n - 1) + float(x)) / n)
    return out


def _atr_series(rows: List[dict], period=14) -> List[float]:
    if not rows: return []
    tr = [float(rows[0]["high"]) - float(rows[0]["low"])]
    for i in range(1, len(rows)):
        h, l, pc = float(rows[i]["high"]), float(rows[i]["low"]), float(rows[i-1]["close"])
        tr.append(max(h-l, abs(h-pc), abs(l-pc)))
    return _wilder_series(tr, period)


def _adx_di(rows: List[dict], period=14):
    if len(rows) < 3: return 0.0, 0.0, 0.0
    trs, plus_dm, minus_dm = [], [], []
    for i in range(1, len(rows)):
        h, l = float(rows[i]["high"]), float(rows[i]["low"])
        ph, pl, pc = float(rows[i-1]["high"]), float(rows[i-1]["low"]), float(rows[i-1]["close"])
        up, down = h-ph, pl-l
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    atr = _wilder_series(trs, period)
    pdm = _wilder_series(plus_dm, period); mdm = _wilder_series(minus_dm, period)
    dx = []
    pdis = []; mdis = []
    for a,p,m in zip(atr,pdm,mdm):
        pdi = 100.0*p/a if a > 0 else 0.0; mdi = 100.0*m/a if a > 0 else 0.0
        pdis.append(pdi); mdis.append(mdi)
        dx.append(100.0*abs(pdi-mdi)/(pdi+mdi) if pdi+mdi > 0 else 0.0)
    adx = _wilder_series(dx, period)
    return (adx[-1] if adx else 0.0, pdis[-1] if pdis else 0.0, mdis[-1] if mdis else 0.0)


def _closed(rows: List[dict], seconds: int):
    now = time.time(); out = list(rows)
    while out:
        t = _ts(out[-1].get("time"))
        if t <= 0 or t + seconds <= now - 2: break
        out.pop()
    return out


def _trend(rows15: List[dict], direction: str):
    closes = [float(x["close"]) for x in rows15]
    e20 = _ema_series(closes,20); e50 = _ema_series(closes,50)
    adx,pdi,mdi = _adx_di(rows15,14)
    if len(e20) < 4: return False, {}
    c = closes[-1]
    if direction == "LONG":
        ok = c > e20[-1] > e50[-1] and e20[-1] > e20[-4] and adx >= 22 and pdi > mdi
    else:
        ok = c < e20[-1] < e50[-1] and e20[-1] < e20[-4] and adx >= 22 and mdi > pdi
    return ok, {"close":c,"ema20":e20[-1],"ema50":e50[-1],"ema20_3ago":e20[-4],"adx":adx,"plus_di":pdi,"minus_di":mdi}


def _confirmed_pivots(rows15: List[dict]):
    highs=[]; lows=[]
    for i in range(2, len(rows15)-2):
        h=float(rows15[i]["high"]); l=float(rows15[i]["low"])
        if h > max(float(rows15[j]["high"]) for j in (i-2,i-1,i+1,i+2)): highs.append(h)
        if l < min(float(rows15[j]["low"]) for j in (i-2,i-1,i+1,i+2)): lows.append(l)
    return highs,lows


@dataclass
class Signal:
    symbol: str; direction: str; setup_id: str; trigger_time: float; breakout_time: float
    reference_entry: float; entry: float; valid_low: float; valid_high: float
    sl: float; t1: float; t2: float; d: float; cost: float; net_risk: float
    atr: float; breakout_level: float; warmup: bool; fee_rate: float; spread: float
    paper_qty: float; risk_budget: float; reason: str


@dataclass
class PaperTrade:
    signal: Signal; created: float; deadline: float; t1_hit: bool=False; be_sl: Optional[float]=None


class TrendBreakoutRetestV1:
    def __init__(self):
        self.running=True; self.alert_cb=None; self.last_signal:Optional[Signal]=None
        self.last_scan_at=0.0; self.last_status:Dict[str,dict]={}; self.scan_errors=0
        self.emitted:Dict[str,float]={}; self.state_seen:Dict[str,float]={}; self.active:Dict[str,PaperTrade]={}
        self.product_cache:Dict[str,dict]={}; self.product_cache_at:Dict[str,float]={}
        self.paper_equity=float(os.getenv("TBR_PAPER_EQUITY_USD","10000") or 10000)
        self.scan_seconds=max(15,int(os.getenv("TBR_SCAN_SECONDS",str(settings.DELTA_SIGNAL_SCAN_SECONDS)) or 30))

    def set_alert_callback(self, cb): self.alert_cb=cb
    async def _alert(self,text):
        if self.alert_cb: await self.alert_cb(text)

    async def _product(self,symbol):
        if symbol in self.product_cache and time.time()-self.product_cache_at.get(symbol,0)<3600: return self.product_cache[symbol]
        r=await delta_market_service.client.get(f"{settings.DELTA_REST_BASE}/v2/products/{symbol}")
        if r.status_code!=200: raise RuntimeError(f"product HTTP {r.status_code}")
        row=(r.json() or {}).get("result") or {}
        if not isinstance(row,dict): raise RuntimeError("product metadata unavailable")
        self.product_cache[symbol]=row; self.product_cache_at[symbol]=time.time(); return row

    async def _quote(self,symbol):
        r=await delta_market_service.client.get(f"{settings.DELTA_REST_BASE}/v2/tickers/{symbol}")
        if r.status_code!=200: raise RuntimeError(f"ticker HTTP {r.status_code}")
        row=(r.json() or {}).get("result") or {}; q=row.get("quotes") or {}
        bid=_f(q.get("best_bid"),0); ask=_f(q.get("best_ask"),0); stamp=_ts(row.get("timestamp"))
        if bid<=0 or ask<=bid:
            rr=await delta_market_service.client.get(f"{settings.DELTA_REST_BASE}/v2/l2orderbook/{symbol}",params={"depth":1})
            if rr.status_code!=200: raise RuntimeError("invalid bid/ask")
            ob=(rr.json() or {}).get("result") or {}; buys=ob.get("buy") or []; sells=ob.get("sell") or []
            bid=_f((buys[0] if buys else {}).get("price"),0); ask=_f((sells[0] if sells else {}).get("price"),0); stamp=_ts(ob.get("last_updated_at"))
        if bid<=0 or ask<=bid: raise RuntimeError("invalid bid/ask")
        if stamp and time.time()-stamp>QUOTE_STALE_SECONDS: raise RuntimeError(f"stale quote {time.time()-stamp:.1f}s")
        return {"bid":bid,"ask":ask,"spread":ask-bid,"ticker":row,"timestamp":stamp}

    def _candle_fresh(self,rows,seconds):
        if not rows:return False
        t=_ts(rows[-1].get("time")); return (not t) or time.time()-(t+seconds)<=CANDLE_GRACE_SECONDS

    async def _cost(self,symbol,direction,entry,quote,product):
        fee=_f(product.get("taker_commission_rate"),-1)
        if fee<0: return None
        # Price-equivalent conservative RT cost: taker both sides + one full current spread.
        fee_cost=2.0*fee*entry; slip_cost=float(quote["spread"])
        funding_cost=0.0
        row=quote.get("ticker") or {}; fr=row.get("funding_rate"); nxt=row.get("next_funding_realization") or row.get("next_funding_time")
        if fr is not None and nxt is not None:
            n=_ts(nxt); within=0 < n-time.time() <= MAX_HOLD_5M_BARS*300
            rate=_f(fr,0.0)/100.0
            adverse=(direction=="LONG" and rate>0) or (direction=="SHORT" and rate<0)
            if within and adverse: funding_cost=entry*abs(rate)
        return {"total":fee_cost+slip_cost+funding_cost,"fee":fee_cost,"slippage":slip_cost,"funding":funding_cost,"fee_rate":fee}

    def _paper_qty(self,product,entry,net_risk):
        risk_budget=self.paper_equity*PAPER_RISK_PCT
        cv=max(_f(product.get("contract_value"),1.0),1e-12)
        unit=str(product.get("contract_unit_currency") or "").upper(); notional=str(product.get("notional_type") or "").lower()
        risk_per_contract=net_risk*cv if unit not in {"USD","USDT","USDC"} else (net_risk/max(entry,1e-12))*cv
        if risk_per_contract<=0:return 0.0,risk_budget
        raw=risk_budget/risk_per_contract
        step=max(_f(product.get("size_increment"),1.0),1e-12); minimum=max(_f(product.get("minimum_order_size") or product.get("min_order_size"),step),step)
        qty=math.floor(raw/step)*step
        half=qty/2.0
        if qty<minimum or half<minimum or abs((half/step)-round(half/step))>1e-7:return 0.0,risk_budget
        return qty,risk_budget

    def _breakout(self,rows5,i,direction,atr_series):
        if i<BREAKOUT_LOOKBACK:return None
        b=rows5[i]; prev=rows5[i-BREAKOUT_LOOKBACK:i]; atr=max(atr_series[i],1e-12)
        vols=[float(x.get("volume") or 0) for x in rows5[max(0,i-20):i]]
        if not vols:return None
        avg=sum(vols)/len(vols); rng=float(b["high"])-float(b["low"]); vol=float(b.get("volume") or 0)
        if direction=="LONG":
            level=max(float(x["high"]) for x in prev)
            ok=float(b["close"])>level+0.10*atr and float(b["close"])>float(b["open"])
        else:
            level=min(float(x["low"]) for x in prev)
            ok=float(b["close"])<level-0.10*atr and float(b["close"])<float(b["open"])
        ok=ok and vol>=1.20*avg and rng<=2.0*atr
        return {"level":level,"atr":atr,"vol_avg":avg,"vol":vol} if ok else None

    def _trigger(self,rows5,bidx,direction,setup):
        closes=[float(x["close"]) for x in rows5]; e9=_ema_series(closes,9); e20=_ema_series(closes,20)
        level=setup["level"]; atr=setup["atr"]
        upto=min(len(rows5)-1,bidx+RETEST_BARS)
        for j in range(bidx+1,upto+1):
            c=rows5[j]
            if direction=="LONG":
                if float(c["close"])<level-0.30*atr:return "CANCELLED",None,j
                ok=(float(c["low"])<=level+0.20*atr and float(c["low"])>=level-0.30*atr and float(c["close"])>level and float(c["close"])>float(c["open"]) and float(c["close"])>e9[j] and e9[j]>e20[j])
            else:
                if float(c["close"])>level+0.30*atr:return "CANCELLED",None,j
                ok=(float(c["high"])>=level-0.20*atr and float(c["high"])<=level+0.30*atr and float(c["close"])<level and float(c["close"])<float(c["open"]) and float(c["close"])<e9[j] and e9[j]<e20[j])
            if ok:return "TRIGGER",j,j
        if len(rows5)-1>=bidx+RETEST_BARS:return "EXPIRED",None,upto
        return "WAIT",None,upto

    async def analyze(self,symbol):
        raw15=await delta_market_service.get_candles(symbol,"15m",FETCH_CANDLES); raw5=await delta_market_service.get_candles(symbol,"5m",FETCH_CANDLES)
        r15=_closed(raw15,900); r5=_closed(raw5,300)
        if len(r15)<MIN_CANDLES or len(r5)<MIN_CANDLES: return None,"NO_SIGNAL",f"need {MIN_CANDLES} closed candles"
        if not self._candle_fresh(r15,900) or not self._candle_fresh(r5,300): return None,"NO_SIGNAL","stale candle feed"
        warmup=len(r15)<50 or len(r5)<21
        atrs=_atr_series(r5,14); quote=await self._quote(symbol); product=await self._product(symbol)
        daily_hit,eqpct=tbr_stats.daily_loss_limit_hit()
        if daily_hit:return None,"RISK_BLOCK",f"daily paper loss {eqpct:.2f}% <= -1%"
        if symbol in self.active:return None,"ACTIVE","one active paper trade on symbol"
        if len(self.active)*PAPER_RISK_PCT>=MAX_TOTAL_RISK_PCT:return None,"RISK_BLOCK","total simultaneous paper risk >=0.50%"

        for direction in ("LONG","SHORT"):
            trend_ok,trend_meta=_trend(r15,direction)
            if not trend_ok:continue
            # Only breakouts recent enough to still have a valid 3-bar retest window.
            start=max(BREAKOUT_LOOKBACK,len(r5)-4)
            for bidx in range(len(r5)-2,start-1,-1):
                setup=self._breakout(r5,bidx,direction,atrs)
                if not setup:continue
                btime=_ts(r5[bidx].get("time")); sid=f"{symbol}:{STRATEGY}:{direction}:{int(btime)}"
                state,tidx,_=self._trigger(r5,bidx,direction,setup)
                if state in {"CANCELLED","EXPIRED"}:
                    sk=f"{sid}:{state}"
                    if sk not in self.state_seen:
                        self.state_seen[sk]=time.time();tbr_stats.record_state(state.lower())
                    continue
                if state!="TRIGGER" or tidx is None:continue
                # Signal is valid only during the single 5m candle immediately after T close.
                tstart=_ts(r5[tidx].get("time")); tclose=tstart+300
                if time.time()>tclose+300:continue
                if tidx!=len(r5)-1:continue
                trend_now,_=_trend(r15,direction)
                if not trend_now:continue
                ref=float(r5[tidx]["close"]); atr=setup["atr"]
                entry=quote["ask"] if direction=="LONG" else quote["bid"]
                if direction=="LONG":
                    if entry>ref+0.15*atr:continue
                    sl=min(float(x["low"]) for x in r5[bidx+1:tidx+1])-0.15*atr; d=entry-sl
                    vlo,vhi=ref-999*atr,ref+0.15*atr
                else:
                    if entry<ref-0.15*atr:continue
                    sl=max(float(x["high"]) for x in r5[bidx+1:tidx+1])+0.15*atr; d=sl-entry
                    vlo,vhi=ref-0.15*atr,ref+999*atr
                if d<0.50*atr or d>1.80*atr:continue
                cost=await self._cost(symbol,direction,entry,quote,product)
                if not cost:continue
                c=cost["total"]
                if c>0.20*d:continue
                net_risk=d+c
                t1=entry+(1.85*net_risk+c) if direction=="LONG" else entry-(1.85*net_risk+c)
                t2=entry+(2.30*net_risk+c) if direction=="LONG" else entry-(2.30*net_risk+c)
                ph,pl=_confirmed_pivots(r15[-100:])
                if direction=="LONG" and any(entry<p<=t1 for p in ph):continue
                if direction=="SHORT" and any(t1<=p<entry for p in pl):continue
                qty,risk_budget=self._paper_qty(product,entry,net_risk)
                if qty<=0:continue
                if sid in self.emitted and time.time()-self.emitted[sid]<DUPLICATE_SECONDS:continue
                reason=(f"15M trend pass ADX {trend_meta.get('adx',0):.1f}; 5M breakout+retest; "
                        f"vol {setup['vol']/max(setup['vol_avg'],1e-12):.2f}x; cost {c/d*100:.1f}% of D")
                sig=Signal(symbol,direction,sid,tstart,btime,ref,entry,vlo,vhi,sl,t1,t2,d,c,net_risk,atr,setup["level"],warmup,cost["fee_rate"],quote["spread"],qty,risk_budget,reason)
                return sig,"VALID","valid setup"
        return None,"NO_SIGNAL","no completed breakout-retest setup"

    def format_signal(self,s:Signal):
        exp=datetime.fromtimestamp(s.trigger_time+600,timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        trig=datetime.fromtimestamp(s.trigger_time+300,timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        vr=(f"<= {s.valid_high:,.2f}" if s.direction=="LONG" else f">= {s.valid_low:,.2f}")
        warm="WARMUP_18" if s.warmup else "FULL_HISTORY"
        return (f"🚀 *{STRATEGY}*\n\nSYMBOL: *{s.symbol}*\nDIRECTION: *{s.direction}*\nSETUP ID: `{s.setup_id}`\n"
                f"TRIGGER TIME UTC: `{trig}`\nREFERENCE ENTRY: `{s.reference_entry:,.2f}`\nVALID ENTRY RANGE: `{vr}`\n"
                f"CANDIDATE ENTRY: `{s.entry:,.2f}`\nSL: `{s.sl:,.2f}`\nT1: `{s.t1:,.2f}`\nT2: `{s.t2:,.2f}`\n"
                f"ESTIMATED NET RR: `1:1.85 / 1:2.30`\nESTIMATED COST: `{s.cost:.4f}` price-units\n"
                f"EXPIRY TIME: `{exp}`\nSTATUS: *VALID*\nREASON: {s.reason}\n"
                f"History mode: *{warm}* | Paper qty: `{s.paper_qty:g}` | Risk budget: `${s.risk_budget:.2f}`\n\n"
                "🧪 Paper tracking: T1 50% → cost-BE → T2; 6×5m time exit.\n📡 *SIGNAL ONLY — NO ORDER EXECUTED*")

    async def _resolve_trade(self,symbol,outcome,exit_px):
        tr=self.active.pop(symbol,None)
        if not tr:return
        s=tr.signal
        if s.direction=="LONG":
            if tr.t1_hit:gross=0.5*(s.t1-s.entry)+0.5*(exit_px-s.entry)
            else:gross=exit_px-s.entry
        else:
            if tr.t1_hit:gross=0.5*(s.entry-s.t1)+0.5*(s.entry-exit_px)
            else:gross=s.entry-exit_px
        net=gross-s.cost; net_r=net/max(s.net_risk,1e-12); gross_r=gross/max(s.net_risk,1e-12); cost_r=s.cost/max(s.net_risk,1e-12)
        tbr_stats.resolve(symbol,s.direction,outcome,net_r,gross_r,cost_r)
        await self._alert(f"🏁 *TBR V1 PAPER {outcome}* — {symbol} {s.direction}\nExit `{exit_px:,.2f}` | Net `{net_r:+.2f}R` | T1 {'YES' if tr.t1_hit else 'NO'}")

    async def _monitor(self):
        for symbol,tr in list(self.active.items()):
            try:
                q=await self._quote(symbol);s=tr.signal;px=q["bid"] if s.direction=="LONG" else q["ask"]
                if not tr.t1_hit:
                    slhit=px<=s.sl if s.direction=="LONG" else px>=s.sl
                    t1hit=px>=s.t1 if s.direction=="LONG" else px<=s.t1
                    if slhit:
                        await self._resolve_trade(symbol,"SL",px);continue
                    if t1hit:
                        tr.t1_hit=True;tr.be_sl=s.entry+s.cost if s.direction=="LONG" else s.entry-s.cost
                        tbr_stats.mark_t1(symbol,s.direction)
                        await self._alert(f"✅ *TBR V1 T1 HIT* — {symbol} {s.direction}\n50% paper exit at `{s.t1:,.2f}` | remaining SL → cost-BE `{tr.be_sl:,.2f}`")
                else:
                    t2hit=px>=s.t2 if s.direction=="LONG" else px<=s.t2
                    behit=px<=tr.be_sl if s.direction=="LONG" else px>=tr.be_sl
                    if t2hit:
                        tbr_stats.mark_t2();await self._resolve_trade(symbol,"T2",s.t2);continue
                    if behit:
                        await self._resolve_trade(symbol,"BE",px);continue
                if time.time()>=tr.deadline:
                    await self._resolve_trade(symbol,"TIME",px)
            except Exception as exc:logger.warning("[TBR_MONITOR] %s: %s",symbol,exc)

    async def scan_once(self):
        self.last_scan_at=time.time()
        for symbol in SYMBOLS:
            try:
                sig,status,reason=await self.analyze(symbol);self.last_status[symbol]={"status":status,"reason":reason,"time":time.time()}
                if sig:
                    self.emitted[sig.setup_id]=time.time();self.last_signal=sig;tbr_stats.new_signal(symbol,sig.direction)
                    self.active[symbol]=PaperTrade(sig,time.time(),sig.trigger_time+300+MAX_HOLD_5M_BARS*300)
                    await self._alert(self.format_signal(sig))
            except Exception as exc:
                self.scan_errors+=1;self.last_status[symbol]={"status":"ERROR","reason":str(exc)[:160],"time":time.time()};logger.warning("[TBR] %s scan error: %s",symbol,exc)
        await self._monitor()
        cutoff=time.time()-86400
        self.emitted={k:v for k,v in self.emitted.items() if v>cutoff};self.state_seen={k:v for k,v in self.state_seen.items() if v>cutoff}

    async def loop(self):
        while True:
            try:
                if self.running:await self.scan_once()
            except asyncio.CancelledError:raise
            except Exception as exc:self.scan_errors+=1;logger.exception("[TBR] loop error: %s",exc)
            await asyncio.sleep(self.scan_seconds)


tbr_engine=TrendBreakoutRetestV1()
