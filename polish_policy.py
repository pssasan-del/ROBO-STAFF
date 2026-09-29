"""ROBO STAFF first Delta strategy — Fresh V4.0 PRECISION SCALP.

Design goal: high-precision trend-continuation scalps after the ultra-loose/balanced
research epochs produced too many fast stop-outs. 1m + 5m remain the execution
timeframes, but 15m trend agreement is now a HARD requirement and a strongly
opposite 1h trend is a HARD veto. The engine prefers pullback/reclaim and retest
entries instead of chasing raw breakouts.

Important: this is a research strategy, not a promise of any win rate. A 90% hit
rate is not assumed or encoded. Promotion must be based on fresh sample evidence.

SIGNAL ONLY. No order placement, modification, cancellation or broker secrets.
MASTER MIND remains a separate engine and cooldown.
"""
from __future__ import annotations

import math

POLISH_VERSION = "FRESH_V4.0_PRECISION_SCALP_2026-09-29"
MODE_REVISION = "PRECISION_PULLBACK_RETEST_2026-09-29"
MIN_ALERT_SCORE = 76
STRONG_SCORE = 84
ELITE_SCORE = 92
DAILY_RESEARCH_TARGET = 3

# Execution quality is intentionally stricter than V3.7.
SPREAD_CAP_PCT = {"BTC": 2.8, "ETH": 3.4, "GOLD": 4.2}
DAILY_SIGNAL_CAP = {"BTC": 6, "ETH": 6, "GOLD": 4}
PREMIUM_SPOT_CAP = {"BTC": 0.0120, "ETH": 0.0140, "GOLD": 0.0180}

BASE_COOLDOWN_MINUTES = 12
SUCCESS_COOLDOWN_MINUTES = 10
FAIL_COOLDOWN_MINUTES = 20
CONTRACT_COOLDOWN_MINUTES = 15
CORRELATION_WINDOW_MINUTES = 15
CORRELATION_THRESHOLD = 0.88

ACCEPTANCE_CRITERIA = {
    "min_resolved": 50,
    "preferred_resolved": 100,
    "min_calendar_days": 5,
    "min_t1_success_pct": 55.0,
    "min_profit_factor": 1.35,
    "min_expectancy_r": 0.15,
    "max_median_t1_minutes": 20.0,
    "max_p75_t1_minutes": 35.0,
    "max_fast_sl_pct": 20.0,
    "max_sl_later_t1_pct": 15.0,
    "max_stale_pct": 15.0,
    "bucket_min_n": 15,
    "bucket_min_win_pct": 45.0,
    "bucket_min_pf": 1.10,
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


def _ema_side(direction: str, state: dict) -> bool:
    px, e9, e20 = _f(state.get('price')), _f(state.get('ema9')), _f(state.get('ema20'))
    if direction == 'BULLISH':
        return px >= e9 >= e20
    return px <= e9 <= e20


def _price_action(direction: str, state: dict) -> bool:
    px, e9, vw = _f(state.get('price')), _f(state.get('ema9')), _f(state.get('vwap'))
    pdi, mdi = _f(state.get('plus_di')), _f(state.get('minus_di'))
    if direction == 'BULLISH':
        return px >= e9 and px >= vw and pdi > mdi
    return px <= e9 and px <= vw and mdi > pdi


def _strong_opposite(direction: str, state: dict) -> bool:
    opposite = 'BEARISH' if direction == 'BULLISH' else 'BULLISH'
    adx = _f(state.get('adx'))
    return adx >= 18 and _ema_side(opposite, state) and _price_action(opposite, state)


def _rsi_ok(direction: str, value) -> bool:
    v = _f(value, 50)
    return 50 <= v <= 72 if direction == 'BULLISH' else 28 <= v <= 50


def _wr_ok(direction: str, value) -> bool:
    v = _f(value, -50)
    return -72 <= v <= -12 if direction == 'BULLISH' else -88 <= v <= -28


def _structure_ok(direction: str, structure: str) -> bool:
    return (direction == 'BULLISH' and structure == 'HH/HL') or (direction == 'BEARISH' and structure == 'LH/LL')


def _structure_opposite(direction: str, structure: str) -> bool:
    return (direction == 'BULLISH' and structure == 'LH/LL') or (direction == 'BEARISH' and structure == 'HH/HL')


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
    """Require 1m + 5m directional agreement. No vote-only fallback."""
    tf = snap.get('tf') or {}
    s1, s5 = tf.get('1m') or {}, tf.get('5m') or {}
    for direction in ('BULLISH', 'BEARISH'):
        if _ema_side(direction, s5) and _ema_side(direction, s1) and _price_action(direction, s1):
            return direction
    return None


def _confirmations(direction: str, snap: dict):
    tf = snap.get('tf') or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ('1m', '5m', '15m', '1h'))
    structure = str(snap.get('structure') or '')
    five_zone = str(snap.get('five_zone') or '')
    daily_zone = str(snap.get('daily_zone') or '')
    return [
        ('15M trend aligned', _ema_side(direction, s15) and _price_action(direction, s15)),
        ('1H not opposite', not _strong_opposite(direction, s1h)),
        ('5M EMA 9/20', _ema_side(direction, s5)),
        ('1M EMA 9/20', _ema_side(direction, s1)),
        ('1M price action', _price_action(direction, s1)),
        ('RSI zone', _rsi_ok(direction, s1.get('rsi'))),
        ('Williams %R', _wr_ok(direction, s1.get('williams_r'))),
        ('5M structure', _structure_ok(direction, structure)),
        ('5M pivot side', _pivot_supports(direction, five_zone)),
        ('Daily pivot side', _pivot_supports(direction, daily_zone)),
    ]


