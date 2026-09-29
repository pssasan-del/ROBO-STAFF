"""ROBO STAFF first Delta strategy — Fresh V3.5 LOCAL SCALP FLOW research policy.

This version replaces the previous pullback/reclaim-only logic with a lighter
scalping model. 1m + 5m local flow decide direction; 15m/1h are context only and
are never universal direction blockers. Daily/5m pivots are treated as major
levels/quality context, not mandatory trend filters. The goal is to collect
usable scalp samples while keeping quote/dust/expiry/chase protection.

SIGNAL ONLY: no order placement, modification, cancellation or broker secrets.
MASTER MIND remains a separate engine with its own cooldown.
"""
from __future__ import annotations

import math

POLISH_VERSION = "FRESH_V3.5_LOCAL_SCALP_2026-09-29"
MODE_REVISION = "LOCAL_1M5M_SCALP_FLOW_2026-09-29"
MIN_ALERT_SCORE = 50
STRONG_SCORE = 68
ELITE_SCORE = 84
DAILY_RESEARCH_TARGET = 3

SPREAD_CAP_PCT = {"BTC": 4.0, "ETH": 5.0, "GOLD": 6.0}
DAILY_SIGNAL_CAP = {"BTC": 12, "ETH": 12, "GOLD": 10}
PREMIUM_SPOT_CAP = {"BTC": 0.0140, "ETH": 0.0140, "GOLD": 0.0180}

BASE_COOLDOWN_MINUTES = 5
SUCCESS_COOLDOWN_MINUTES = 4
FAIL_COOLDOWN_MINUTES = 8
CONTRACT_COOLDOWN_MINUTES = 7
CORRELATION_WINDOW_MINUTES = 6
CORRELATION_THRESHOLD = 0.92

ACCEPTANCE_CRITERIA = {
    "min_resolved": 50,
    "preferred_resolved": 75,
    "min_calendar_days": 3,
    "min_t1_success_pct": 40.0,
    "min_profit_factor": 1.15,
    "min_expectancy_r": 0.08,
    "max_median_t1_minutes": 25.0,
    "max_p75_t1_minutes": 40.0,
    "max_fast_sl_pct": 35.0,
    "max_sl_later_t1_pct": 22.0,
    "max_stale_pct": 22.0,
    "bucket_min_n": 12,
    "bucket_min_win_pct": 34.0,
    "bucket_min_pf": 0.95,
}


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _di_ratio(direction: str, state: dict) -> float:
    pdi, mdi = _f(state.get('plus_di')), _f(state.get('minus_di'))
    if direction == 'BULLISH':
        return pdi / max(mdi, 1.0)
    return mdi / max(pdi, 1.0)


def _votes(direction: str, state: dict) -> int:
    px, e5, e9, vw = (_f(state.get(k)) for k in ('price','ema5','ema9','vwap'))
    pdi, mdi = _f(state.get('plus_di')), _f(state.get('minus_di'))
    if direction == 'BULLISH':
        return sum((px >= e9, e5 >= e9, pdi >= mdi, px >= vw * 0.9995))
    if direction == 'BEARISH':
        return sum((px <= e9, e5 <= e9, mdi >= pdi, px <= vw * 1.0005))
    return 0


def _micro_votes(direction: str, state: dict) -> int:
    px, e5, e9 = (_f(state.get(k)) for k in ('price','ema5','ema9'))
    pdi, mdi = _f(state.get('plus_di')), _f(state.get('minus_di'))
    if direction == 'BULLISH':
        return sum((px >= e9, e5 >= e9, pdi >= mdi))
    if direction == 'BEARISH':
        return sum((px <= e9, e5 <= e9, mdi >= pdi))
    return 0


