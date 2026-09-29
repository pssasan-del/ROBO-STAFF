"""ROBO STAFF Delta first strategy — Fresh V3.3 OPEN SCALP research policy.

This policy intentionally loosens the FIRST ROBO STAFF strategy so live research
collects usable signals instead of remaining silent. It is still SIGNAL ONLY.
The separate MASTER MIND module is not coupled to this file.

Design:
- prefer 5m + 1m local direction;
- 15m/1h become context/score, not universal hard blockers;
- pivots/structure become quality inputs, not universal hard blockers;
- keep dead-market, extreme-chase and unusable-option protections;
- AI remains display-only/non-blocking in the existing engine.
"""
from __future__ import annotations

import math

POLISH_VERSION = "FRESH_V3.3_LOOSE_2026-09-29"
MODE_REVISION = "OPEN_SCALP_RESEARCH_2026-09-29"
MIN_ALERT_SCORE = 55
STRONG_SCORE = 75
ELITE_SCORE = 90
DAILY_RESEARCH_TARGET = 3

# Wider, but still bounded, executable quote limits.
SPREAD_CAP_PCT = {"BTC": 3.5, "ETH": 4.5, "GOLD": 5.5}
DAILY_SIGNAL_CAP = {"BTC": 10, "ETH": 10, "GOLD": 8}
PREMIUM_SPOT_CAP = {"BTC": 0.0125, "ETH": 0.0125, "GOLD": 0.0150}

BASE_COOLDOWN_MINUTES = 8
SUCCESS_COOLDOWN_MINUTES = 5
FAIL_COOLDOWN_MINUTES = 12
CONTRACT_COOLDOWN_MINUTES = 10
CORRELATION_WINDOW_MINUTES = 8
CORRELATION_THRESHOLD = 0.90

