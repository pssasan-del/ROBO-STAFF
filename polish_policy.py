"""ROBO STAFF V7.1 SCALP OPPORTUNITY base policy.

Signal-only base policy feeding the V7.1 taker-flow overlay.
15M is the primary scalp regime; 1H is context and only vetoes when strongly opposite.
5M flow/setup is required, while 1M timing is supportive rather than a universal hard gate.
MASTER MIND stays separate and untouched.
"""
from __future__ import annotations
import math

POLISH_VERSION = "FRESH_V7_1_SCALP_OPPORTUNITY_2026-10-02"
MODE_REVISION = "15M_PRIMARY_1H_CONTEXT_5M_SCALP_2026-10-02"

MIN_ALERT_SCORE = 64
STRONG_SCORE = 76
ELITE_SCORE = 88
DAILY_RESEARCH_TARGET = 10

SPREAD_CAP_PCT = {"BTC": 3.5, "ETH": 4.2, "GOLD": 5.5}
DAILY_SIGNAL_CAP = {"BTC": 48, "ETH": 48, "GOLD": 0}
PREMIUM_SPOT_CAP = {"BTC": 0.024, "ETH": 0.028, "GOLD": 0.030}

BASE_COOLDOWN_MINUTES = 5
SUCCESS_COOLDOWN_MINUTES = 4
FAIL_COOLDOWN_MINUTES = 7
CONTRACT_COOLDOWN_MINUTES = 6
CORRELATION_WINDOW_MINUTES = 8
CORRELATION_THRESHOLD = 0.97

ACCEPTANCE_CRITERIA = {
    "min_resolved": 40,
    "preferred_resolved": 80,
    "min_calendar_days": 5,
    "min_t1_success_pct": 40.0,
    "min_profit_factor": 1.20,
    "min_expectancy_r": 0.05,
    "max_median_t1_minutes": 30.0,
    "max_p75_t1_minutes": 45.0,
    "max_fast_sl_pct": 25.0,
    "max_sl_later_t1_pct": 18.0,
    "max_stale_pct": 20.0,
    "bucket_min_n": 12,
    "bucket_min_win_pct": 38.0,
    "bucket_min_pf": 1.05,
}


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _trend(state: dict) -> str:
    return str((state or {}).get("trend") or "MIXED").upper()


def _ema_flow(direction: str, state: dict) -> bool:
    px, e5, e9, e20 = (_f(state.get(k)) for k in ("price", "ema5", "ema9", "ema20"))
    if direction == "BULLISH":
        return px >= e9 and e5 >= e9 and e9 >= e20 * 0.999
    return px <= e9 and e5 <= e9 and e9 <= e20 * 1.001


def _micro_flow(direction: str, state: dict) -> bool:
    px, e5, e9 = (_f(state.get(k)) for k in ("price", "ema5", "ema9"))
    pdi, mdi = _f(state.get("plus_di")), _f(state.get("minus_di"))
    if direction == "BULLISH":
        return px >= e9 and e5 >= e9 and pdi >= mdi * 0.95
    return px <= e9 and e5 <= e9 and mdi >= pdi * 0.95


def _di_ratio(direction: str, state: dict) -> float:
    pdi, mdi = _f(state.get("plus_di")), _f(state.get("minus_di"))
    return pdi / max(mdi, 1.0) if direction == "BULLISH" else mdi / max(pdi, 1.0)


def _structure_ok(direction: str, structure: str) -> bool:
    return (direction == "BULLISH" and structure == "HH/HL") or (direction == "BEARISH" and structure == "LH/LL")


def _pivot_ok(direction: str, zone: str) -> bool:
    return zone in ({"PIVOT_TO_R1", "ABOVE_R1"} if direction == "BULLISH" else {"S1_TO_PIVOT", "BELOW_S1"})


def _rsi_context(direction: str, value) -> bool:
    x = _f(value, 50)
    return 44 <= x <= 78 if direction == "BULLISH" else 22 <= x <= 56


def _wr_context(direction: str, value) -> bool:
    x = _f(value, -50)
    return -88 <= x <= -8 if direction == "BULLISH" else -92 <= x <= -12


def _rewrite_setup_id(snap: dict, direction: str, pattern: str):
    sid = str(snap.get("setup_id") or "")
    parts = sid.split(":")
    if len(parts) >= 4:
        parts[1], parts[2] = direction, pattern
        snap["setup_id"] = ":".join(parts)
    else:
        snap["setup_id"] = f"{snap.get('symbol','UNK')}:{direction}:{pattern}:{sid}"


def _regime_direction(snap: dict):
    tf = snap.get("tf") or {}
    s1h, s15 = tf.get("1h") or {}, tf.get("15m") or {}
    t1h, t15 = _trend(s1h), _trend(s15)
    adx1h = _f(s1h.get("adx"))
    if t15 == "BULLISH" and not (t1h == "BEARISH" and adx1h >= 24):
        return "BULLISH"
    if t15 == "BEARISH" and not (t1h == "BULLISH" and adx1h >= 24):
        return "BEARISH"
    return None


