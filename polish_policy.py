"""ROBO STAFF first Delta strategy — Fresh V3.4 PULLBACK/RECLAIM research policy.

The V3.3 OPEN_SCALP path produced low-quality early samples. V3.4 changes the
entry model instead of simply tightening/loosening the same gates:
- local 5m trend + 1m confirmation are both required;
- entries prefer pullback/reclaim, retest confirmation, or controlled trend resume;
- blind OPEN_SCALP is removed;
- at least one structural/pivot/cross/15m anchor is required;
- higher timeframes remain context/veto rather than universal blockers;
- option BUY requires a higher deterministic score than option SELL;
- quote/dust/chase/expiry protections remain;
- SIGNAL ONLY: this module has no execution functions.

The separate MASTER MIND module is intentionally untouched.
"""
from __future__ import annotations

import math

POLISH_VERSION = "FRESH_V3.4_RECLAIM_2026-09-29"
MODE_REVISION = "PULLBACK_RECLAIM_SCALP_2026-09-29"
MIN_ALERT_SCORE = 60
STRONG_SCORE = 76
ELITE_SCORE = 90
DAILY_RESEARCH_TARGET = 3

SPREAD_CAP_PCT = {"BTC": 3.0, "ETH": 4.0, "GOLD": 5.0}
DAILY_SIGNAL_CAP = {"BTC": 8, "ETH": 8, "GOLD": 6}
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
    "min_t1_success_pct": 42.0,
    "min_profit_factor": 1.20,
    "min_expectancy_r": 0.10,
    "max_median_t1_minutes": 25.0,
    "max_p75_t1_minutes": 40.0,
    "max_fast_sl_pct": 30.0,
    "max_sl_later_t1_pct": 20.0,
    "max_stale_pct": 20.0,
    "bucket_min_n": 12,
    "bucket_min_win_pct": 35.0,
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
    return pdi / max(mdi, 1.0) if direction == 'BULLISH' else mdi / max(pdi, 1.0)


def _trend5(direction: str, s5: dict) -> bool:
    px, e5, e9, e20, vw = (_f(s5.get(k)) for k in ('price','ema5','ema9','ema20','vwap'))
    pdi, mdi = _f(s5.get('plus_di')), _f(s5.get('minus_di'))
    if direction == 'BULLISH':
        return px >= e9 and e5 >= e9 and e9 >= e20 and pdi >= mdi and px >= vw * 0.998
    if direction == 'BEARISH':
        return px <= e9 and e5 <= e9 and e9 <= e20 and mdi >= pdi and px <= vw * 1.002
    return False


def _micro1(direction: str, s1: dict) -> bool:
    px, e5, e9 = (_f(s1.get(k)) for k in ('price','ema5','ema9'))
    pdi, mdi, adx = _f(s1.get('plus_di')), _f(s1.get('minus_di')), _f(s1.get('adx'))
    if direction == 'BULLISH':
        return px >= e9 and e5 >= e9 and pdi >= mdi and adx >= 5
    if direction == 'BEARISH':
        return px <= e9 and e5 <= e9 and mdi >= pdi and adx >= 5
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
    px, e5, e9, e20 = (_f(state.get(k)) for k in ('price','ema5','ema9','ema20'))
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


def _infer_direction(snap: dict):
    tf = snap.get('tf') or {}
    s1 = tf.get('1m') or {}; s5 = tf.get('5m') or {}; s15 = tf.get('15m') or {}
    for d in ('BULLISH','BEARISH'):
        if _trend5(d, s5) and _micro1(d, s1):
            return d, '5m trend + 1m reclaim confirmation'
    for d in ('BULLISH','BEARISH'):
        if _trend5(d, s5) and _tf_soft(d, s15):
            return d, '5m trend + 15m context; awaiting 1m confirmation'
    return None, 'no coherent 5m trend'