def _tf_soft(direction: str, state: dict) -> bool:
    px, e9, vw = _f(state.get('price')), _f(state.get('ema9')), _f(state.get('vwap'))
    pdi, mdi = _f(state.get('plus_di')), _f(state.get('minus_di'))
    if direction == 'BULLISH':
        return px >= e9 or px >= vw or pdi >= mdi
    if direction == 'BEARISH':
        return px <= e9 or px <= vw or mdi >= pdi
    return False


def _structure_ok(direction: str, structure: str) -> bool:
    return (direction == 'BULLISH' and structure == 'HH/HL') or (direction == 'BEARISH' and structure == 'LH/LL')


def _pivot_supports(direction: str, zone: str) -> bool:
    if direction == 'BULLISH':
        return zone in {'PIVOT_TO_R1','ABOVE_R1'}
    if direction == 'BEARISH':
        return zone in {'S1_TO_PIVOT','BELOW_S1'}
    return False


def _rewrite_setup_id(snap: dict, direction: str, pattern: str):
    sid = str(snap.get('setup_id') or '')
    parts = sid.split(':')
    if len(parts) >= 4:
        parts[1] = direction
        parts[2] = pattern
        snap['setup_id'] = ':'.join(parts)
    else:
        snap['setup_id'] = f"{snap.get('symbol','UNK')}:{direction}:{pattern}:{sid}"


def _infer_local_direction(snap: dict):
    tf = snap.get('tf') or {}
    s1, s5 = tf.get('1m') or {}, tf.get('5m') or {}
    scored = []
    for d in ('BULLISH','BEARISH'):
        v5, v1 = _votes(d, s5), _micro_votes(d, s1)
        scored.append((v5 * 2 + v1, v5, v1, d))
    scored.sort(reverse=True)
    total, v5, v1, direction = scored[0]
    other = scored[1]
    if v5 >= 3 and v1 >= 2 and total > other[0]:
        return direction, f'local 5m/1m flow {v5}/4 + {v1}/3'
    if v5 == 4 and v1 >= 1 and total >= other[0] + 2:
        return direction, f'strong 5m flow {v5}/4; early 1m confirmation {v1}/3'
    return None, f'local flow unresolved best={direction} 5m={v5}/4 1m={v1}/3'


def evaluate_entry(underlying: str, action: str, snap: dict):
    """Local scalp gate: 1m/5m choose direction, higher TFs only add context."""
    underlying = str(underlying or '').upper()
    tf = snap.get('tf') or {}
    s1, s5 = tf.get('1m') or {}, tf.get('5m') or {}
    s15, s1h = tf.get('15m') or {}, tf.get('1h') or {}

    direction, why = _infer_local_direction(snap)
    if not direction:
        return False, f'V3.5 wait: {why}'
    snap['direction'] = direction
    snap['bias_reason'] = why

    v5, v1 = _votes(direction, s5), _micro_votes(direction, s1)
    adx = _f(s5.get('adx'))
    rvol = _f(s5.get('rel_volume'))
    ratio = _di_ratio(direction, s5)
    structure = str(snap.get('structure') or '')
    structure_ok = _structure_ok(direction, structure)

    # Only truly dead tape is rejected. ADX/RVOL are quality inputs otherwise.
    if adx < 7 and rvol < 0.18 and not structure_ok:
        return False, f'V3.5 dead tape ADX/RVOL {adx:.1f}/{rvol:.2f}'

    vwap_atr = _f(snap.get('vwap_distance_atr'))
    ema9_atr = _f(snap.get('ema9_distance_atr'))
    breakout_ext = _f(snap.get('breakout_extension_atr'))
    if vwap_atr > 3.50 or ema9_atr > 2.00:
        return False, f'V3.5 extreme chase VWAP/EMA9 {vwap_atr:.2f}/{ema9_atr:.2f} ATR'

    daily_zone = str(snap.get('daily_zone') or '')
    five_zone = str(snap.get('five_zone') or '')
    pivot5 = _pivot_supports(direction, five_zone)
    pivotd = _pivot_supports(direction, daily_zone)
    htf15 = _tf_soft(direction, s15)
    htf1h = _tf_soft(direction, s1h)

    cross = snap.get('ema_cross_5m') or {}
    cross_ok = str(cross.get('side') or '').upper() == direction and cross.get('bars_ago') in (0,1)
    old_pattern = str(snap.get('pattern') or '').upper()

    # Pattern selection intentionally favors frequency; pivots/HTF only label quality.
    if ema9_atr <= 0.70:
        pattern = 'PULLBACK_SCALP'
    elif old_pattern in {'BREAKOUT','RETEST'} and cross_ok and breakout_ext <= 1.20:
        pattern = 'BREAKOUT_SCALP' if old_pattern == 'BREAKOUT' else 'RETEST_SCALP'
    elif adx >= 12 or rvol >= 0.35 or ratio >= 1.05:
        pattern = 'MOMENTUM_SCALP'
    else:
        pattern = 'EARLY_SCALP'

    snap['pattern'] = pattern
    snap['scalp_mode'] = True
    snap['momentum_mode'] = pattern in {'MOMENTUM_SCALP','BREAKOUT_SCALP'}
    snap['structure_relaxed'] = not structure_ok
    snap['one_min_trigger'] = v1 >= 2
    snap['one_min_ema_hold'] = v1 >= 2
    snap['micro_trigger'] = v1 >= 2
    snap['price_ema_aligned'] = v5 >= 3
    snap['local_5m_votes'] = v5
    snap['local_1m_votes'] = v1
    snap['htf15_context'] = htf15
    snap['htf1h_context'] = htf1h
    snap['pivot5_context'] = pivot5
    snap['pivotd_context'] = pivotd
    snap['major_level_context_only'] = True
    _rewrite_setup_id(snap, direction, pattern)
    return True, 'V3.5_LOCAL_SCALP_PASS'


