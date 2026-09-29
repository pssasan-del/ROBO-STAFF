"""ROBO STAFF first Delta strategy — Fresh V3.6 ULTRA LOOSE SCALP research policy.

Purpose: collect many real scalp samples first, then tighten from evidence.
1m + 5m local flow decide direction. 15m/1h, structure and pivots are context
only and never universal blockers. Only unusable quotes, dust contracts,
extreme chase and genuinely dead tape are hard-rejected.

SIGNAL ONLY: no order placement, modification, cancellation or broker secrets.
MASTER MIND remains a separate engine/cooldown.
"""
from __future__ import annotations

import math

POLISH_VERSION = "FRESH_V3.6_ULTRA_SCALP_2026-09-29"
MODE_REVISION = "ULTRA_LOOSE_1M5M_FLOW_2026-09-29"
MIN_ALERT_SCORE = 36
STRONG_SCORE = 55
ELITE_SCORE = 75
DAILY_RESEARCH_TARGET = 8

SPREAD_CAP_PCT = {"BTC": 5.5, "ETH": 6.5, "GOLD": 7.5}
DAILY_SIGNAL_CAP = {"BTC": 24, "ETH": 24, "GOLD": 18}
PREMIUM_SPOT_CAP = {"BTC": 0.0180, "ETH": 0.0180, "GOLD": 0.0220}

BASE_COOLDOWN_MINUTES = 3
SUCCESS_COOLDOWN_MINUTES = 2
FAIL_COOLDOWN_MINUTES = 5
CONTRACT_COOLDOWN_MINUTES = 4
CORRELATION_WINDOW_MINUTES = 3
CORRELATION_THRESHOLD = 0.96