def _micro_trigger(direction: str, snap: dict) -> bool:
    tf = snap.get("tf") or {}
    s1 = tf.get("1m") or {}
    if bool(snap.get("one_min_breakout")):
        return True
    return _micro_flow(direction, s1) and _di_ratio(direction, s1) >= 0.98 and _rsi_context(direction, s1.get("rsi"))


def _confirmations(direction: str, snap: dict):
    tf = snap.get("tf") or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ("1m", "5m", "15m", "1h"))
    strong_1h_opposite = (_trend(s1h) not in {direction, "MIXED"} and _f(s1h.get("adx")) >= 24)
    return [
        ("15M primary regime", _trend(s15) == direction),
        ("1H not strongly opposite", not strong_1h_opposite),
        ("5M EMA flow", _ema_flow(direction, s5)),
        ("5M structure/near EMA9", _structure_ok(direction, str(snap.get("structure") or "")) or _f(snap.get("ema9_distance_atr")) <= 1.10),
        ("1M timing", _micro_trigger(direction, snap)),
        ("5M active tape", _f(s5.get("adx")) >= 10 or max(_f(s5.get("rel_volume")), _f(s1.get("rel_volume"))) >= 0.45),
        ("DI supports", _di_ratio(direction, s5) >= 0.98),
        ("RSI context", _rsi_context(direction, s1.get("rsi"))),
        ("Williams context", _wr_context(direction, s1.get("williams_r"))),
        ("Pivot context", _pivot_ok(direction, str(snap.get("five_zone") or ""))),
    ]


def evaluate_entry(underlying: str, action: str, snap: dict):
    underlying = str(underlying or "").upper()
    if underlying not in {"BTC", "ETH"}:
        return False, "V7.1 scalp universe: BTC/ETH only"

    tf = snap.get("tf") or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ("1m", "5m", "15m", "1h"))
    direction = _regime_direction(snap)
    if not direction:
        return False, "V7.1 wait: no usable 15M regime or strong 1H opposition"

    if not _ema_flow(direction, s5):
        return False, "V7.1 wait: 5M EMA flow not aligned"

    adx = _f(s5.get("adx")); rv = max(_f(s5.get("rel_volume")), _f(s1.get("rel_volume")))
    if adx < 8 and rv < 0.30:
        return False, f"V7.1 reject: dead tape ADX {adx:.1f} RVOL {rv:.2f}"

    vwap_atr = _f(snap.get("vwap_distance_atr")); ema9_atr = _f(snap.get("ema9_distance_atr"))
    if vwap_atr > 2.40 or ema9_atr > 1.60:
        return False, f"V7.1 reject: extreme chase {vwap_atr:.2f}/{ema9_atr:.2f} ATR"

    structure_ok = _structure_ok(direction, str(snap.get("structure") or "")); micro = _micro_trigger(direction, snap)
    if ema9_atr <= 1.10 and (micro or structure_ok):
        pattern = "SCALP_PULLBACK"
    elif bool(snap.get("one_min_breakout")) and ema9_atr <= 1.35:
        pattern = "SCALP_BREAKOUT"
    elif structure_ok and adx >= 12 and _di_ratio(direction, s5) >= 0.98:
        pattern = "SCALP_TREND_RESUME"
    else:
        return False, "V7.1 wait: no usable pullback/breakout/resume trigger"

    a5 = max(_f(s5.get("atr")), max(_f(s5.get("price")) * 0.0002, 1e-9)); price = _f(s5.get("price")); risk_atr = 1.10
    invalidation = price - risk_atr * a5 if direction == "BULLISH" else price + risk_atr * a5

    confirmations = _confirmations(direction, snap)
    passed = [name for name, ok in confirmations if ok]; failed = [name for name, ok in confirmations if not ok]
    # Primary hard gates only: 15M regime, 1H veto, 5M flow, and active tape.
    if not (confirmations[0][1] and confirmations[1][1] and confirmations[2][1] and confirmations[5][1]):
        return False, "V7.1 wait: primary scalp gates incomplete"

    snap.update({
        "direction": direction, "pattern": pattern,
        "confirmation_count": len(passed), "confirmation_total": len(confirmations),
        "confirmations_passed": passed, "confirmations_failed": failed,
        "scalp_mode": True, "precision_mode": True, "htf_trend_retest_mode": False,
        "v7_1_scalp_opportunity_mode": True, "structural_invalidation": invalidation,
        "underlying_risk_atr": risk_atr, "major_level_context_only": True,
    })
    _rewrite_setup_id(snap, direction, pattern)
    return True, f"V7_1_SCALP_PASS {pattern}"