def contract_gate(underlying: str, action: str, *, entry, bid, ask, spot=None, delta=None,
                  tick_size=0.01, minutes_to_expiry=None, python_score=None):
    underlying = str(underlying or '').upper()
    action = str(action or '').upper()
    p, b, a = _f(entry, -1), _f(bid, -1), _f(ask, -1)
    tick = max(_f(tick_size, 0.01), 1e-9)
    if p <= 0 or b <= 0 or a <= 0 or a < b:
        return False, 'invalid two-sided quote', {}

    mid = (a + b) / 2.0
    spread = a - b
    spread_pct = spread / mid * 100.0 if mid > 0 else 999.0
    cap = SPREAD_CAP_PCT.get(underlying, 5.0)
    if spread_pct > cap:
        return False, f'spread>{cap:.1f}%', {'spread_pct': spread_pct}

    min_premium = max(0.06, 4.0 * tick, 2.0 * spread)
    if p < min_premium:
        return False, f'premium<{min_premium:.4g} execution floor', {'spread_pct': spread_pct, 'min_premium': min_premium}

    s = _f(spot, 0)
    if s > 0 and p / s > PREMIUM_SPOT_CAP.get(underlying, 0.014):
        return False, 'premium/spot above V3.5 cap', {'spread_pct': spread_pct}

    d = None if delta is None else abs(_f(delta, -1))
    if d is not None and d >= 0:
        if d < 0.05:
            return False, 'lottery delta<0.05', {'spread_pct': spread_pct, 'abs_delta': d}
        lo, hi = ((0.12, 0.65) if action == 'OPTION BUY' else (0.08, 0.50))
        if not (lo <= d <= hi):
            return False, f'delta outside V3.5 {lo:.2f}-{hi:.2f}', {'spread_pct': spread_pct, 'abs_delta': d}

    score = _f(python_score, 100)
    if action == 'OPTION BUY' and score < 52:
        return False, 'OPTION BUY requires Python score>=52', {'spread_pct': spread_pct}
    if action == 'OPTION SELL' and score < 48:
        return False, 'OPTION SELL requires Python score>=48', {'spread_pct': spread_pct}

    if minutes_to_expiry is not None:
        mte = _f(minutes_to_expiry, -1)
        if 0 <= mte < 45:
            return False, 'expiry<45m', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}
        if 45 <= mte < 90 and (score < 60 or spread_pct > 4.5):
            return False, 'near-expiry needs score>=60 and spread<=4.5%', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}

    return True, 'CONTRACT_GATE_PASS', {
        'spread_pct': spread_pct, 'spread_abs': spread, 'min_premium': min_premium,
        'abs_delta': d, 'tick_size': tick,
    }


