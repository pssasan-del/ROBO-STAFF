"""ROBO STAFF Delta strategy — Fresh V4.2 LIVE-READY SCALP.

V4.2 tightens V4.1 for real-account use while keeping local-flow authority:
- Higher minimum alert score (live money filter)
- Tighter spread / premium / daily caps
- Slightly longer cooldowns after fails
- Live path is gated separately in delta_live_trading.py; this file only
  decides signal quality. MASTER MIND remains separate and untouched.
"""
from __future__ import annotations

import math

POLISH_VERSION = "FRESH_V4.2_LIVE_READY_SCALP_2026-09-30"
MODE_REVISION = "LIVE_READY_LOCAL_FLOW_2026-09-30"
MIN_ALERT_SCORE = 58
STRONG_SCORE = 70
ELITE_SCORE = 84
DAILY_RESEARCH_TARGET = 5

SPREAD_CAP_PCT = {"BTC": 3.8, "ETH": 4.5, "GOLD": 6.5}
DAILY_SIGNAL_CAP = {"BTC": 12, "ETH": 12, "GOLD": 8}
PREMIUM_SPOT_CAP = {"BTC": 0.022, "ETH": 0.026, "GOLD": 0.030}

BASE_COOLDOWN_MINUTES = 5
SUCCESS_COOLDOWN_MINUTES = 4
FAIL_COOLDOWN_MINUTES = 9
CONTRACT_COOLDOWN_MINUTES = 8
CORRELATION_WINDOW_MINUTES = 12
CORRELATION_THRESHOLD = 0.92

ACCEPTANCE_CRITERIA = {
    "min_resolved": 40,
    "preferred_resolved": 80,
    "min_calendar_days": 4,
    "min_t1_success_pct": 48.0,
    "min_profit_factor": 1.25,
    "min_expectancy_r": 0.08,
    "max_median_t1_minutes": 18.0,
    "max_p75_t1_minutes": 30.0,
    "max_fast_sl_pct": 25.0,
    "max_sl_later_t1_pct": 18.0,
    "max_stale_pct": 15.0,
    "bucket_min_n": 12,
    "bucket_min_win_pct": 42.0,
    "bucket_min_pf": 1.05,
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


def _ema_side(direction: str, state: dict) -> bool:
    px, e5, e9, e20 = (_f(state.get(k)) for k in ('price','ema5','ema9','ema20'))
    if direction == 'BULLISH':
        return px >= e9 and e5 >= e9 and e9 >= e20
    return px <= e9 and e5 <= e9 and e9 <= e20


def _price_action(direction: str, state: dict) -> bool:
    px, e9, vw = _f(state.get('price')), _f(state.get('ema9')), _f(state.get('vwap'))
    pdi, mdi = _f(state.get('plus_di')), _f(state.get('minus_di'))
    if direction == 'BULLISH':
        return px >= e9 and px >= vw and pdi >= mdi * 0.90
    return px <= e9 and px <= vw and mdi >= pdi * 0.90


def _votes(direction: str, state: dict) -> int:
    px, e5, e9, e20, vw = (_f(state.get(k)) for k in ('price','ema5','ema9','ema20','vwap'))
    pdi, mdi = _f(state.get('plus_di')), _f(state.get('minus_di'))
    if direction == 'BULLISH':
        checks = (px >= e9, e5 >= e9, e9 >= e20, px >= vw, pdi >= mdi * 0.90)
    else:
        checks = (px <= e9, e5 <= e9, e9 <= e20, px <= vw, mdi >= pdi * 0.90)
    return sum(bool(x) for x in checks)


def _strong_opposite(direction: str, state: dict) -> bool:
    opposite = 'BEARISH' if direction == 'BULLISH' else 'BULLISH'
    return _f(state.get('adx')) >= 24 and _votes(opposite, state) >= 4


def _rsi_supports(direction: str, value) -> bool:
    v = _f(value, 50)
    return v >= 48 if direction == 'BULLISH' else v <= 52


def _wr_supports(direction: str, value) -> bool:
    v = _f(value, -50)
    return v >= -62 if direction == 'BULLISH' else v <= -38


def _structure_ok(direction: str, structure: str) -> bool:
    return (direction == 'BULLISH' and structure == 'HH/HL') or (direction == 'BEARISH' and structure == 'LH/LL')


def _pivot_supports(direction: str, zone: str) -> bool:
    if direction == 'BULLISH':
        return zone in {'PIVOT_TO_R1', 'ABOVE_R1'}
    return zone in {'S1_TO_PIVOT', 'BELOW_S1'}


def _rewrite_setup_id(snap: dict, direction: str, pattern: str):
    sid = str(snap.get('setup_id') or '')
    parts = sid.split(':')
    if len(parts) >= 4:
        parts[1], parts[2] = direction, pattern
        snap['setup_id'] = ':'.join(parts)
    else:
        snap['setup_id'] = f"{snap.get('symbol','UNK')}:{direction}:{pattern}:{sid}"


def _local_direction(snap: dict):
    tf = snap.get('tf') or {}
    s1, s5 = tf.get('1m') or {}, tf.get('5m') or {}
    b5, r5 = _votes('BULLISH', s5), _votes('BEARISH', s5)
    b1, r1 = _votes('BULLISH', s1), _votes('BEARISH', s1)
    bull = b5 >= 3 and b1 >= 2 and (b5 + b1) >= (r5 + r1 + 2)
    bear = r5 >= 3 and r1 >= 2 and (r5 + r1) >= (b5 + b1 + 2)
    if bull and not bear:
        return 'BULLISH'
    if bear and not bull:
        return 'BEARISH'
    # Frequency fallback: use fast EMA flow when votes are close but both execution
    # timeframes still point the same way.
    if _f(s5.get('ema5')) >= _f(s5.get('ema9')) and _f(s1.get('ema5')) >= _f(s1.get('ema9')) and _f(s5.get('price')) >= _f(s5.get('ema9')):
        return 'BULLISH'
    if _f(s5.get('ema5')) <= _f(s5.get('ema9')) and _f(s1.get('ema5')) <= _f(s1.get('ema9')) and _f(s5.get('price')) <= _f(s5.get('ema9')):
        return 'BEARISH'
    return None


def _confirmations(direction: str, snap: dict):
    tf = snap.get('tf') or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ('1m','5m','15m','1h'))
    return [
        ('5M local flow', _votes(direction, s5) >= 3),
        ('1M local flow', _votes(direction, s1) >= 3),
        ('15M context', _votes(direction, s15) >= 3),
        ('1H not strongly opposite', not _strong_opposite(direction, s1h)),
        ('DI supports', _di_ratio(direction, s5) >= 1.00),
        ('Volume active', max(_f(s5.get('rel_volume')), _f(s1.get('rel_volume'))) >= 0.45),
        ('RSI supports', _rsi_supports(direction, s1.get('rsi'))),
        ('Williams %R supports', _wr_supports(direction, s1.get('williams_r'))),
        ('5M structure', _structure_ok(direction, str(snap.get('structure') or ''))),
        ('5M pivot side', _pivot_supports(direction, str(snap.get('five_zone') or ''))),
    ]


