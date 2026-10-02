"""ROBO STAFF V7 TAKER-FLOW PULLBACK overlay.

Adds the filters present in the user-supplied June research:
- high-conviction window 12:00-17:59 UTC
- HTF direction from the existing 1H + 15M engine
- 5M pullback/resume around EMA9
- pullback RSI context
- 5M RVOL >= 1.0
- public recent-trade aggressor flow confirmation
- 10-minute underlying direction tracking, separate from option T1/SL tracking

Signal-only. No private/order APIs.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from types import MethodType

from config import settings, logger
from delta_market_service import delta_market_service
from performance_store import performance_store
from strategy_engine import ema, rsi

V7_VERSION = "FRESH_V7_TAKER_FLOW_PULLBACK_2026-10-02"
WINDOW_START_UTC = 12
WINDOW_END_UTC_EXCLUSIVE = 18
SHORT_TAKER_MAX = 0.48
SHORT_TAKER_ELITE = 0.45
LONG_TAKER_MIN = 0.52
LONG_TAKER_ELITE = 0.55
MIN_RVOL = 1.00
MIN_TRADE_SAMPLES = 20


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


async def _taker_flow(symbol: str):
    """Size-weighted aggressor buy ratio from Delta public recent trades."""
    r = await delta_market_service.client.get(f"{settings.DELTA_REST_BASE}/v2/trades/{symbol}")
    if r.status_code != 200:
        raise RuntimeError(f"public trades HTTP {r.status_code}: {r.text[:160]}")
    obj = r.json()
    result = obj.get("result") if isinstance(obj, dict) else None
    trades = (result or {}).get("trades") if isinstance(result, dict) else None
    if not isinstance(trades, list):
        raise RuntimeError("public trades returned no list")

    usable = []
    buy_size = total_size = 0.0
    buy_count = 0
    for row in trades:
        side = str((row or {}).get("side") or "").lower()
        if side not in {"buy", "sell"}:
            continue
        size = max(0.0, _f((row or {}).get("size"), 0.0))
        usable.append(row)
        if side == "buy":
            buy_count += 1
            buy_size += size
        total_size += size

    if len(usable) < MIN_TRADE_SAMPLES:
        raise RuntimeError(f"recent trade sample too small: {len(usable)}")

    if total_size > 0:
        ratio = buy_size / total_size
        basis = "size-weighted"
    else:
        ratio = buy_count / max(1, len(usable))
        basis = "count-weighted"

    return {"taker_buy_ratio": ratio, "samples": len(usable), "basis": basis}


async def _pullback_state(engine, symbol: str, direction: str):
    raw = await delta_market_service.get_candles(symbol, "5m", 45)
    rows = engine._closed_rows(raw, 300)
    if len(rows) < 25:
        return False, "insufficient closed 5m candles", {}

    closes = [float(x["close"]) for x in rows]
    prev_rows = rows[:-1]
    prev_closes = closes[:-1]
    prev = prev_rows[-1]
    cur = rows[-1]
    prev_ema9 = ema(prev_closes, 9)
    cur_ema9 = ema(closes, 9)
    prev_rsi = rsi(prev_closes, 14)

    if direction == "BEARISH":
        touched = float(prev["high"]) >= prev_ema9
        rsi_ok = prev_rsi >= 50.0
        resumed = float(cur["close"]) <= cur_ema9
        ok = touched and rsi_ok and resumed
    else:
        touched = float(prev["low"]) <= prev_ema9
        rsi_ok = prev_rsi <= 50.0
        resumed = float(cur["close"]) >= cur_ema9
        ok = touched and rsi_ok and resumed

    return ok, f"EMA9 pullback touched={touched} prevRSI={prev_rsi:.1f} resumed={resumed}", {
        "pullback_prev_rsi": prev_rsi,
        "pullback_prev_ema9": prev_ema9,
        "pullback_current_ema9": cur_ema9,
    }


def install_v7_taker_flow(engine):
    original_analyze = engine.analyze_symbol
    original_alert = engine._alert
    original_scan_once = engine.scan_once

    engine.v7_direction_watch = {}
    engine.v7_taker_flow_installed = True
    engine.v7_version = V7_VERSION

    async def analyze_v7(self, symbol):
        if self._underlying(symbol) not in {"BTC", "ETH"}:
            return []

        now_utc = datetime.now(timezone.utc)
        if not (WINDOW_START_UTC <= now_utc.hour < WINDOW_END_UTC_EXCLUSIVE):
            logger.info("[V7_FLOW] %s outside 12-17 UTC high-conviction window", symbol)
            return []

        candidates = await original_analyze(symbol)
        if not candidates:
            return []

        snap = self.last_scan.get(symbol, {}) or {}
        tf = snap.get("tf") or {}
        s5 = tf.get("5m") or {}
        rvol = _f(s5.get("rel_volume"))
        if rvol < MIN_RVOL:
            logger.info("[V7_FLOW] %s rejected RVOL %.2f < %.2f", symbol, rvol, MIN_RVOL)
            return []

        direction = str(snap.get("direction") or candidates[0].direction).upper()
        ok_pullback, pullback_reason, pullback_meta = await _pullback_state(self, symbol, direction)
        if not ok_pullback:
            logger.info("[V7_FLOW] %s rejected: %s", symbol, pullback_reason)
            return []

        try:
            flow = await _taker_flow(symbol)
        except Exception as exc:
            logger.info("[V7_FLOW] %s rejected: taker flow unavailable: %s", symbol, exc)
            return []

        ratio = flow["taker_buy_ratio"]
        if direction == "BEARISH":
            flow_ok = ratio <= SHORT_TAKER_MAX
            conviction = "ELITE_FLOW" if ratio <= SHORT_TAKER_ELITE else "VALID_FLOW"
            pattern = "TAKER_PULLBACK_SHORT"
        else:
            flow_ok = ratio >= LONG_TAKER_MIN
            conviction = "ELITE_FLOW" if ratio >= LONG_TAKER_ELITE else "VALID_FLOW"
            pattern = "TAKER_PULLBACK_LONG"

        if not flow_ok:
            logger.info("[V7_FLOW] %s %s rejected taker_buy_ratio=%.3f", symbol, direction, ratio)
            return []

        snap["pattern"] = pattern
        snap["v7_taker_buy_ratio"] = ratio
        snap["v7_trade_samples"] = flow["samples"]
        snap["v7_flow_basis"] = flow["basis"]
        snap["v7_rvol"] = rvol
        snap["v7_pullback_reason"] = pullback_reason
        snap["v7_high_conviction_window"] = True
        snap.update(pullback_meta)
        passed = list(snap.get("confirmations_passed") or [])
        passed.extend([
            "12-17 UTC liquid window",
            "5M RVOL >= 1.0",
            "5M EMA9 pullback/resume",
            f"Taker flow {ratio:.3f}",
        ])
        snap["confirmations_passed"] = passed

        for c in candidates:
            c.pattern = pattern
            c.reason = f"{pattern} + RVOL {rvol:.2f} + taker-buy {ratio:.3f} ({flow['samples']} public trades)"
            c.market.update({
                "v7_taker_flow": True,
                "taker_buy_ratio": ratio,
                "taker_trade_samples": flow["samples"],
                "taker_flow_basis": flow["basis"],
                "v7_flow_conviction": conviction,
                "v7_window_utc": "12:00-17:59",
                "v7_rvol": rvol,
                **pullback_meta,
            })
        return candidates

    async def alert_v7(self, text):
        c = self.last_signal
        if isinstance(text, str) and text.startswith("⚡ *ROBO STAFF — V7") and c is not None and c.setup_id not in self.v7_direction_watch:
            try:
                sym = {"BTC": "BTCUSD", "ETH": "ETHUSD"}.get(c.underlying)
                tick = await delta_market_service.get_ticker(sym)
                self.v7_direction_watch[c.setup_id] = {
                    "created": time.time(), "underlying": c.underlying, "symbol": sym,
                    "direction": c.direction, "entry": float(tick["price"]),
                    "taker_buy_ratio": _f((c.market or {}).get("taker_buy_ratio")),
                    "rvol": _f((c.market or {}).get("v7_rvol")),
                }
            except Exception as exc:
                logger.warning("[V7_DIRECTION] watch registration failed: %s", exc)
        await original_alert(text)

    async def resolve_direction_watch(self):
        now = time.time()
        for key, item in list(self.v7_direction_watch.items()):
            if now - item["created"] < 600:
                continue
            try:
                tick = await delta_market_service.get_ticker(item["symbol"])
                end = float(tick["price"]); start = float(item["entry"])
                move_pct = (end / start - 1.0) * 100.0 if start else 0.0
                win = move_pct > 0 if item["direction"] == "BULLISH" else move_pct < 0
                performance_store.record_direction_10m(
                    item["underlying"], item["direction"], win, move_pct,
                    item.get("taker_buy_ratio", 0.0), item.get("rvol", 0.0),
                )
                logger.info("[V7_DIRECTION] %s %s 10m %s move=%+.4f%%", item["underlying"], item["direction"], "WIN" if win else "LOSS", move_pct)
                self.v7_direction_watch.pop(key, None)
            except Exception as exc:
                if now - item["created"] > 900:
                    logger.warning("[V7_DIRECTION] dropping unresolved watch %s: %s", key, exc)
                    self.v7_direction_watch.pop(key, None)

    async def scan_once_v7(self):
        result = await original_scan_once()
        await resolve_direction_watch(self)
        return result

    engine.analyze_symbol = MethodType(analyze_v7, engine)
    engine._alert = MethodType(alert_v7, engine)
    engine.scan_once = MethodType(scan_once_v7, engine)
    logger.info("[V7_FLOW] installed: 12-17 UTC + EMA9 pullback + RVOL>=1 + taker-flow confirmation + 10m direction tracking")
    return engine