ACCEPTANCE_CRITERIA = {
    "min_resolved": 50,
    "preferred_resolved": 75,
    "min_calendar_days": 3,
    "min_t1_success_pct": 40.0,
    "min_profit_factor": 1.20,
    "min_expectancy_r": 0.10,
    "max_median_t1_minutes": 25.0,
    "max_p75_t1_minutes": 40.0,
    "max_fast_sl_pct": 35.0,
    "max_sl_later_t1_pct": 22.0,
    "max_stale_pct": 20.0,
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


def _local_5m(direction: str, s5: dict) -> bool:
    px, e5, e9 = (_f(s5.get(k)) for k in ('price', 'ema5', 'ema9'))
    pdi, mdi = _f(s5.get('plus_di')), _f(s5.get('minus_di'))
    if direction == 'BULLISH':
        return px > e9 and e5 >= e9 and pdi >= mdi
    if direction == 'BEARISH':
        return px < e9 and e5 <= e9 and mdi >= pdi
    return False


def _micro_1m(direction: str, s1: dict) -> bool:
    px, e5, e9 = (_f(s1.get(k)) for k in ('price', 'ema5', 'ema9'))
    pdi, mdi = _f(s1.get('plus_di')), _f(s1.get('minus_di'))
    adx = _f(s1.get('adx'))
    if direction == 'BULLISH':
        return px > e9 and e5 >= e9 and pdi >= mdi and adx >= 5
    if direction == 'BEARISH':
        return px < e9 and e5 <= e9 and mdi >= pdi and adx >= 5
    return False


def _tf_soft(direction: str, state: dict) -> bool:
    px, e9, vw = _f(state.get('price')), _f(state.get('ema9')), _f(state.get('vwap'))
    pdi, mdi = _f(state.get('plus_di')), _f(state.get('minus_di'))
    if direction == 'BULLISH':
        return px >= e9 and (px >= vw or pdi >= mdi)
    if direction == 'BEARISH':
        return px <= e9 and (px <= vw or mdi >= pdi)
    return False


def _tf_strong_opposite(direction: str, state: dict) -> bool:
    px = _f(state.get('price')); e5 = _f(state.get('ema5')); e9 = _f(state.get('ema9')); e20 = _f(state.get('ema20'))
    pdi, mdi, adx = _f(state.get('plus_di')), _f(state.get('minus_di')), _f(state.get('adx'))
    if direction == 'BULLISH':
        return px < e5 < e9 < e20 and mdi > pdi * 1.20 and adx >= 24
    if direction == 'BEARISH':
        return px > e5 > e9 > e20 and pdi > mdi * 1.20 and adx >= 24
    return False


def _structure_ok(direction: str, structure: str) -> bool:
    return (direction == 'BULLISH' and structure == 'HH/HL') or (direction == 'BEARISH' and structure == 'LH/LL')


def _pivot_supports(direction: str, zone: str) -> bool:
    if direction == 'BULLISH':
        return zone in {'PIVOT_TO_R1', 'ABOVE_R1'}
    if direction == 'BEARISH':
        return zone in {'S1_TO_PIVOT', 'BELOW_S1'}
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


def _infer_direction(snap: dict):
    tf = snap.get('tf') or {}
    s1 = tf.get('1m') or {}; s5 = tf.get('5m') or {}; s15 = tf.get('15m') or {}; s1h = tf.get('1h') or {}

    # Primary: 5m local direction + 1m confirmation.
    for d in ('BULLISH', 'BEARISH'):
        if _local_5m(d, s5) and _micro_1m(d, s1):
            return d, '5m+1m local alignment'

    # Secondary: 5m direction plus at least one higher timeframe leaning same way.
    for d in ('BULLISH', 'BEARISH'):
        if _local_5m(d, s5) and (_tf_soft(d, s15) or _tf_soft(d, s1h)):
            return d, '5m local + higher-timeframe lean'

    # Tertiary research path: 1m and 15m agree while 5m DI is not opposite.
    for d in ('BULLISH', 'BEARISH'):
        if _micro_1m(d, s1) and _tf_soft(d, s15) and _di_ratio(d, s5) >= 1.0:
            return d, '1m+15m early scalp bias'

    return None, 'no usable local direction'


def evaluate_entry(underlying: str, action: str, snap: dict):
    """Loose first-strategy gate for signal-frequency research.

    Hard rejects are deliberately limited to dead tape, extreme chase, exhausted
    momentum, or a two-HTF hard contradiction without strong local force.
    """
    underlying = str(underlying or '').upper()
    tf = snap.get('tf') or {}
    s1 = tf.get('1m') or {}; s5 = tf.get('5m') or {}; s15 = tf.get('15m') or {}; s1h = tf.get('1h') or {}

    direction = str(snap.get('direction') or '').upper()
    if direction not in {'BULLISH', 'BEARISH'}:
        direction, reason = _infer_direction(snap)
        if not direction:
            return False, f'open scalp: {reason}'
        snap['direction'] = direction
        snap['bias_scalp_mode'] = True
        snap['bias_reason'] = reason
    else:
        # Even directional snapshots use local tape as the immediate authority.
        if not _local_5m(direction, s5):
            inferred, reason = _infer_direction(snap)
            if inferred:
                direction = inferred
                snap['direction'] = direction
                snap['bias_reason'] = reason

    local5 = _local_5m(direction, s5)
    micro = _micro_1m(direction, s1)
    adx = _f(s5.get('adx'))
    ratio = _di_ratio(direction, s5)
    rvol = _f(s5.get('rel_volume'))
    structure = str(snap.get('structure') or '')

    if not local5 and not micro:
        return False, 'open scalp: neither 5m local alignment nor 1m trigger'

    # Dead-market reject only when BOTH trend strength and participation are poor.
    if adx < 12 and rvol < 0.35:
        return False, f'open scalp dead tape ADX/RVOL {adx:.1f}/{rvol:.2f}'

    # DI can be nearly balanced in reversals; require only a minimal directional edge.
    if ratio < 1.02 and not _structure_ok(direction, structure):
        return False, f'open scalp DI edge too weak {ratio:.2f}'

    vwap_atr = _f(snap.get('vwap_distance_atr'))
    ema9_atr = _f(snap.get('ema9_distance_atr'))
    if vwap_atr > 3.20 or ema9_atr > 1.80:
        return False, f'open scalp extreme chase VWAP/EMA9 {vwap_atr:.2f}/{ema9_atr:.2f} ATR'

    # If BOTH higher TFs are strongly opposite, local tape must be meaningfully strong.
    both_opposite = _tf_strong_opposite(direction, s15) and _tf_strong_opposite(direction, s1h)
    if both_opposite and not (adx >= 24 and ratio >= 1.25 and rvol >= 0.70):
        return False, 'open scalp both 15m/1h strongly opposite without local impulse'

    rsi5 = _f(s5.get('rsi')); wr5 = _f(s5.get('williams_r'))
    if direction == 'BULLISH' and (rsi5 > 92 or wr5 > -0.5):
        return False, 'open scalp bullish exhaustion extreme'
    if direction == 'BEARISH' and (rsi5 < 8 or wr5 < -99.5):
        return False, 'open scalp bearish exhaustion extreme'

    old_pattern = str(snap.get('pattern') or '').upper()
    cross = snap.get('ema_cross_5m') or {}
    cross_ok = str(cross.get('side') or '').upper() == direction and cross.get('bars_ago') in (0, 1)
    if old_pattern in {'BREAKOUT', 'RETEST'} and cross_ok:
        pattern = old_pattern
    elif _structure_ok(direction, structure):
        pattern = 'TREND_SCALP'
    elif both_opposite:
        pattern = 'COUNTERTREND_SCALP'
    else:
        pattern = 'OPEN_SCALP'

    snap['pattern'] = pattern
    snap['scalp_mode'] = True
    snap['momentum_mode'] = True
    snap['structure_relaxed'] = not _structure_ok(direction, structure)
    snap['one_min_trigger'] = bool(micro)
    snap['one_min_ema_hold'] = bool(micro)
    snap['micro_trigger'] = bool(micro)
    snap['price_ema_aligned'] = bool(local5)
    snap['loose_pass'] = True
    _rewrite_setup_id(snap, direction, pattern)
    return True, 'V3.3_OPEN_SCALP_PASS'


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
    cap = SPREAD_CAP_PCT.get(underlying, 4.5)
    if spread_pct > cap + 1e-9:
        return False, f'spread>{cap:.1f}%', {'spread_pct': spread_pct}

    # Still blocks the old 0.01/dust problem, but allows practical low-premium scalps.
    min_premium = max(0.08, 6.0 * tick, 2.5 * spread)
    if p < min_premium:
        return False, f'premium<{min_premium:.4g} execution floor', {'spread_pct': spread_pct, 'min_premium': min_premium}

    s = _f(spot, 0)
    if s > 0 and p / s > PREMIUM_SPOT_CAP.get(underlying, 0.0125):
        return False, 'premium/spot above loose scalp cap', {'spread_pct': spread_pct}

    d = None if delta is None else abs(_f(delta, -1))
    if d is not None and d >= 0:
        if d < 0.08:
            return False, 'lottery delta<0.08', {'spread_pct': spread_pct, 'abs_delta': d}
        lo, hi = ((0.15, 0.60) if action == 'OPTION BUY' else (0.10, 0.45))
        if not (lo <= d <= hi):
            return False, f'delta outside loose {lo:.2f}-{hi:.2f}', {'spread_pct': spread_pct, 'abs_delta': d}

    if minutes_to_expiry is not None:
        mte = _f(minutes_to_expiry, -1)
        if 0 <= mte < 60:
            return False, 'expiry<60m', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}
        if 60 <= mte < 120:
            if _f(python_score, 0) < 70 or spread_pct > 3.5 + 1e-9:
                return False, 'near-expiry needs score>=70 and spread<=3.5%', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}

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
    s1 = tf.get('1m') or {}; s5 = tf.get('5m') or {}; s15 = tf.get('15m') or {}; s1h = tf.get('1h') or {}
    score = 0.0

    if _local_5m(direction, s5): score += 22
    if _micro_1m(direction, s1): score += 14
    if _tf_soft(direction, s15): score += 10
    if _tf_soft(direction, s1h): score += 8
    if _structure_ok(direction, str(snap.get('structure') or '')): score += 8
    elif snap.get('structure_relaxed'): score += 3

    adx = _f(s5.get('adx')); ratio = _di_ratio(direction, s5); rvol = _f(s5.get('rel_volume'))
    score += 8 if adx >= 25 else (6 if adx >= 18 else (3 if adx >= 12 else 0))
    score += 6 if ratio >= 1.30 else (4 if ratio >= 1.12 else (2 if ratio >= 1.02 else 0))
    score += 6 if rvol >= 1.25 else (4 if rvol >= 0.80 else (2 if rvol >= 0.35 else 0))

    daily_zone = str(snap.get('daily_zone') or '')
    five_zone = str(snap.get('five_zone') or '')
    if _pivot_supports(direction, five_zone): score += 4
    if _pivot_supports(direction, daily_zone): score += 3

    vwap_atr = _f(snap.get('vwap_distance_atr'))
    ema9_atr = _f(snap.get('ema9_distance_atr'))
    if vwap_atr <= 1.5: score += 4
    elif vwap_atr <= 2.5: score += 2
    if ema9_atr <= 0.8: score += 3

    rsi5 = _f(s5.get('rsi')); wr5 = _f(s5.get('williams_r'))
    if direction == 'BULLISH':
        if 38 <= rsi5 <= 82: score += 3
        if -95 <= wr5 <= -4: score += 2
    elif direction == 'BEARISH':
        if 18 <= rsi5 <= 62: score += 3
        if -96 <= wr5 <= -5: score += 2

    if snap.get('pattern') in {'BREAKOUT', 'RETEST'}: score += 5
    elif snap.get('pattern') == 'TREND_SCALP': score += 4
    elif snap.get('pattern') in {'OPEN_SCALP', 'COUNTERTREND_SCALP'}: score += 2

    score += max(0.0, min(10.0, _f(contract_score)))
    return int(round(max(0.0, min(100.0, score))))


def quality_label(score: int) -> str:
    if score >= ELITE_SCORE: return 'ELITE'
    if score >= STRONG_SCORE: return 'STRONG'
    if score >= MIN_ALERT_SCORE: return 'VALID'
    return 'NO TRADE'


def ai_adjustment(decision: str, confidence: int) -> int:
    d = str(decision or '').upper()
    c = int(max(0, min(100, confidence or 0)))
    if d == 'CONFIRM' and c >= 80: return 3
    if d == 'WAIT': return -2
    if d == 'REJECT': return -5 if c >= 90 else -3
    return 0
