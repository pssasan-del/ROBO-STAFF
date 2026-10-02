"""ROBO STAFF V6 HTF TREND RETEST.

Signal-only strategy:
- BTC/ETH only for this evidence-oriented research epoch.
- 1H defines regime.
- 15M must confirm the same direction.
- 5M provides the setup and must not be chased.
- 1M is timing only.
- RSI/Williams/ADX/Pivots are context, not stacked mandatory gates.
MASTER MIND stays separate and untouched.
"""

from __future__ import annotations
import math

POLISH_VERSION = "FRESH_V6_HTF_TREND_RETEST_2026-10-02"
MODE_REVISION = "1H_15M_5M_RETEST_1M_TRIGGER_2026-10-02"

MIN_ALERT_SCORE = 72
STRONG_SCORE = 82
ELITE_SCORE = 90
DAILY_RESEARCH_TARGET = 6

SPREAD_CAP_PCT = {"BTC": 3.0, "ETH": 3.5, "GOLD": 5.5}
DAILY_SIGNAL_CAP = {"BTC": 24, "ETH": 24, "GOLD": 0}
PREMIUM_SPOT_CAP = {"BTC": 0.020, "ETH": 0.024, "GOLD": 0.030}

BASE_COOLDOWN_MINUTES = 8
SUCCESS_COOLDOWN_MINUTES = 6
FAIL_COOLDOWN_MINUTES = 12
CONTRACT_COOLDOWN_MINUTES = 10
CORRELATION_WINDOW_MINUTES = 12
CORRELATION_THRESHOLD = 0.95

ACCEPTANCE_CRITERIA = {
    "min_resolved": 40,
    "preferred_resolved": 80,
    "min_calendar_days": 5,
    "min_t1_success_pct": 40.0,
    "min_profit_factor": 1.20,
    "min_expectancy_r": 0.05,
    "max_median_t1_minutes": 30.0,
    "max_p75_t1_minutes": 45.0,
    "max_fast_sl_pct": 22.0,
    "max_sl_later_t1_pct": 15.0,
    "max_stale_pct": 18.0,
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
        return px >= e9 and e5 >= e9 and e9 >= e20
    return px <= e9 and e5 <= e9 and e9 <= e20


def _micro_flow(direction: str, state: dict) -> bool:
    px, e5, e9 = (_f(state.get(k)) for k in ("price", "ema5", "ema9"))
    pdi, mdi = _f(state.get("plus_di")), _f(state.get("minus_di"))
    if direction == "BULLISH":
        return px >= e5 >= e9 and pdi >= mdi
    return px <= e5 <= e9 and mdi >= pdi


def _di_ratio(direction: str, state: dict) -> float:
    pdi, mdi = _f(state.get("plus_di")), _f(state.get("minus_di"))
    return pdi / max(mdi, 1.0) if direction == "BULLISH" else mdi / max(pdi, 1.0)


def _structure_ok(direction: str, structure: str) -> bool:
    return (direction == "BULLISH" and structure == "HH/HL") or (
        direction == "BEARISH" and structure == "LH/LL"
    )


def _pivot_ok(direction: str, zone: str) -> bool:
    if direction == "BULLISH":
        return zone in {"PIVOT_TO_R1", "ABOVE_R1"}
    return zone in {"S1_TO_PIVOT", "BELOW_S1"}


def _rsi_context(direction: str, value) -> bool:
    x = _f(value, 50)
    return 48 <= x <= 74 if direction == "BULLISH" else 26 <= x <= 52


def _wr_context(direction: str, value) -> bool:
    x = _f(value, -50)
    return -82 <= x <= -12 if direction == "BULLISH" else -88 <= x <= -18


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
    if t1h == "BULLISH" and t15 == "BULLISH":
        return "BULLISH"
    if t1h == "BEARISH" and t15 == "BEARISH":
        return "BEARISH"
    return None


def _micro_trigger(direction: str, snap: dict) -> bool:
    tf = snap.get("tf") or {}
    s1 = tf.get("1m") or {}
    if bool(snap.get("one_min_breakout")):
        return True
    return _micro_flow(direction, s1) and _di_ratio(direction, s1) >= 1.03 and _rsi_context(direction, s1.get("rsi"))


def _confirmations(direction: str, snap: dict):
    tf = snap.get("tf") or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ("1m", "5m", "15m", "1h"))
    return [
        ("1H regime", _trend(s1h) == direction),
        ("15M confirmation", _trend(s15) == direction),
        ("5M EMA flow", _ema_flow(direction, s5)),
        ("5M structure/retest", _structure_ok(direction, str(snap.get("structure") or "")) or _f(snap.get("ema9_distance_atr")) <= 0.85),
        ("1M timing", _micro_trigger(direction, snap)),
        ("5M active tape", _f(s5.get("adx")) >= 12 or max(_f(s5.get("rel_volume")), _f(s1.get("rel_volume"))) >= 0.60),
        ("DI supports", _di_ratio(direction, s5) >= 1.05),
        ("RSI context", _rsi_context(direction, s1.get("rsi"))),
        ("Williams context", _wr_context(direction, s1.get("williams_r"))),
        ("Pivot context", _pivot_ok(direction, str(snap.get("five_zone") or ""))),
    ]