def evaluate_entry(underlying: str, action: str, snap: dict):
    """V3.4 entry gate: pullback/reclaim first, no blind OPEN_SCALP."""
    underlying = str(underlying or '').upper()
    tf = snap.get('tf') or {}
    s1 = tf.get('1m') or {}; s5 = tf.get('5m') or {}; s15 = tf.get('15m') or {}; s1h = tf.get('1h') or {}

    direction = str(snap.get('direction') or '').upper()
    if direction not in {'BULLISH','BEARISH'} or not _trend5(direction, s5):
        inferred, reason = _infer_direction(snap)
        if not inferred:
            return False, f'V3.4 no trend: {reason}'
        direction = inferred
        snap['direction'] = direction
        snap['bias_reason'] = reason

    local5 = _trend5(direction, s5)
    micro = _micro1(direction, s1)
    if not local5:
        return False, 'V3.4 5m trend alignment failed'
    if not micro:
        return False, 'V3.4 waiting for 1m reclaim/continuation confirmation'

    adx = _f(s5.get('adx'))
    rvol = _f(s5.get('rel_volume'))
    ratio = _di_ratio(direction, s5)
    structure = str(snap.get('structure') or '')
    structure_ok = _structure_ok(direction, structure)
    daily_zone = str(snap.get('daily_zone') or '')
    five_zone = str(snap.get('five_zone') or '')
    pivot5 = _pivot_supports(direction, five_zone)
    pivotd = _pivot_supports(direction, daily_zone)

    if adx < 11 and rvol < 0.30:
        return False, f'V3.4 dead tape ADX/RVOL {adx:.1f}/{rvol:.2f}'
    if ratio < 1.05 and not structure_ok:
        return False, f'V3.4 DI edge too weak {ratio:.2f}'

    vwap_atr = _f(snap.get('vwap_distance_atr'))
    ema9_atr = _f(snap.get('ema9_distance_atr'))
    breakout_ext = _f(snap.get('breakout_extension_atr'))
    if vwap_atr > 2.50 or ema9_atr > 1.35:
        return False, f'V3.4 chase reject VWAP/EMA9 {vwap_atr:.2f}/{ema9_atr:.2f} ATR'

    both_opposite = _tf_strong_opposite(direction, s15) and _tf_strong_opposite(direction, s1h)
    if both_opposite and not (adx >= 22 and ratio >= 1.20 and rvol >= 0.65):
        return False, 'V3.4 both 15m/1h strongly opposite'

    rsi5, wr5 = _f(s5.get('rsi')), _f(s5.get('williams_r'))
    if direction == 'BULLISH' and (rsi5 > 88 or wr5 > -1):
        return False, 'V3.4 bullish exhaustion'
    if direction == 'BEARISH' and (rsi5 < 12 or wr5 < -99):
        return False, 'V3.4 bearish exhaustion'

    cross = snap.get('ema_cross_5m') or {}
    cross_ok = str(cross.get('side') or '').upper() == direction and cross.get('bars_ago') in (0,1)
    old_pattern = str(snap.get('pattern') or '').upper()
    htf15 = _tf_soft(direction, s15)
    anchor_count = sum(bool(x) for x in (structure_ok, pivot5, pivotd, cross_ok, htf15))
    if anchor_count < 1:
        return False, 'V3.4 no structural/pivot/HTF anchor'

    # Pattern priority deliberately favors entries after a controlled pullback.
    if ema9_atr <= 0.65:
        pattern = 'PULLBACK_RECLAIM'
    elif old_pattern == 'RETEST' and cross_ok:
        pattern = 'RETEST_CONFIRM'
    elif old_pattern == 'BREAKOUT' and cross_ok and breakout_ext <= 0.75:
        pattern = 'BREAKOUT_CONFIRM'
    elif adx >= 15 and ratio >= 1.10 and rvol >= 0.40 and ema9_atr <= 1.00:
        pattern = 'TREND_RESUME'
    else:
        return False, (
            f'V3.4 wait for pullback/retest (EMA9 {ema9_atr:.2f}ATR, '
            f'ADX {adx:.1f}, DI {ratio:.2f}, RVOL {rvol:.2f})'
        )

    snap['pattern'] = pattern
    snap['scalp_mode'] = True
    snap['momentum_mode'] = pattern in {'BREAKOUT_CONFIRM','TREND_RESUME'}
    snap['structure_relaxed'] = not structure_ok
    snap['one_min_trigger'] = True
    snap['one_min_ema_hold'] = True
    snap['micro_trigger'] = True
    snap['price_ema_aligned'] = True
    snap['reclaim_mode'] = pattern in {'PULLBACK_RECLAIM','RETEST_CONFIRM'}
    snap['anchor_count'] = anchor_count
    _rewrite_setup_id(snap, direction, pattern)
    return True, 'V3.4_PULLBACK_RECLAIM_PASS'


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
    cap = SPREAD_CAP_PCT.get(underlying, 4.0)
    if spread_pct > cap + 1e-9:
        return False, f'spread>{cap:.1f}%', {'spread_pct': spread_pct}
    if action == 'OPTION BUY' and spread_pct > min(cap, 3.5):
        return False, 'OPTION BUY spread too wide for scalp', {'spread_pct': spread_pct}

    min_premium = max(0.08, 6.0 * tick, 2.5 * spread)
    if p < min_premium:
        return False, f'premium<{min_premium:.4g} execution floor', {'spread_pct': spread_pct, 'min_premium': min_premium}

    s = _f(spot, 0)
    if s > 0 and p / s > PREMIUM_SPOT_CAP.get(underlying, 0.0125):
        return False, 'premium/spot above V3.4 cap', {'spread_pct': spread_pct}

    d = None if delta is None else abs(_f(delta, -1))
    if d is not None and d >= 0:
        if d < 0.08:
            return False, 'lottery delta<0.08', {'spread_pct': spread_pct, 'abs_delta': d}
        lo, hi = ((0.18, 0.55) if action == 'OPTION BUY' else (0.10, 0.45))
        if not (lo <= d <= hi):
            return False, f'delta outside V3.4 {lo:.2f}-{hi:.2f}', {'spread_pct': spread_pct, 'abs_delta': d}

    score = _f(python_score, 100)
    # The engine first probes with score=100, then re-checks with the real score.
    # On the second pass, option buying needs stronger setup quality than selling.
    if action == 'OPTION BUY' and score < 66:
        return False, 'OPTION BUY requires Python score>=66', {'spread_pct': spread_pct}
    if action == 'OPTION SELL' and score < 58:
        return False, 'OPTION SELL requires Python score>=58', {'spread_pct': spread_pct}

    if minutes_to_expiry is not None:
        mte = _f(minutes_to_expiry, -1)
        if 0 <= mte < 60:
            return False, 'expiry<60m', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}
        if 60 <= mte < 120 and (score < 72 or spread_pct > 3.0):
            return False, 'near-expiry needs score>=72 and spread<=3%', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}

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

    if _trend5(direction, s5): score += 20
    if _micro1(direction, s1): score += 16
    if _tf_soft(direction, s15): score += 9
    if _tf_soft(direction, s1h): score += 6
    if _structure_ok(direction, str(snap.get('structure') or '')): score += 7
    elif snap.get('structure_relaxed'): score += 2

    adx, rvol, ratio = _f(s5.get('adx')), _f(s5.get('rel_volume')), _di_ratio(direction, s5)
    score += 8 if adx >= 24 else (6 if adx >= 18 else (3 if adx >= 11 else 0))
    score += 6 if ratio >= 1.30 else (4 if ratio >= 1.12 else (2 if ratio >= 1.05 else 0))
    score += 6 if rvol >= 1.20 else (4 if rvol >= 0.70 else (2 if rvol >= 0.30 else 0))

    if _pivot_supports(direction, str(snap.get('five_zone') or '')): score += 4
    if _pivot_supports(direction, str(snap.get('daily_zone') or '')): score += 3

    ema9_atr = _f(snap.get('ema9_distance_atr'))
    vwap_atr = _f(snap.get('vwap_distance_atr'))
    if ema9_atr <= 0.65: score += 6
    elif ema9_atr <= 1.0: score += 3
    if vwap_atr <= 1.5: score += 4
    elif vwap_atr <= 2.2: score += 2

    pattern = str(snap.get('pattern') or '')
    if pattern == 'PULLBACK_RECLAIM': score += 10
    elif pattern == 'RETEST_CONFIRM': score += 9
    elif pattern == 'BREAKOUT_CONFIRM': score += 7
    elif pattern == 'TREND_RESUME': score += 5

    rsi5, wr5 = _f(s5.get('rsi')), _f(s5.get('williams_r'))
    if direction == 'BULLISH':
        if 38 <= rsi5 <= 78: score += 3
        if -92 <= wr5 <= -5: score += 2
    elif direction == 'BEARISH':
        if 22 <= rsi5 <= 62: score += 3
        if -96 <= wr5 <= -8: score += 2

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
