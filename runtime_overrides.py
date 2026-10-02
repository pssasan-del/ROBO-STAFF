"""Locked runtime overrides for the 2026-10-02 TBR/option-buy deployment.

Keeps existing strategy modules intact while applying the approved fast-history,
Fib verification and cheap-option rejection rules. Signal generation only.
"""
from __future__ import annotations

from types import MethodType

import polish_policy
import trend_breakout_retest_v1 as tbr
from strategy_engine import fibonacci_pivots
from delta_market_service import delta_market_service

# TBR fast-start/history policy. The 12-bar breakout rule is intentionally kept,
# so 9 bars starts analysis/warmup; a breakout cannot be fabricated before its
# required lookback exists.
tbr.MIN_CANDLES = 9
tbr.FETCH_CANDLES = 180
tbr.FULL_HISTORY_CANDLES = 180
tbr.VERSION = "TBR_V1_FAST9_180_FIB_2026-10-02"

_original_analyze = tbr.TrendBreakoutRetestV1.analyze


def _zone(px: float, piv: dict) -> str:
    try:
        p = float(piv.get("pivot") or 0)
        r1 = float(piv.get("fib_r1") or 0)
        s1 = float(piv.get("fib_s1") or 0)
    except (TypeError, ValueError):
        return "NA"
    if not p:
        return "NA"
    if r1 and px > r1:
        return "ABOVE_R1"
    if s1 and px < s1:
        return "BELOW_S1"
    return "P_TO_R1" if px >= p else "S1_TO_P"


async def _analyze_with_fib(self, symbol):
    sig, status, reason = await _original_analyze(self, symbol)
    if sig is None:
        return sig, status, reason
    try:
        r5 = tbr._closed(await delta_market_service.get_candles(symbol, "5m", 3), 300)
        r1d = tbr._closed(await delta_market_service.get_candles(symbol, "1d", 3), 86400)
        if r5:
            source5 = r5[-2] if len(r5) >= 2 else r5[-1]
            five = fibonacci_pivots(source5)
            daily = fibonacci_pivots(r1d[-1]) if r1d else {}
            px = float(r5[-1]["close"])
            sig.reason += f"; 5M Fib {_zone(px, five)}; Daily Fib {_zone(px, daily)}"
    except Exception:
        # Fib is verification/context only; never manufacture or destroy the
        # underlying breakout/retest signal because optional context failed.
        pass
    # 180 bars is the approved full-history state.
    try:
        r15 = tbr._closed(await delta_market_service.get_candles(symbol, "15m", 180), 900)
        r5h = tbr._closed(await delta_market_service.get_candles(symbol, "5m", 180), 300)
        sig.warmup = len(r15) < 180 or len(r5h) < 180
    except Exception:
        sig.warmup = True
    return sig, status, reason


tbr.TrendBreakoutRetestV1.analyze = _analyze_with_fib
tbr.tbr_engine.analyze = MethodType(_analyze_with_fib, tbr.tbr_engine)

# Stronger OPTION BUY premium floor: existing tick/spread floor plus 0.05% of
# underlying spot. Futures and non-option paths retain the original policy.
_original_contract_gate = polish_policy.contract_gate


def _contract_gate_with_premium_floor(underlying, action, *, entry, bid, ask, spot=None,
                                      delta=None, tick_size=0.01,
                                      minutes_to_expiry=None, python_score=None):
    ok, reason, meta = _original_contract_gate(
        underlying, action, entry=entry, bid=bid, ask=ask, spot=spot,
        delta=delta, tick_size=tick_size, minutes_to_expiry=minutes_to_expiry,
        python_score=python_score,
    )
    if not ok:
        return ok, reason, meta
    if str(action or "").upper() == "OPTION BUY":
        try:
            premium = float(entry)
            spot_value = float(spot or 0)
            spot_floor = 0.0005 * spot_value if spot_value > 0 else 0.0
        except (TypeError, ValueError):
            premium, spot_floor = 0.0, 0.0
        if spot_floor > 0 and premium < spot_floor:
            out = dict(meta or {})
            out["min_premium"] = max(float(out.get("min_premium") or 0), spot_floor)
            return False, f"premium<{spot_floor:.4g} floor", out
    return ok, reason, meta


polish_policy.contract_gate = _contract_gate_with_premium_floor