def evaluate_entry(underlying: str, action: str, snap: dict):
    underlying = str(underlying or "").upper()
    if underlying not in {"BTC", "ETH"}:
        return False, "V6 research universe: BTC/ETH only"

    tf = snap.get("tf") or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ("1m", "5m", "15m", "1h"))

    direction = _regime_direction(snap)
    if not direction:
        return False, "V6 wait: 1H and 15M regime not aligned"

    if not _ema_flow(direction, s5):
        return False, "V6 wait: 5M EMA flow not aligned"

    adx = _f(s5.get("adx"))
    rv = max(_f(s5.get("rel_volume")), _f(s1.get("rel_volume")))
    if adx < 9 and rv < 0.40:
        return False, f"V6 reject: inactive tape ADX {adx:.1f} RVOL {rv:.2f}"

    vwap_atr = _f(snap.get("vwap_distance_atr"))
    ema9_atr = _f(snap.get("ema9_distance_atr"))
    if vwap_atr > 2.0 or ema9_atr > 1.25:
        return False, f"V6 reject: chased entry {vwap_atr:.2f}/{ema9_atr:.2f} ATR"

    structure_ok = _structure_ok(direction, str(snap.get("structure") or ""))
    micro = _micro_trigger(direction, snap)

    if ema9_atr <= 0.85 and micro:
        pattern = "RETEST_RESUME"
    elif bool(snap.get("one_min_breakout")) and structure_ok and ema9_atr <= 1.05:
        pattern = "BREAKOUT_RETEST"
    elif structure_ok and micro and adx >= 16 and _di_ratio(direction, s5) >= 1.08:
        pattern = "TREND_RESUME"
    else:
        return False, "V6 wait: no retest/resume trigger"

    a5 = max(_f(s5.get("atr")), max(_f(s5.get("price")) * 0.0002, 1e-9))
    price = _f(s5.get("price"))
    risk_atr = 1.05
    invalidation = price - risk_atr * a5 if direction == "BULLISH" else price + risk_atr * a5

    confirmations = _confirmations(direction, snap)
    passed = [name for name, ok in confirmations if ok]
    failed = [name for name, ok in confirmations if not ok]

    core = confirmations[:6]
    if not all(ok for _, ok in core):
        return False, "V6 wait: core regime/setup/timing confirmation incomplete"

    snap["direction"] = direction
    snap["pattern"] = pattern
    snap["confirmation_count"] = len(passed)
    snap["confirmation_total"] = len(confirmations)
    snap["confirmations_passed"] = passed
    snap["confirmations_failed"] = failed
    snap["scalp_mode"] = True
    snap["precision_mode"] = True
    snap["htf_trend_retest_mode"] = True
    snap["clean_confluence_mode"] = False
    snap["structural_invalidation"] = invalidation
    snap["underlying_risk_atr"] = risk_atr
    snap["major_level_context_only"] = True
    _rewrite_setup_id(snap, direction, pattern)
    return True, f"V6_TREND_RETEST_PASS {pattern}"