def contract_gate(underlying: str, action: str, *, entry, bid, ask, spot=None, delta=None, tick_size=0.01, minutes_to_expiry=None, python_score=None):
    underlying = str(underlying or "").upper()
    if underlying not in {"BTC", "ETH"}:
        return False, "V7.1 BTC/ETH only", {}
    p, b, a = _f(entry, -1), _f(bid, -1), _f(ask, -1); tick = max(_f(tick_size, 0.01), 1e-9)
    if p <= 0 or b <= 0 or a <= 0 or a < b:
        return False, "invalid two-sided quote", {}
    mid = (a + b) / 2.0; spread = a - b; spread_pct = spread / mid * 100.0 if mid > 0 else 999.0
    cap = SPREAD_CAP_PCT.get(underlying, 4.0)
    if spread_pct > cap:
        return False, f"spread>{cap:.1f}%", {"spread_pct": spread_pct}
    min_premium = max(0.05, 3.0 * tick, 1.10 * spread)
    if p < min_premium:
        return False, f"premium<{min_premium:.4g} floor", {"spread_pct": spread_pct, "min_premium": min_premium}
    s = _f(spot, 0)
    if s > 0 and p / s > PREMIUM_SPOT_CAP.get(underlying, 0.028):
        return False, "premium/spot above V7.1 cap", {"spread_pct": spread_pct}
    d = None if delta is None else abs(_f(delta, -1))
    if d is not None and d >= 0 and not (0.30 <= d <= 0.65):
        return False, "delta outside V7.1 0.30-0.65", {"spread_pct": spread_pct, "abs_delta": d}
    score = _f(python_score, 100)
    if score < MIN_ALERT_SCORE:
        return False, f"Python score<{MIN_ALERT_SCORE}", {"spread_pct": spread_pct}
    if minutes_to_expiry is not None:
        mte = _f(minutes_to_expiry, -1)
        if 0 <= mte < 60:
            return False, "expiry<60m", {"spread_pct": spread_pct, "minutes_to_expiry": mte}
    return True, "V7_1_CONTRACT_PASS", {"spread_pct": spread_pct, "spread_abs": spread, "min_premium": min_premium, "abs_delta": d, "tick_size": tick}


def evaluate_contract(premium, *, tick_size=None, bid=None, ask=None, underlying="BTC", action="OPTION BUY", spot=None, delta=None, minutes_to_expiry=None, python_score=None):
    ok, reason, _ = contract_gate(underlying, action, entry=premium, bid=bid, ask=ask, spot=spot, delta=delta, tick_size=tick_size or 0.01, minutes_to_expiry=minutes_to_expiry, python_score=python_score)
    return ok, reason


def quality_score(underlying: str, snap: dict, contract_score: float = 0.0) -> int:
    if str(underlying or "").upper() not in {"BTC", "ETH"}:
        return 0
    direction = str(snap.get("direction") or "").upper(); tf = snap.get("tf") or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ("1m", "5m", "15m", "1h"))
    if direction not in {"BULLISH", "BEARISH"}:
        direction = _regime_direction(snap) or ""
    score = 0.0
    if direction and _trend(s15) == direction: score += 24
    if direction and _trend(s1h) == direction: score += 12
    elif _trend(s1h) == "MIXED": score += 8
    if direction and _ema_flow(direction, s5): score += 22
    if direction and _micro_trigger(direction, snap): score += 12
    if direction and _structure_ok(direction, str(snap.get("structure") or "")): score += 8
    elif _f(snap.get("ema9_distance_atr")) <= 1.10: score += 6
    adx = _f(s5.get("adx")); rv = max(_f(s5.get("rel_volume")), _f(s1.get("rel_volume")))
    score += 6 if adx >= 20 else (4 if adx >= 12 else 2)
    score += 6 if rv >= 1.0 else (4 if rv >= 0.60 else 2)
    if direction and _di_ratio(direction, s5) >= 1.02: score += 3
    if direction and _rsi_context(direction, s1.get("rsi")): score += 2
    if direction and _wr_context(direction, s1.get("williams_r")): score += 1
    if direction and _pivot_ok(direction, str(snap.get("five_zone") or "")): score += 1
    score += max(0.0, min(4.0, _f(contract_score) * 0.4))
    return int(round(max(0.0, min(100.0, score))))


def quality_label(score: int) -> str:
    if score >= ELITE_SCORE: return "ELITE"
    if score >= STRONG_SCORE: return "STRONG"
    if score >= MIN_ALERT_SCORE: return "VALID"
    return "NO TRADE"


def ai_adjustment(decision: str, confidence: int) -> int:
    d = str(decision or "").upper(); c = int(max(0, min(100, confidence or 0)))
    if d == "CONFIRM" and c >= 85: return 1
    if d == "WAIT": return -1
    if d == "REJECT" and c >= 90: return -1
    return 0
