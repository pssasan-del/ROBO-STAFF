"""MASTER MIND BTC 5m scalp signal engine.

Completely separate from ROBO STAFF / FRESH_V3 policy, cooldowns, research and
performance tracking. Public Delta data only. SIGNAL ONLY: this module contains
no order placement, modification, cancellation or broker credential logic.

Indicator vocabulary intentionally limited to the user-locked stack:
- EMA 9 / EMA 95
- McGinley Dynamic 14
- Fibonacci pivots P/S1/S2/S3/R1/R2/R3
- Momentum(10, close)
- Volume / Volume SMA20
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


MASTER_MIND_VERSION = "MASTER_MIND_BTC_5M_V1_2026-09-28"
MASTER_MIND_SYMBOL = "BTCUSD"
MASTER_MIND_COOLDOWN_SECONDS = 10 * 60  # independent; does not touch old cooldowns


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _ts_seconds(v):
    x = _f(v, 0.0)
    return x / 1000.0 if x > 100_000_000_000 else x


def _closed_rows(rows, seconds):
    now = time.time()
    out = list(rows or [])
    while out:
        ts = _ts_seconds(out[-1].get("time"))
        if ts <= 0 or ts + seconds <= now - 2:
            break
        out.pop()
    return out


def _ema(values, period):
    return float(ema([float(x) for x in values], period))


def _mcginley_series(closes, period=14, k=0.6):
    """Standard bounded McGinley Dynamic recursion."""
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
            denom = max(k * period * (ratio ** 4), 1e-9)
            md = md + (px - md) / denom
        out.append(md)
    return out


def _momentum(closes, period=10):
    vals = [float(x) for x in closes]
    if len(vals) <= period:
        return 0.0
    return vals[-1] - vals[-1 - period]


def _pivot_map(piv):
    return {
        "P": _f(piv.get("pivot")),
        "R1": _f(piv.get("fib_r1") or piv.get("r1")),
        "R2": _f(piv.get("fib_r2") or piv.get("r2")),
        "R3": _f(piv.get("fib_r3") or piv.get("r3")),
        "S1": _f(piv.get("fib_s1") or piv.get("s1")),
        "S2": _f(piv.get("fib_s2") or piv.get("s2")),
        "S3": _f(piv.get("fib_s3") or piv.get("s3")),
    }


def _nearest_level(price, levels):
    valid = [(name, value) for name, value in levels.items() if value > 0]
    return min(valid, key=lambda x: abs(x[1] - price)) if valid else ("N/A", 0.0)


def _crossed_level(prev_close, close, levels, upward=True):
    valid = []
    for name, value in levels.items():
        if value <= 0:
            continue
        if upward and prev_close <= value < close:
            valid.append((name, value))
        if not upward and prev_close >= value > close:
            valid.append((name, value))
    if not valid:
        return None
    # For an upward move return the highest crossed level; downward returns lowest.
    return max(valid, key=lambda x: x[1]) if upward else min(valid, key=lambda x: x[1])


def _next_pivot(price, levels, upward=True, skip=None):
    items = [(n, v) for n, v in levels.items() if v > 0 and n != skip]
    if upward:
        higher = sorted((n, v) for n, v in items if v > price)
        return higher[0] if higher else ("EXT", price * 1.004)
    lower = sorted(((n, v) for n, v in items if v < price), key=lambda x: x[1], reverse=True)
    return lower[0] if lower else ("EXT", price * 0.996)


def _wick_rejection(row, bullish):
    o, h, l, c = (_f(row.get(k)) for k in ("open", "high", "low", "close"))
    body = max(abs(c - o), max(c, 1.0) * 0.00015)
    lower = min(o, c) - l
    upper = h - max(o, c)
    if bullish:
        return lower >= 1.2 * body and c >= o
    return upper >= 1.2 * body and c <= o


def _near(price, level, pct=0.0020):
    return level > 0 and abs(price - level) / max(price, 1e-9) <= pct


def _fmt_price(v):
    return f"{v:,.1f}" if abs(v) >= 1000 else f"{v:.4f}"


class MasterMindScalpEngine:
    def __init__(self):
        self.running = True
        self.alert_cb = None
        self.last_alert_at = 0.0
        self.last_alert_key = ""
        self.last_scan_at = 0.0
        self.last_status = "INIT"
        self.last_reason = ""

    def set_alert_callback(self, cb):
        self.alert_cb = cb

    async def _alert(self, text):
        if self.alert_cb:
            await self.alert_cb(text)

    async def _best_strike(self, direction, action, spot, pivots):
        """Public option-chain suggestion only; never executes anything."""
        try:
            rows = await delta_options_service.get_chain("BTC")
            parsed = [delta_options_service._snapshot(r) for r in rows]
            parsed = [x for x in parsed if x.get("strike") and x.get("expiry")]
            if not parsed:
                return "N/A", "no live option chain"
            expiries = sorted({str(x["expiry"]) for x in parsed})
            today = datetime.now(timezone.utc).date()
            expiry = next((e for e in expiries if datetime.fromisoformat(e).date() >= today), expiries[0])
            pool = [x for x in parsed if str(x.get("expiry")) == expiry]
            strikes = sorted({float(x["strike"]) for x in pool})
            if not strikes:
                return "N/A", expiry

            if "SELL OTM PUT" in action:
                supports = [v for n, v in pivots.items() if n in {"P", "S1", "S2", "S3"} and 0 < v < spot]
                anchor = max(supports) if supports else spot * 0.995
                eligible = [s for s in strikes if s <= anchor and s < spot]
                strike = max(eligible) if eligible else min(strikes, key=lambda s: abs(s - spot))
                return f"P-{int(strike)}", f"below { _fmt_price(anchor) } support | {expiry}"

            if "SELL OTM CALL" in action:
                resist = [v for n, v in pivots.items() if n in {"P", "R1", "R2", "R3"} and v > spot]
                anchor = min(resist) if resist else spot * 1.005
                eligible = [s for s in strikes if s >= anchor and s > spot]
                strike = min(eligible) if eligible else min(strikes, key=lambda s: abs(s - spot))
                return f"C-{int(strike)}", f"above { _fmt_price(anchor) } resistance | {expiry}"

            atm = min(strikes, key=lambda s: abs(s - spot))
            side = "C" if direction == "BULLISH" else "P"
            return f"{side}-{int(atm)}", f"ATM | {expiry}"
        except Exception as exc:
            logger.debug("[MASTER_MIND] option strike lookup failed: %s", exc)
            return "N/A", "option-chain unavailable"

    async def evaluate(self):
        raw5 = await delta_market_service.get_candles(MASTER_MIND_SYMBOL, "5m", 180)
        rawd = await delta_market_service.get_candles(MASTER_MIND_SYMBOL, "1d", 42)
        rows = _closed_rows(raw5, 300)
        days = _closed_rows(rawd, 86400)
        if len(rows) < 110 or len(days) < 2:
            return None, "insufficient completed candles"

        closes = [_f(x.get("close")) for x in rows]
        current, prev = rows[-1], rows[-2]
        close, prev_close = closes[-1], closes[-2]
        open_, high, low = (_f(current.get(k)) for k in ("open", "high", "low"))
        ema9 = _ema(closes, 9)
        ema95 = _ema(closes, 95)
        mc_series = _mcginley_series(closes, 14)
        mcg = mc_series[-1]
        prev_mcg = mc_series[-2]
        mom = _momentum(closes, 10)
        prev_mom = _momentum(closes[:-1], 10)
        volumes = [_f(x.get("volume")) for x in rows]
        vol = volumes[-1]
        vol_sma20 = sum(volumes[-21:-1]) / 20.0 if len(volumes) >= 21 else max(vol, 1.0)
        vol_ratio = vol / max(vol_sma20, 1e-9)
        green = close > open_
        red = close < open_

        # Previous completed daily candle drives the full-session Fibonacci pivots.
        piv = _pivot_map(fibonacci_pivots(days[-1]))
        nearest_name, nearest_value = _nearest_level(close, piv)
        up_break = _crossed_level(prev_close, close, piv, True)
        down_break = _crossed_level(prev_close, close, piv, False)

        trend_long = close > ema95 and close > ema9 > mcg
        trend_short = close < ema95 and close < ema9 < mcg
        mom_rising = mom > 0 and mom > prev_mom
        mom_falling = mom < 0 and mom < prev_mom
        volume_breakout = vol_ratio >= 1.15

        setup = None
        direction = None
        action = None
        reason = []
        trigger = ""
        sl = 0.0
        tp1 = 0.0
        tp2 = 0.0
        confidence = 0

        # 1) Strong trend breakout.
        if trend_long and up_break and green and volume_breakout and mom_rising:
            setup = "Breakout"; direction = "BULLISH"
            action = "FUTURE LONG + SELL OTM PUT"
            level_name, level = up_break
            next_name, next_level = _next_pivot(close, piv, True, level_name)
            trigger = f"5m close > {level_name} {_fmt_price(level)} with green volume"
            sl = level * 0.999
            tp1, tp2 = next_level, _next_pivot(next_level + 1e-9, piv, True, next_name)[1]
            reason = ["Price>EMA95", "Price>EMA9>McGinley14", f"{level_name} breakout", f"Volume {vol_ratio:.2f}x", f"Mom {mom:.0f} rising"]
            confidence = 9 if vol_ratio >= 1.5 else 8

        elif trend_short and down_break and red and volume_breakout and mom_falling:
            setup = "Breakout"; direction = "BEARISH"
            action = "FUTURE SHORT + SELL OTM CALL"
            level_name, level = down_break
            next_name, next_level = _next_pivot(close, piv, False, level_name)
            trigger = f"5m close < {level_name} {_fmt_price(level)} with red volume"
            sl = level * 1.001
            tp1, tp2 = next_level, _next_pivot(next_level - 1e-9, piv, False, next_name)[1]
            reason = ["Price<EMA95", "Price<EMA9<McGinley14", f"{level_name} breakdown", f"Volume {vol_ratio:.2f}x", f"Mom {mom:.0f} falling"]
            confidence = 9 if vol_ratio >= 1.5 else 8

        # 2) Trend pullback to EMA9 / McGinley / Fib pivot with rejection.
        if setup is None:
            long_refs = [("EMA9", ema9), ("McGinley14", mcg)] + list(piv.items())
            short_refs = long_refs
            long_touches = [(n, v) for n, v in long_refs if v > 0 and low <= v * 1.0015 and close >= v]
            short_touches = [(n, v) for n, v in short_refs if v > 0 and high >= v * 0.9985 and close <= v]
            long_ref = min(long_touches, key=lambda x: abs(close - x[1])) if long_touches else None
            short_ref = min(short_touches, key=lambda x: abs(close - x[1])) if short_touches else None
            if trend_long and long_ref and _wick_rejection(current, True) and mom > prev_mom:
                setup = "Pullback"; direction = "BULLISH"; action = "FUTURE LONG + SELL OTM PUT"
                ref_name, ref = long_ref
                trigger = f"Bullish rejection from {ref_name} {_fmt_price(ref)}; Momentum curls up"
                sl = min(ref, mcg) * 0.999
                tp1_name, tp1 = _next_pivot(close, piv, True)
                tp2 = _next_pivot(tp1 + 1e-9, piv, True, tp1_name)[1]
                reason = ["95 EMA uptrend", f"{ref_name} pullback", "bullish rejection wick", f"Mom {prev_mom:.0f}->{mom:.0f}"]
                confidence = 8 if vol_ratio >= 1.0 else 7
            elif trend_short and short_ref and _wick_rejection(current, False) and mom < prev_mom:
                setup = "Pullback"; direction = "BEARISH"; action = "FUTURE SHORT + SELL OTM CALL"
                ref_name, ref = short_ref
                trigger = f"Bearish rejection from {ref_name} {_fmt_price(ref)}; Momentum curls down"
                sl = max(ref, mcg) * 1.001
                tp1_name, tp1 = _next_pivot(close, piv, False)
                tp2 = _next_pivot(tp1 - 1e-9, piv, False, tp1_name)[1]
                reason = ["95 EMA downtrend", f"{ref_name} pullback", "bearish rejection wick", f"Mom {prev_mom:.0f}->{mom:.0f}"]
                confidence = 8 if vol_ratio >= 1.0 else 7

        # 3) Exhaustion reversal: extreme momentum hooks toward zero at a pivot.
        if setup is None:
            near_pivot = _near(close, nearest_value, 0.0025)
            vol_spike = vol_ratio >= 1.20
            if prev_mom > 200 and mom < prev_mom and near_pivot and _wick_rejection(current, False) and vol_spike:
                setup = "Exhaustion Reversal"; direction = "BEARISH"; action = "SELL OTM CALL"
                trigger = f"Momentum hook {prev_mom:.0f}->{mom:.0f} near {nearest_name} {_fmt_price(nearest_value)}"
                sl = high * 1.001
                tp1 = max(x for x in (ema9, mcg) if x < close) if any(x < close for x in (ema9, mcg)) else min(ema9, mcg)
                tp2 = _next_pivot(tp1 - 1e-9, piv, False)[1]
                reason = ["Momentum >+200 exhaustion", f"{nearest_name} rejection wick", f"Volume spike {vol_ratio:.2f}x", "hook toward zero"]
                confidence = 9 if vol_ratio >= 1.5 else 8
            elif prev_mom < -150 and mom > prev_mom and near_pivot and _wick_rejection(current, True) and vol_spike:
                setup = "Exhaustion Reversal"; direction = "BULLISH"; action = "SELL OTM PUT"
                trigger = f"Momentum hook {prev_mom:.0f}->{mom:.0f} near {nearest_name} {_fmt_price(nearest_value)}"
                sl = low * 0.999
                tp1 = min(x for x in (ema9, mcg) if x > close) if any(x > close for x in (ema9, mcg)) else max(ema9, mcg)
                tp2 = _next_pivot(tp1 + 1e-9, piv, True)[1]
                reason = ["Momentum <-150 exhaustion", f"{nearest_name} rejection wick", f"Volume spike {vol_ratio:.2f}x", "hook toward zero"]
                confidence = 9 if vol_ratio >= 1.5 else 8

        if setup is None:
            between = min(ema9, ema95) <= close <= max(ema9, ema95)
            flat = vol_ratio < 0.90 and abs(mom) < 50
            return None, "NO_TRADE_CHOP" if between and flat else "WAIT_CONFLUENCE"

        strike, strike_note = await self._best_strike(direction, action, close, piv)
        bias = "Bullish" if direction == "BULLISH" else "Bearish"
        key = f"{setup}:{direction}:{current.get('time')}:{strike}"
        alert = (
            "🔴🚨 MASTER MIND SIGNAL ALERT 🚨🔴\n"
            f"Version: {MASTER_MIND_VERSION}\n"
            f"BTCUSD 5m | Close: `{_fmt_price(close)}`\n\n"
            f"1. Market Bias: **{bias}**\n"
            f"2. Active Setup: **{setup}**\n"
            f"3. Signal Action: **{action}**\n"
            f"4. Best Strike Selection: **{strike}** ({strike_note})\n"
            f"5. Entry Trigger: {trigger}\n"
            f"6. Stop Loss (Invalidation): `{_fmt_price(sl)}` | 5m close through invalidation / McGinley condition\n"
            f"7. Scalp Targets: TP1 `{_fmt_price(tp1)}` | TP2 `{_fmt_price(tp2)}`\n"
            f"8. Confidence Score: **{confidence}/10**\n\n"
            f"EMA9 `{_fmt_price(ema9)}` | EMA95 `{_fmt_price(ema95)}` | McGinley14 `{_fmt_price(mcg)}`\n"
            f"Momentum10 `{mom:.1f}` (prev `{prev_mom:.1f}`) | Volume `{vol_ratio:.2f}x` SMA20\n"
            f"P `{_fmt_price(piv['P'])}` | S1 `{_fmt_price(piv['S1'])}` | R1 `{_fmt_price(piv['R1'])}`\n"
            f"Why: {' | '.join(reason)}\n\n"
            "📡 SIGNAL ONLY — NO ORDER EXECUTED"
        )
        return {"key": key, "alert": alert, "setup": setup, "direction": direction, "action": action}, "SIGNAL"

    async def scan_once(self):
        self.last_scan_at = time.time()
        signal, status = await self.evaluate()
        self.last_status = status
        if not signal:
            self.last_reason = status
            return {"status": status}
        now = time.time()
        if signal["key"] == self.last_alert_key:
            return {"status": "DUPLICATE_CANDLE"}
        if now - self.last_alert_at < MASTER_MIND_COOLDOWN_SECONDS:
            return {"status": "MASTER_MIND_COOLDOWN"}
        self.last_alert_key = signal["key"]
        self.last_alert_at = now
        self.last_reason = signal["setup"]
        await self._alert(signal["alert"])
        logger.info("[MASTER_MIND] %s %s %s", signal["setup"], signal["direction"], signal["action"])
        return {"status": "SIGNAL", "setup": signal["setup"], "direction": signal["direction"]}

    async def loop(self):
        while True:
            try:
                if self.running:
                    await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_status = "ERROR"
                self.last_reason = str(exc)[:160]
                logger.warning("[MASTER_MIND] scan failed safely: %s", exc)
            await asyncio.sleep(max(30, settings.DELTA_SIGNAL_SCAN_SECONDS))


master_mind_scalp_engine = MasterMindScalpEngine()