def contract_gate(
    underlying: str, action: str, *, entry, bid, ask, spot=None, delta=None,
    tick_size=0.01, minutes_to_expiry=None, python_score=None
):
    underlying = str(underlying or "").upper()
    action = str(action or "").upper()
    if underlying not in {"BTC", "ETH"}:
        return False, "V6 BTC/ETH only", {}

    p, b, a = _f(entry, -1), _f(bid, -1), _f(ask, -1)
    tick = max(_f(tick_size, 0.01), 1e-9)
    if p <= 0 or b <= 0 or a <= 0 or a < b:
        return False, "invalid two-sided quote", {}

    mid = (a + b) / 2.0
    spread = a - b
    spread_pct = spread / mid * 100.0 if mid > 0 else 999.0
    cap = SPREAD_CAP_PCT.get(underlying, 3.5)
    if spread_pct > cap:
        return False, f"spread>{cap:.1f}%", {"spread_pct": spread_pct}

    min_premium = max(0.05, 3.0 * tick, 1.20 * spread)
    if p < min_premium:
        return False, f"premium<{min_premium:.4g} floor", {"spread_pct": spread_pct, "min_premium": min_premium}

    s = _f(spot, 0)
    if s > 0 and p / s > PREMIUM_SPOT_CAP.get(underlying, 0.025):
        return False, "premium/spot above V6 cap", {"spread_pct": spread_pct}

    d = None if delta is None else abs(_f(delta, -1))
    if d is not None and d >= 0 and not (0.35 <= d <= 0.60):
        return False, "delta outside V6 0.35-0.60", {"spread_pct": spread_pct, "abs_delta": d}

    score = _f(python_score, 100)
    if score < MIN_ALERT_SCORE:
        return False, f"Python score<{MIN_ALERT_SCORE}", {"spread_pct": spread_pct}

    if minutes_to_expiry is not None:
        mte = _f(minutes_to_expiry, -1)
        if 0 <= mte < 90:
            return False, "expiry<90m", {"spread_pct": spread_pct, "minutes_to_expiry": mte}

    return True, "V6_CONTRACT_PASS", {
        "spread_pct": spread_pct,
        "spread_abs": spread,
        "min_premium": min_premium,
        "abs_delta": d,
        "tick_size": tick,
    }


def evaluate_contract(
    premium, *, tick_size=None, bid=None, ask=None, underlying="BTC", action="OPTION BUY",
    spot=None, delta=None, minutes_to_expiry=None, python_score=None
):
    ok, reason, _ = contract_gate(
        underlying, action, entry=premium, bid=bid, ask=ask, spot=spot, delta=delta,
        tick_size=tick_size or 0.01, minutes_to_expiry=minutes_to_expiry, python_score=python_score
    )
    return ok, reason


def quality_score(underlying: str, snap: dict, contract_score: float = 0.0) -> int:
    if str(underlying or "").upper() not in {"BTC", "ETH"}:
        return 0
    direction = str(snap.get("direction") or "").upper()
    tf = snap.get("tf") or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ("1m", "5m", "15m", "1h"))
    if direction not in {"BULLISH", "BEARISH"}:
        direction = _regime_direction(snap) or ""

    score = 0.0
    if direction and _trend(s1h) == direction:
        score += 22
    if direction and _trend(s15) == direction:
        score += 20
    if direction and _ema_flow(direction, s5):
        score += 18
    if direction and _micro_trigger(direction, snap):
        score += 16

    if direction and _structure_ok(direction, str(snap.get("structure") or "")):
        score += 7
    elif _f(snap.get("ema9_distance_atr")) <= 0.85:
        score += 5

    adx = _f(s5.get("adx"))
    rv = max(_f(s5.get("rel_volume")), _f(s1.get("rel_volume")))
    score += 5 if adx >= 20 else (3 if adx >= 14 else 1)
    score += 4 if rv >= 1.0 else (3 if rv >= 0.60 else 1)

    if direction and _di_ratio(direction, s5) >= 1.08:
        score += 3
    if direction and _rsi_context(direction, s1.get("rsi")):
        score += 2
    if direction and _wr_context(direction, s1.get("williams_r")):
        score += 1
    if direction and _pivot_ok(direction, str(snap.get("five_zone") or "")):
        score += 1

    score += max(0.0, min(4.0, _f(contract_score) * 0.4))
    return int(round(max(0.0, min(100.0, score))))


def quality_label(score: int) -> str:
    if score >= ELITE_SCORE:
        return "ELITE"
    if score >= STRONG_SCORE:
        return "STRONG"
    if score >= MIN_ALERT_SCORE:
        return "VALID"
    return "NO TRADE"


def ai_adjustment(decision: str, confidence: int) -> int:
    d = str(decision or "").upper()
    c = int(max(0, min(100, confidence or 0)))
    if d == "CONFIRM" and c >= 85:
        return 1
    if d == "WAIT":
        return -1
    if d == "REJECT" and c >= 90:
        return -1
    return 0
