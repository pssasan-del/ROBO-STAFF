"""ROBO STAFF V7.1 SCALP OPPORTUNITY taker-flow overlay.

The former V7 hard 12-17 UTC block is removed. The liquid window is now a
quality tag, not a gate, so off-window scalp opportunities can still alert.
Filters are relaxed but still require directional structure, usable activity,
and either taker-flow confirmation or a strong momentum fallback.

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

V7_VERSION = "FRESH_V7_1_SCALP_OPPORTUNITY_2026-10-02"
LIQUID_WINDOW_START_UTC = 12
LIQUID_WINDOW_END_UTC_EXCLUSIVE = 18
CORE_SHORT_TAKER_MAX = 0.49
CORE_LONG_TAKER_MIN = 0.51
OFFHOUR_SHORT_TAKER_MAX = 0.48
OFFHOUR_LONG_TAKER_MIN = 0.52
ELITE_SHORT_TAKER = 0.45
ELITE_LONG_TAKER = 0.55
MIN_RVOL_CORE = 0.60
MIN_RVOL_OFFHOUR = 0.75
MIN_TRADE_SAMPLES = 12
FLOW_FALLBACK_RVOL = 1.20
FLOW_FALLBACK_ADX = 20.0


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _in_liquid_window(now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    return LIQUID_WINDOW_START_UTC <= now_utc.hour < LIQUID_WINDOW_END_UTC_EXCLUSIVE


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

    ratio = (buy_size / total_size) if total_size > 0 else (buy_count / max(1, len(usable)))
    basis = "size-weighted" if total_size > 0 else "count-weighted"
    return {"taker_buy_ratio": ratio, "samples": len(usable), "basis": basis}


async def _pullback_state(engine, symbol: str, direction: str):
    """Allow recent EMA9 pullback/reclaim OR strong continuation so fast scalps are not missed."""
    raw = await delta_market_service.get_candles(symbol, "5m", 50)
    rows = engine._closed_rows(raw, 300)
    if len(rows) < 25:
        return False, "insufficient closed 5m candles", {}

    closes = [float(x["close"]) for x in rows]
    cur = rows[-1]
    cur_ema9 = ema(closes, 9)
    cur_rsi = rsi(closes, 14)
    lookback = rows[-4:-1]
    touched = False
    pullback_rsi = None

    for i in range(len(lookback)):
        prefix = rows[: len(rows) - 3 + i]
        if len(prefix) < 15:
            continue
        e9 = ema([float(x["close"]) for x in prefix], 9)
        rr = lookback[i]
        rr_rsi = rsi([float(x["close"]) for x in prefix], 14)
        if direction == "BEARISH" and float(rr["high"]) >= e9:
            touched = True; pullback_rsi = rr_rsi
        if direction == "BULLISH" and float(rr["low"]) <= e9:
            touched = True; pullback_rsi = rr_rsi

    if pullback_rsi is None:
        pullback_rsi = cur_rsi

    if direction == "BEARISH":
        resumed = float(cur["close"]) <= cur_ema9
        rsi_ok = pullback_rsi >= 46.0
    else:
        resumed = float(cur["close"]) >= cur_ema9
        rsi_ok = pullback_rsi <= 54.0

    snap = engine.last_scan.get(symbol, {}) or {}
    s5 = ((snap.get("tf") or {}).get("5m") or {})
    structure = str(snap.get("structure") or "")
    adx = _f(s5.get("adx")); rvol = _f(s5.get("rel_volume"))
    structure_ok = (direction == "BULLISH" and structure == "HH/HL") or (direction == "BEARISH" and structure == "LH/LL")
    continuation = resumed and structure_ok and adx >= 14 and rvol >= 0.85
    ok = resumed and ((touched and rsi_ok) or continuation)

    mode = "RECENT_EMA9_PULLBACK" if touched and rsi_ok else ("MOMENTUM_CONTINUATION" if continuation else "WAIT")
    return ok, f"{mode} touched={touched} RSI={pullback_rsi:.1f} resumed={resumed} ADX={adx:.1f} RVOL={rvol:.2f}", {
        "pullback_prev_rsi": pullback_rsi,
        "pullback_current_ema9": cur_ema9,
        "v7_setup_mode": mode,
    }


def install_v7_taker_flow(engine):
    original_analyze = engine.analyze_symbol
    original_alert = engine._alert
    original_scan_once = engine.scan_once

    engine.v7_direction_watch = {}
    engine.v7_taker_flow_installed = True
    engine.v7_1_scalp_opportunity_installed = True
    engine.v7_version = V7_VERSION

    async def analyze_v7(self, symbol):
        if self._underlying(symbol) not in {"BTC", "ETH"}:
            return []

        candidates = await original_analyze(symbol)
        if not candidates:
            return []

        snap = self.last_scan.get(symbol, {}) or {}
        tf = snap.get("tf") or {}
        s5 = tf.get("5m") or {}
        liquid_window = _in_liquid_window()
        rvol = _f(s5.get("rel_volume"))
        min_rvol = MIN_RVOL_CORE if liquid_window else MIN_RVOL_OFFHOUR
        if rvol < min_rvol:
            logger.info("[V7.1_FLOW] %s rejected RVOL %.2f < %.2f", symbol, rvol, min_rvol)
            return []

        direction = str(snap.get("direction") or candidates[0].direction).upper()
        ok_setup, setup_reason, setup_meta = await _pullback_state(self, symbol, direction)
        if not ok_setup:
            logger.info("[V7.1_FLOW] %s rejected: %s", symbol, setup_reason)
            return []

        ratio = None; samples = 0; basis = "unavailable"; flow_ok = False; flow_fallback = False
        try:
            flow = await _taker_flow(symbol)
            ratio = flow["taker_buy_ratio"]; samples = flow["samples"]; basis = flow["basis"]
            if direction == "BEARISH":
                threshold = CORE_SHORT_TAKER_MAX if liquid_window else OFFHOUR_SHORT_TAKER_MAX
                flow_ok = ratio <= threshold
            else:
                threshold = CORE_LONG_TAKER_MIN if liquid_window else OFFHOUR_LONG_TAKER_MIN
                flow_ok = ratio >= threshold
        except Exception as exc:
            logger.info("[V7.1_FLOW] %s taker flow unavailable: %s", symbol, exc)

        adx = _f(s5.get("adx"))
        if not flow_ok:
            # Strong tape fallback prevents a temporary trades-endpoint issue or near-neutral flow
            # from deleting an otherwise clean momentum scalp.
            flow_fallback = rvol >= FLOW_FALLBACK_RVOL and adx >= FLOW_FALLBACK_ADX and max(c.score for c in candidates) >= 76
            if not flow_fallback:
                logger.info("[V7.1_FLOW] %s %s rejected flow ratio=%s RVOL=%.2f ADX=%.1f", symbol, direction, ratio, rvol, adx)
                return []

        if ratio is not None:
            if direction == "BEARISH":
                conviction = "ELITE_FLOW" if ratio <= ELITE_SHORT_TAKER else ("VALID_FLOW" if flow_ok else "FLOW_FALLBACK")
                pattern = "SCALP_FLOW_SHORT"
            else:
                conviction = "ELITE_FLOW" if ratio >= ELITE_LONG_TAKER else ("VALID_FLOW" if flow_ok else "FLOW_FALLBACK")
                pattern = "SCALP_FLOW_LONG"
        else:
            conviction = "FLOW_FALLBACK"
            pattern = "SCALP_MOMENTUM_SHORT" if direction == "BEARISH" else "SCALP_MOMENTUM_LONG"

        snap["pattern"] = pattern
        snap["v7_taker_buy_ratio"] = ratio
        snap["v7_trade_samples"] = samples
        snap["v7_flow_basis"] = basis
        snap["v7_rvol"] = rvol
        snap["v7_pullback_reason"] = setup_reason
        snap["v7_high_conviction_window"] = liquid_window
        snap["v7_flow_fallback"] = flow_fallback
        snap.update(setup_meta)
        passed = list(snap.get("confirmations_passed") or [])
        passed.extend([
            "Liquid window boost" if liquid_window else "Off-window scalp allowed",
            f"5M RVOL >= {min_rvol:.2f}",
            setup_meta.get("v7_setup_mode", "5M setup"),
            (f"Taker flow {ratio:.3f}" if ratio is not None else "Strong-tape flow fallback"),
        ])
        snap["confirmations_passed"] = passed

        for c in candidates:
            c.pattern = pattern
            flow_text = f"taker-buy {ratio:.3f} ({samples} trades)" if ratio is not None else "flow fallback"
            c.reason = f"{pattern} + RVOL {rvol:.2f} + {flow_text} + {'liquid-window' if liquid_window else 'off-window'}"
            c.market.update({
                "v7_taker_flow": True,
                "v7_1_scalp_opportunity": True,
                "taker_buy_ratio": ratio,
                "taker_trade_samples": samples,
                "taker_flow_basis": basis,
                "v7_flow_conviction": conviction,
                "v7_liquid_window": liquid_window,
                "v7_window_utc": "12:00-17:59 boost; 24h alerts allowed",
                "v7_rvol": rvol,
                "v7_flow_fallback": flow_fallback,
                **setup_meta,
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
                logger.warning("[V7.1_DIRECTION] watch registration failed: %s", exc)
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
                performance_store.record_direction_10m(item["underlying"], item["direction"], win, move_pct, item.get("taker_buy_ratio", 0.0), item.get("rvol", 0.0))
                logger.info("[V7.1_DIRECTION] %s %s 10m %s move=%+.4f%%", item["underlying"], item["direction"], "WIN" if win else "LOSS", move_pct)
                self.v7_direction_watch.pop(key, None)
            except Exception as exc:
                if now - item["created"] > 900:
                    logger.warning("[V7.1_DIRECTION] dropping unresolved watch %s: %s", key, exc)
                    self.v7_direction_watch.pop(key, None)

    async def scan_once_v7(self):
        result = await original_scan_once()
        await resolve_direction_watch(self)
        return result

    engine.analyze_symbol = MethodType(analyze_v7, engine)
    engine._alert = MethodType(alert_v7, engine)
    engine.scan_once = MethodType(scan_once_v7, engine)
    logger.info("[V7.1_FLOW] installed: 24h alerts; 12-17 UTC boost; RVOL 0.60/0.75; relaxed EMA9 setup; taker flow or strong-tape fallback")
    return engine