def evaluate_contract(premium, *, tick_size=None, bid=None, ask=None, underlying='BTC', action='OPTION BUY',
                      spot=None, delta=None, minutes_to_expiry=None, python_score=None):
    ok, reason, _ = contract_gate(
        underlying, action, entry=premium, bid=bid, ask=ask, spot=spot, delta=delta,
        tick_size=tick_size or 0.01, minutes_to_expiry=minutes_to_expiry,
        python_score=python_score,
    )
    return ok, reason


def quality_score(underlying: str, snap: dict, contract_score: float = 0.0) -> int:
    direction = str(snap.get('direction') or '').upper()
    tf = snap.get('tf') or {}
    s1, s5 = tf.get('1m') or {}, tf.get('5m') or {}
    s15, s1h = tf.get('15m') or {}, tf.get('1h') or {}
    v5, v1 = _votes(direction, s5), _micro_votes(direction, s1)
    score = v5 * 6.0 + v1 * 6.0

    if _structure_ok(direction, str(snap.get('structure') or '')):
        score += 8
    else:
        score += 3

    adx, ratio, rvol = _f(s5.get('adx')), _di_ratio(direction, s5), _f(s5.get('rel_volume'))
    score += 8 if adx >= 24 else (6 if adx >= 16 else (3 if adx >= 9 else 0))
    score += 7 if ratio >= 1.25 else (5 if ratio >= 1.08 else (2 if ratio >= 0.98 else 0))
    score += 7 if rvol >= 1.25 else (5 if rvol >= 0.75 else (2 if rvol >= 0.30 else 0))

    if _pivot_supports(direction, str(snap.get('five_zone') or '')):
        score += 4
    if _pivot_supports(direction, str(snap.get('daily_zone') or '')):
        score += 2
    if _tf_soft(direction, s15):
        score += 3
    if _tf_soft(direction, s1h):
        score += 2

    vwap_atr, ema9_atr = _f(snap.get('vwap_distance_atr')), _f(snap.get('ema9_distance_atr'))
    if vwap_atr <= 1.5:
        score += 4
    elif vwap_atr <= 2.5:
        score += 2
    if ema9_atr <= 0.8:
        score += 4
    elif ema9_atr <= 1.4:
        score += 2

    pattern = str(snap.get('pattern') or '')
    if pattern == 'PULLBACK_SCALP':
        score += 6
    elif pattern in {'RETEST_SCALP','BREAKOUT_SCALP'}:
        score += 5
    elif pattern == 'MOMENTUM_SCALP':
        score += 4
    elif pattern == 'EARLY_SCALP':
        score += 2

    score += max(0.0, min(10.0, _f(contract_score)))
    return int(round(max(0.0, min(100.0, score))))


def quality_label(score: int) -> str:
    if score >= ELITE_SCORE:
        return 'ELITE'
    if score >= STRONG_SCORE:
        return 'STRONG'
    if score >= MIN_ALERT_SCORE:
        return 'VALID'
    return 'NO TRADE'


def ai_adjustment(decision: str, confidence: int) -> int:
    d = str(decision or '').upper()
    c = int(max(0, min(100, confidence or 0)))
    if d == 'CONFIRM' and c >= 80:
        return 3
    if d == 'WAIT':
        return -2
    if d == 'REJECT':
        return -5 if c >= 90 else -3
    return 0