def evaluate_entry(underlying: str, action: str, snap: dict):
    """V4 high-precision gate: trend first, pullback/retest second, micro-trigger last."""
    tf = snap.get('tf') or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ('1m', '5m', '15m', '1h'))

    direction = _local_direction(snap)
    if not direction:
        return False, 'V4 wait: 1m/5m direction not aligned'

    # Hard contextual vetoes: the exact failure seen in V3.7 must not fire again.
    if not (_ema_side(direction, s15) and _price_action(direction, s15)):
        return False, 'V4 reject: 15m trend conflict'
    if _strong_opposite(direction, s1h):
        return False, 'V4 reject: strong 1h opposite trend'

    structure = str(snap.get('structure') or '')
    if _structure_opposite(direction, structure):
        return False, f'V4 reject: opposite 5m structure {structure}'

    adx = _f(s5.get('adx'))
    rvol5 = _f(s5.get('rel_volume'))
    rvol1 = _f(s1.get('rel_volume'))
    ratio = _di_ratio(direction, s5)
    if adx < 14:
        return False, f'V4 reject: 5m ADX {adx:.1f}<14'
    if ratio < 1.08:
        return False, f'V4 reject: DI ratio {ratio:.2f}<1.08'
    if rvol5 < 0.45 and rvol1 < 0.75:
        return False, f'V4 reject: volume weak 5m/1m {rvol5:.2f}/{rvol1:.2f}'

    # Oscillator sanity: enter after reset, never at micro exhaustion.
    if not _rsi_ok(direction, s1.get('rsi')):
        return False, f"V4 reject: 1m RSI {float(s1.get('rsi') or 0):.1f} not in precision zone"
    if not _wr_ok(direction, s1.get('williams_r')):
        return False, f"V4 reject: Williams {float(s1.get('williams_r') or 0):.1f} not reset"

    vwap_atr = _f(snap.get('vwap_distance_atr'))
    ema9_atr = _f(snap.get('ema9_distance_atr'))
    room = _f(snap.get('distance_to_next_pivot_atr'))
    breakout_ext = _f(snap.get('breakout_extension_atr'))
    if vwap_atr > 2.0 or ema9_atr > 1.20:
        return False, f'V4 reject: chase {vwap_atr:.2f}/{ema9_atr:.2f} ATR'
    if room < 0.60:
        return False, f'V4 reject: target room {room:.2f}ATR<0.60'
    if breakout_ext > 1.0 and ema9_atr > 0.70:
        return False, f'V4 reject: late breakout {breakout_ext:.2f}ATR'

    # Underlying invalidation is rebuilt after the final direction is known.
    a5 = max(_f(s5.get('atr')), 1e-9)
    price = _f(s5.get('price'))
    e20 = _f(s5.get('ema20'))
    if direction == 'BULLISH':
        invalidation = min(e20, price - 0.50 * a5) - 0.10 * a5
        risk_atr = (price - invalidation) / a5
    else:
        invalidation = max(e20, price + 0.50 * a5) + 0.10 * a5
        risk_atr = (invalidation - price) / a5
    if risk_atr < 0.50 or risk_atr > 1.60:
        return False, f'V4 reject: structural risk {risk_atr:.2f}ATR outside 0.50-1.60'

    # Prefer a pullback/reclaim or retest. Pure breakout chasing is deliberately rare.
    old_pattern = str(snap.get('pattern') or '').upper()
    pivot_ok = _pivot_supports(direction, str(snap.get('five_zone') or ''))
    structure_ok = _structure_ok(direction, structure)
    one_break = bool(snap.get('one_min_breakout'))
    if ema9_atr <= 0.65 and _price_action(direction, s1):
        pattern = 'PULLBACK_RECLAIM'
    elif old_pattern == 'RETEST' and one_break:
        pattern = 'RETEST_CONFIRM'
    elif structure_ok and pivot_ok and one_break and breakout_ext <= 0.80 and rvol5 >= 0.75:
        pattern = 'BREAKOUT_RETEST'
    elif structure_ok and adx >= 20 and ratio >= 1.18 and rvol5 >= 0.80 and ema9_atr <= 0.90:
        pattern = 'TREND_RESUME'
    else:
        return False, 'V4 wait: no precision pullback/retest trigger'

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
    snap['precision_mode'] = True
    snap['one_min_trigger'] = True
    snap['one_min_ema_hold'] = True
    snap['price_ema_aligned'] = True
    snap['structural_invalidation'] = invalidation
    snap['underlying_risk_atr'] = risk_atr
    snap['major_level_context_only'] = False
    _rewrite_setup_id(snap, direction, pattern)
    return True, f'V4_PRECISION_PASS {pattern}'


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
    cap = SPREAD_CAP_PCT.get(underlying, 3.4)
    if spread_pct > cap:
        return False, f'spread>{cap:.1f}%', {'spread_pct': spread_pct}

    # Precision epoch intentionally rejects dust and spread-dominated premiums.
    min_premium = max(0.10, 6.0 * tick, 3.0 * spread)
    if p < min_premium:
        return False, f'premium<{min_premium:.4g} execution floor', {'spread_pct': spread_pct, 'min_premium': min_premium}

    s = _f(spot, 0)
    if s > 0 and p / s > PREMIUM_SPOT_CAP.get(underlying, 0.014):
        return False, 'premium/spot above V4 cap', {'spread_pct': spread_pct}

    d = None if delta is None else abs(_f(delta, -1))
    if d is not None and d >= 0:
        # V4 alerts OPTION BUY only; keep a conservative SELL band for compatibility/tests.
        lo, hi = ((0.28, 0.62) if action == 'OPTION BUY' else (0.12, 0.28))
        if not (lo <= d <= hi):
            return False, f'delta outside V4 {lo:.2f}-{hi:.2f}', {'spread_pct': spread_pct, 'abs_delta': d}

    score = _f(python_score, 100)
    if action == 'OPTION BUY' and score < MIN_ALERT_SCORE:
        return False, f'OPTION BUY requires Python score>={MIN_ALERT_SCORE}', {'spread_pct': spread_pct}
    if action == 'OPTION SELL' and score < 86:
        return False, 'OPTION SELL disabled for V4 precision alerts', {'spread_pct': spread_pct}

    if minutes_to_expiry is not None:
        mte = _f(minutes_to_expiry, -1)
        if 0 <= mte < 120:
            return False, 'expiry<120m', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}
        if 120 <= mte < 180 and (score < STRONG_SCORE or spread_pct > 2.5):
            return False, 'near-expiry needs STRONG score and spread<=2.5%', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}

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
    """Calibrated score: cannot hit 100 merely by counting weak confirmations."""
    direction = str(snap.get('direction') or '').upper()
    tf = snap.get('tf') or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ('1m', '5m', '15m', '1h'))
    score = 0.0

    # Higher timeframe context — 28 points.
    if _ema_side(direction, s15) and _price_action(direction, s15): score += 18
    if not _strong_opposite(direction, s1h):
        score += 10 if (_ema_side(direction, s1h) or _price_action(direction, s1h)) else 5

    # 5m setup quality — 25 points.
    if _ema_side(direction, s5): score += 10
    if _price_action(direction, s5): score += 5
    if _structure_ok(direction, str(snap.get('structure') or '')): score += 5
    if _pivot_supports(direction, str(snap.get('five_zone') or '')): score += 5

    # 1m trigger — 20 points.
    if _ema_side(direction, s1): score += 7
    if _price_action(direction, s1): score += 6
    if _rsi_ok(direction, s1.get('rsi')): score += 4
    if _wr_ok(direction, s1.get('williams_r')): score += 3

    # Trend strength / volume — 12 points.
    adx, ratio, rv5, rv1 = _f(s5.get('adx')), _di_ratio(direction, s5), _f(s5.get('rel_volume')), _f(s1.get('rel_volume'))
    score += 4 if adx >= 24 else (3 if adx >= 18 else 2)
    score += 4 if ratio >= 1.30 else (3 if ratio >= 1.18 else 2)
    score += 4 if max(rv5, rv1) >= 1.20 else (3 if max(rv5, rv1) >= 0.80 else 1)

    # Entry geometry — 10 points.
    ema9_atr = _f(snap.get('ema9_distance_atr'))
    room = _f(snap.get('distance_to_next_pivot_atr'))
    pattern = str(snap.get('pattern') or '')
    if pattern == 'PULLBACK_RECLAIM': score += 4
    elif pattern == 'RETEST_CONFIRM': score += 4
    elif pattern == 'BREAKOUT_RETEST': score += 3
    elif pattern == 'TREND_RESUME': score += 2
    if ema9_atr <= 0.65: score += 3
    if room >= 1.0: score += 3
    elif room >= 0.60: score += 2

    # Contract quality — 5 points from the engine's 0..10 normalized input.
    score += max(0.0, min(5.0, _f(contract_score) * 0.5))

    # Anti-inflation caps: a mediocre context can never print ELITE 100/100.
    cap = 100
    if not (_ema_side(direction, s1h) or _price_action(direction, s1h)): cap = min(cap, 89)
    if not _structure_ok(direction, str(snap.get('structure') or '')): cap = min(cap, 88)
    if max(rv5, rv1) < 0.80: cap = min(cap, 84)
    return int(round(max(0.0, min(float(cap), score))))


def quality_label(score: int) -> str:
    if score >= ELITE_SCORE: return 'ELITE'
    if score >= STRONG_SCORE: return 'STRONG'
    if score >= MIN_ALERT_SCORE: return 'VALID'
    return 'NO TRADE'


def ai_adjustment(decision: str, confidence: int) -> int:
    # AI stays second-opinion only. Deterministic V4 gates must catch HTF conflicts first.
    d = str(decision or '').upper()
    c = int(max(0, min(100, confidence or 0)))
    if d == 'CONFIRM' and c >= 80: return 2
    if d == 'WAIT': return -2
    if d == 'REJECT': return -5 if c >= 90 else -3
    return 0