ACCEPTANCE_CRITERIA = {
    "min_resolved": 60,
    "preferred_resolved": 100,
    "min_calendar_days": 3,
    "min_t1_success_pct": 38.0,
    "min_profit_factor": 1.10,
    "min_expectancy_r": 0.05,
    "max_median_t1_minutes": 25.0,
    "max_p75_t1_minutes": 45.0,
    "max_fast_sl_pct": 40.0,
    "max_sl_later_t1_pct": 25.0,
    "max_stale_pct": 25.0,
    "bucket_min_n": 15,
    "bucket_min_win_pct": 32.0,
    "bucket_min_pf": 0.90,
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
        return sum((px >= e9, e5 >= e9, pdi >= mdi, px >= vw * 0.9985))
    if direction == 'BEARISH':
        return sum((px <= e9, e5 <= e9, mdi >= pdi, px <= vw * 1.0015))
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
    """Ultra-loose direction: local 5m leads; 1m confirms when available."""
    tf = snap.get('tf') or {}
    s1, s5 = tf.get('1m') or {}, tf.get('5m') or {}
    rows = []
    for d in ('BULLISH','BEARISH'):
        v5, v1 = _votes(d, s5), _micro_votes(d, s1)
        rows.append({'d': d, 'v5': v5, 'v1': v1, 'score': v5 * 2 + v1})
    rows.sort(key=lambda x: x['score'], reverse=True)
    best, other = rows[0], rows[1]

    if best['v5'] >= 2 and best['v1'] >= 1 and best['score'] > other['score']:
        return best['d'], f"5m/1m flow {best['v5']}/4 + {best['v1']}/3"
    if best['v5'] >= 3 and best['score'] >= other['score'] + 1:
        return best['d'], f"5m dominant flow {best['v5']}/4; 1m early {best['v1']}/3"

    # Final research fallback: EMA5/9 slope on 5m + price side on 1m.
    p5, e5, e9 = (_f(s5.get(k)) for k in ('price','ema5','ema9'))
    p1, e1 = _f(s1.get('price')), _f(s1.get('ema9'))
    if e5 > e9 and p5 >= e9 and p1 >= e1 * 0.999:
        return 'BULLISH', '5m EMA5>EMA9 + 1m price support'
    if e5 < e9 and p5 <= e9 and p1 <= e1 * 1.001:
        return 'BEARISH', '5m EMA5<EMA9 + 1m price resistance'
    return None, f"flow unresolved B={rows[0] if rows[0]['d']=='BULLISH' else rows[1]} S={rows[0] if rows[0]['d']=='BEARISH' else rows[1]}"


def evaluate_entry(underlying: str, action: str, snap: dict):
    """Ultra-loose scalp gate. HTF/pivots enrich score but do not veto."""
    tf = snap.get('tf') or {}
    s1, s5 = tf.get('1m') or {}, tf.get('5m') or {}
    s15, s1h = tf.get('15m') or {}, tf.get('1h') or {}

    direction, why = _infer_local_direction(snap)
    if not direction:
        return False, f'V3.6 wait: {why}'
    snap['direction'] = direction
    snap['bias_reason'] = why

    v5, v1 = _votes(direction, s5), _micro_votes(direction, s1)
    adx = _f(s5.get('adx'))
    rvol = _f(s5.get('rel_volume'))
    ratio = _di_ratio(direction, s5)
    structure = str(snap.get('structure') or '')
    structure_ok = _structure_ok(direction, structure)

    # Only near-dead tape is blocked. Everything else becomes research data.
    if adx < 4 and rvol < 0.08 and not structure_ok:
        return False, f'V3.6 dead tape ADX/RVOL {adx:.1f}/{rvol:.2f}'

    vwap_atr = _f(snap.get('vwap_distance_atr'))
    ema9_atr = _f(snap.get('ema9_distance_atr'))
    breakout_ext = _f(snap.get('breakout_extension_atr'))
    if vwap_atr > 5.0 or ema9_atr > 3.0:
        return False, f'V3.6 extreme chase {vwap_atr:.2f}/{ema9_atr:.2f} ATR'

    daily_zone = str(snap.get('daily_zone') or '')
    five_zone = str(snap.get('five_zone') or '')
    pivot5 = _pivot_supports(direction, five_zone)
    pivotd = _pivot_supports(direction, daily_zone)
    htf15 = _tf_soft(direction, s15)
    htf1h = _tf_soft(direction, s1h)
    cross = snap.get('ema_cross_5m') or {}
    cross_ok = str(cross.get('side') or '').upper() == direction and cross.get('bars_ago') in (0, 1)
    old_pattern = str(snap.get('pattern') or '').upper()

    if ema9_atr <= 1.00:
        pattern = 'PULLBACK_SCALP'
    elif old_pattern == 'BREAKOUT' and breakout_ext <= 1.75:
        pattern = 'BREAKOUT_SCALP'
    elif old_pattern == 'RETEST':
        pattern = 'RETEST_SCALP'
    elif v1 >= 2:
        pattern = 'MICRO_SCALP'
    elif adx >= 9 or rvol >= 0.20 or ratio >= 1.00 or cross_ok:
        pattern = 'MOMENTUM_SCALP'
    else:
        pattern = 'FLOW_SCALP'

    snap['pattern'] = pattern
    snap['scalp_mode'] = True
    snap['momentum_mode'] = pattern in {'MOMENTUM_SCALP','BREAKOUT_SCALP','MICRO_SCALP'}
    snap['structure_relaxed'] = not structure_ok
    snap['one_min_trigger'] = v1 >= 1
    snap['one_min_ema_hold'] = v1 >= 1
    snap['micro_trigger'] = v1 >= 1
    snap['price_ema_aligned'] = v5 >= 2
    snap['local_5m_votes'] = v5
    snap['local_1m_votes'] = v1
    snap['htf15_context'] = htf15
    snap['htf1h_context'] = htf1h
    snap['pivot5_context'] = pivot5
    snap['pivotd_context'] = pivotd
    snap['major_level_context_only'] = True
    snap['ultra_loose_research'] = True
    _rewrite_setup_id(snap, direction, pattern)
    return True, 'V3.6_ULTRA_SCALP_PASS'


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
    cap = SPREAD_CAP_PCT.get(underlying, 6.5)
    if spread_pct > cap:
        return False, f'spread>{cap:.1f}%', {'spread_pct': spread_pct}

    min_premium = max(0.05, 3.0 * tick, 1.5 * spread)
    if p < min_premium:
        return False, f'premium<{min_premium:.4g} floor', {'spread_pct': spread_pct, 'min_premium': min_premium}

    s = _f(spot, 0)
    if s > 0 and p / s > PREMIUM_SPOT_CAP.get(underlying, 0.018):
        return False, 'premium/spot above V3.6 cap', {'spread_pct': spread_pct}

    d = None if delta is None else abs(_f(delta, -1))
    if d is not None and d >= 0:
        if d < 0.03:
            return False, 'lottery delta<0.03', {'spread_pct': spread_pct, 'abs_delta': d}
        lo, hi = ((0.07, 0.75) if action == 'OPTION BUY' else (0.05, 0.60))
        if not (lo <= d <= hi):
            return False, f'delta outside V3.6 {lo:.2f}-{hi:.2f}', {'spread_pct': spread_pct, 'abs_delta': d}

    score = _f(python_score, 100)
    if action == 'OPTION BUY' and score < 40:
        return False, 'OPTION BUY requires Python score>=40', {'spread_pct': spread_pct}
    if action == 'OPTION SELL' and score < 36:
        return False, 'OPTION SELL requires Python score>=36', {'spread_pct': spread_pct}

    if minutes_to_expiry is not None:
        mte = _f(minutes_to_expiry, -1)
        if 0 <= mte < 30:
            return False, 'expiry<30m', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}
        if 30 <= mte < 60 and (score < 48 or spread_pct > 6.0):
            return False, 'near-expiry needs score>=48 and spread<=6%', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}

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
    score = 10.0 + v5 * 5.0 + v1 * 4.0

    structure_ok = _structure_ok(direction, str(snap.get('structure') or ''))
    score += 5 if structure_ok else 1

    adx, ratio, rvol = _f(s5.get('adx')), _di_ratio(direction, s5), _f(s5.get('rel_volume'))
    score += 7 if adx >= 24 else (5 if adx >= 14 else (3 if adx >= 7 else 1))
    score += 6 if ratio >= 1.25 else (4 if ratio >= 1.05 else 2)
    score += 6 if rvol >= 1.25 else (4 if rvol >= 0.60 else (2 if rvol >= 0.15 else 0))

    if _pivot_supports(direction, str(snap.get('five_zone') or '')): score += 3
    if _pivot_supports(direction, str(snap.get('daily_zone') or '')): score += 2
    if _tf_soft(direction, s15): score += 2
    if _tf_soft(direction, s1h): score += 1

    vwap_atr, ema9_atr = _f(snap.get('vwap_distance_atr')), _f(snap.get('ema9_distance_atr'))
    if vwap_atr <= 2.5: score += 3
    if ema9_atr <= 1.5: score += 3

    pattern = str(snap.get('pattern') or '')
    if pattern == 'PULLBACK_SCALP': score += 6
    elif pattern in {'RETEST_SCALP','BREAKOUT_SCALP'}: score += 5
    elif pattern in {'MICRO_SCALP','MOMENTUM_SCALP'}: score += 4
    elif pattern == 'FLOW_SCALP': score += 2

    score += max(0.0, min(10.0, _f(contract_score)))
    return int(round(max(0.0, min(100.0, score))))


def quality_label(score: int) -> str:
    if score >= ELITE_SCORE: return 'ELITE'
    if score >= STRONG_SCORE: return 'STRONG'
    if score >= MIN_ALERT_SCORE: return 'VALID'
    return 'NO TRADE'


def ai_adjustment(decision: str, confidence: int) -> int:
    # AI remains non-blocking; deterministic signal still owns the decision.
    d = str(decision or '').upper()
    c = int(max(0, min(100, confidence or 0)))
    if d == 'CONFIRM' and c >= 80: return 2
    if d == 'WAIT': return -1
    if d == 'REJECT': return -3 if c >= 90 else -2
    return 0