def evaluate_entry(underlying: str, action: str, snap: dict):
    """V4.1 frequency-first local-flow gate for signal research."""
    tf = snap.get('tf') or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ('1m','5m','15m','1h'))
    direction = _local_direction(snap)
    if not direction:
        return False, 'V4.1 wait: no common 1m/5m flow'

    # Only severe higher-timeframe conflict is a veto. One conflicting HTF alone is context.
    if _strong_opposite(direction, s15) and _strong_opposite(direction, s1h):
        return False, 'V4.1 reject: 15m+1h both strongly opposite'

    adx = _f(s5.get('adx'))
    rv5, rv1 = _f(s5.get('rel_volume')), _f(s1.get('rel_volume'))
    if adx < 7 and max(rv5, rv1) < 0.25:
        return False, f'V4.1 reject: dead tape ADX {adx:.1f} RVOL {max(rv5,rv1):.2f}'

    vwap_atr = _f(snap.get('vwap_distance_atr'))
    ema9_atr = _f(snap.get('ema9_distance_atr'))
    if vwap_atr > 4.0 or ema9_atr > 2.5:
        return False, f'V4.1 reject: extreme chase {vwap_atr:.2f}/{ema9_atr:.2f} ATR'

    a5 = max(_f(s5.get('atr')), max(_f(s5.get('price')) * 0.0002, 1e-9))
    price = _f(s5.get('price'))
    risk_atr = 0.95
    invalidation = price - risk_atr * a5 if direction == 'BULLISH' else price + risk_atr * a5

    structure_ok = _structure_ok(direction, str(snap.get('structure') or ''))
    pivot_ok = _pivot_supports(direction, str(snap.get('five_zone') or ''))
    ratio = _di_ratio(direction, s5)
    one_break = bool(snap.get('one_min_breakout'))

    if ema9_atr <= 0.80:
        pattern = 'PULLBACK_FLOW'
    elif one_break:
        pattern = 'BREAKOUT_FLOW'
    elif structure_ok:
        pattern = 'STRUCTURE_FLOW'
    elif adx >= 14 or ratio >= 1.05 or max(rv5, rv1) >= 0.70:
        pattern = 'MOMENTUM_FLOW'
    else:
        pattern = 'MICRO_FLOW'

    confirmations = _confirmations(direction, snap)
    passed = [name for name, ok in confirmations if ok]
    failed = [name for name, ok in confirmations if not ok]
    snap['direction'] = direction
    snap['pattern'] = pattern
    snap['confirmation_count'] = len(passed)
    snap['confirmation_total'] = len(confirmations)
    snap['confirmations_passed'] = passed
    snap['confirmations_failed'] = failed
    snap['scalp_mode'] = True
    snap['precision_mode'] = False
    snap['active_flow_mode'] = True
    snap['one_min_trigger'] = True
    snap['one_min_ema_hold'] = True
    snap['price_ema_aligned'] = True
    snap['structural_invalidation'] = invalidation
    snap['underlying_risk_atr'] = risk_atr
    snap['major_level_context_only'] = True
    snap['flow_structure_ok'] = structure_ok
    snap['flow_pivot_ok'] = pivot_ok
    _rewrite_setup_id(snap, direction, pattern)
    return True, f'V4.1_ACTIVE_PASS {pattern}'


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
    cap = SPREAD_CAP_PCT.get(underlying, 6.0)
    if spread_pct > cap:
        return False, f'spread>{cap:.1f}%', {'spread_pct': spread_pct}

    min_premium = max(0.05, 3.0 * tick, 1.25 * spread)
    if p < min_premium:
        return False, f'premium<{min_premium:.4g} floor', {'spread_pct': spread_pct, 'min_premium': min_premium}

    s = _f(spot, 0)
    if s > 0 and p / s > PREMIUM_SPOT_CAP.get(underlying, 0.03):
        return False, 'premium/spot above V4.1 cap', {'spread_pct': spread_pct}

    d = None if delta is None else abs(_f(delta, -1))
    if d is not None and d >= 0:
        lo, hi = ((0.12, 0.80) if action == 'OPTION BUY' else (0.08, 0.40))
        if not (lo <= d <= hi):
            return False, f'delta outside V4.1 {lo:.2f}-{hi:.2f}', {'spread_pct': spread_pct, 'abs_delta': d}

    score = _f(python_score, 100)
    if score < MIN_ALERT_SCORE:
        return False, f'Python score<{MIN_ALERT_SCORE}', {'spread_pct': spread_pct}

    if minutes_to_expiry is not None:
        mte = _f(minutes_to_expiry, -1)
        if 0 <= mte < 30:
            return False, 'expiry<30m', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}

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
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ('1m','5m','15m','1h'))
    score = 0.0

    # Local flow carries most of the score so genuine scalps are not blocked by HTF lag.
    score += min(24, _votes(direction, s5) * 4.8)
    score += min(22, _votes(direction, s1) * 4.4)
    if _votes(direction, s15) >= 3: score += 8
    if not _strong_opposite(direction, s1h): score += 5

    adx, ratio = _f(s5.get('adx')), _di_ratio(direction, s5)
    rv = max(_f(s5.get('rel_volume')), _f(s1.get('rel_volume')))
    score += 5 if adx >= 20 else (4 if adx >= 14 else (2 if adx >= 8 else 0))
    score += 5 if ratio >= 1.20 else (4 if ratio >= 1.05 else 2)
    score += 5 if rv >= 1.0 else (4 if rv >= 0.65 else (2 if rv >= 0.35 else 0))

    if _rsi_supports(direction, s1.get('rsi')): score += 4
    if _wr_supports(direction, s1.get('williams_r')): score += 4
    if _structure_ok(direction, str(snap.get('structure') or '')): score += 4
    if _pivot_supports(direction, str(snap.get('five_zone') or '')): score += 4

    pattern = str(snap.get('pattern') or '')
    if pattern == 'PULLBACK_FLOW': score += 5
    elif pattern in {'BREAKOUT_FLOW','STRUCTURE_FLOW'}: score += 4
    elif pattern == 'MOMENTUM_FLOW': score += 3
    else: score += 2

    score += max(0.0, min(5.0, _f(contract_score) * 0.5))
    return int(round(max(0.0, min(100.0, score))))


def quality_label(score: int) -> str:
    if score >= ELITE_SCORE: return 'ELITE'
    if score >= STRONG_SCORE: return 'STRONG'
    if score >= MIN_ALERT_SCORE: return 'VALID'
    return 'NO TRADE'


def ai_adjustment(decision: str, confidence: int) -> int:
    d = str(decision or '').upper()
    c = int(max(0, min(100, confidence or 0)))
    if d == 'CONFIRM' and c >= 80: return 2
    if d == 'WAIT': return -1
    if d == 'REJECT': return -3 if c >= 90 else -2
    return 0
