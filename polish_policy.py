"""ROBO STAFF V5 CLEAN CONFLUENCE SCALP.

Fresh signal-only policy built after the V4.3 sample showed poor T1 conversion.
The engine deliberately prioritises 1m/5m agreement, a safe 15m context, usable
momentum, and non-chased entries. MASTER MIND is separate and untouched.
No private/order APIs are used here.
"""
from __future__ import annotations

import math

POLISH_VERSION = "FRESH_V5_CLEAN_CONFLUENCE_2026-10-02"
MODE_REVISION = "CLEAN_1M_5M_15M_CONFLUENCE_2026-10-02"
MIN_ALERT_SCORE = 64
STRONG_SCORE = 76
ELITE_SCORE = 88
DAILY_RESEARCH_TARGET = 8

SPREAD_CAP_PCT = {"BTC": 4.0, "ETH": 5.0, "GOLD": 6.5}
DAILY_SIGNAL_CAP = {"BTC": 50, "ETH": 50, "GOLD": 30}
PREMIUM_SPOT_CAP = {"BTC": 0.022, "ETH": 0.028, "GOLD": 0.032}

BASE_COOLDOWN_MINUTES = 5
SUCCESS_COOLDOWN_MINUTES = 4
FAIL_COOLDOWN_MINUTES = 8
CONTRACT_COOLDOWN_MINUTES = 8
CORRELATION_WINDOW_MINUTES = 10
CORRELATION_THRESHOLD = 0.95

ACCEPTANCE_CRITERIA = {
    "min_resolved": 40,
    "preferred_resolved": 80,
    "min_calendar_days": 4,
    "min_t1_success_pct": 45.0,
    "min_profit_factor": 1.20,
    "min_expectancy_r": 0.05,
    "max_median_t1_minutes": 25.0,
    "max_p75_t1_minutes": 40.0,
    "max_fast_sl_pct": 25.0,
    "max_sl_later_t1_pct": 18.0,
    "max_stale_pct": 20.0,
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


def _votes(direction: str, state: dict) -> int:
    px, e5, e9, e20, vw = (_f(state.get(k)) for k in ('price','ema5','ema9','ema20','vwap'))
    pdi, mdi = _f(state.get('plus_di')), _f(state.get('minus_di'))
    if direction == 'BULLISH':
        checks = (px >= e9, e5 >= e9, e9 >= e20, px >= vw, pdi >= mdi)
    else:
        checks = (px <= e9, e5 <= e9, e9 <= e20, px <= vw, mdi >= pdi)
    return sum(bool(x) for x in checks)


def _di_ratio(direction: str, state: dict) -> float:
    pdi, mdi = _f(state.get('plus_di')), _f(state.get('minus_di'))
    return pdi / max(mdi, 1.0) if direction == 'BULLISH' else mdi / max(pdi, 1.0)


def _strong_opposite(direction: str, state: dict, adx_floor=22.0, votes=4) -> bool:
    opposite = 'BEARISH' if direction == 'BULLISH' else 'BULLISH'
    return _f(state.get('adx')) >= adx_floor and _votes(opposite, state) >= votes


def _ema_aligned(direction: str, state: dict) -> bool:
    px, e5, e9 = (_f(state.get(k)) for k in ('price','ema5','ema9'))
    return (px >= e5 >= e9) if direction == 'BULLISH' else (px <= e5 <= e9)


def _rsi_ok(direction: str, value) -> bool:
    x = _f(value, 50)
    return 50 <= x <= 72 if direction == 'BULLISH' else 28 <= x <= 50


def _wr_ok(direction: str, value) -> bool:
    x = _f(value, -50)
    return -70 <= x <= -15 if direction == 'BULLISH' else -85 <= x <= -30


def _structure_ok(direction: str, structure: str) -> bool:
    return (direction == 'BULLISH' and structure == 'HH/HL') or (direction == 'BEARISH' and structure == 'LH/LL')


def _pivot_ok(direction: str, zone: str) -> bool:
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
    b1, r1 = _votes('BULLISH', s1), _votes('BEARISH', s1)
    b5, r5 = _votes('BULLISH', s5), _votes('BEARISH', s5)
    bull = b5 >= 4 and b1 >= 3 and (b5 + b1) >= (r5 + r1 + 2)
    bear = r5 >= 4 and r1 >= 3 and (r5 + r1) >= (b5 + b1 + 2)
    if bull and not bear:
        return 'BULLISH'
    if bear and not bull:
        return 'BEARISH'
    return None


def _confirmations(direction: str, snap: dict):
    tf = snap.get('tf') or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ('1m','5m','15m','1h'))
    return [
        ('5M flow 4/5+', _votes(direction, s5) >= 4),
        ('1M timing 3/5+', _votes(direction, s1) >= 3),
        ('15M safe context', not _strong_opposite(direction, s15)),
        ('1H no extreme conflict', not _strong_opposite(direction, s1h, 30, 5)),
        ('5M ADX/RVOL active', _f(s5.get('adx')) >= 12 or max(_f(s5.get('rel_volume')), _f(s1.get('rel_volume'))) >= 0.65),
        ('DI ratio >= 1.08', _di_ratio(direction, s5) >= 1.08),
        ('RSI controlled', _rsi_ok(direction, s1.get('rsi'))),
        ('Williams %R controlled', _wr_ok(direction, s1.get('williams_r'))),
        ('Structure aligned', _structure_ok(direction, str(snap.get('structure') or ''))),
        ('Pivot context', _pivot_ok(direction, str(snap.get('five_zone') or ''))),
    ]


def evaluate_entry(underlying: str, action: str, snap: dict):
    """Fresh V5 entry gate. It prefers fewer, cleaner setups over raw frequency."""
    tf = snap.get('tf') or {}
    s1, s5, s15, s1h = (tf.get(k) or {} for k in ('1m','5m','15m','1h'))
    direction = _local_direction(snap)
    if not direction:
        return False, 'V5 wait: 1m/5m flow not aligned strongly enough'

    if _strong_opposite(direction, s15):
        return False, 'V5 reject: 15m strong opposite trend'
    if _strong_opposite(direction, s1h, 30, 5):
        return False, 'V5 reject: extreme 1h opposite trend'

    adx = _f(s5.get('adx'))
    rv = max(_f(s5.get('rel_volume')), _f(s1.get('rel_volume')))
    ratio = _di_ratio(direction, s5)
    if adx < 8 and rv < 0.35:
        return False, f'V5 reject: dead tape ADX {adx:.1f} RVOL {rv:.2f}'

    vwap_atr = _f(snap.get('vwap_distance_atr'))
    ema9_atr = _f(snap.get('ema9_distance_atr'))
    if vwap_atr > 2.40 or ema9_atr > 1.40:
        return False, f'V5 reject: chased entry {vwap_atr:.2f}/{ema9_atr:.2f} ATR'

    structure_ok = _structure_ok(direction, str(snap.get('structure') or ''))
    one_break = bool(snap.get('one_min_breakout'))
    one_ema = _ema_aligned(direction, s1)

    if ema9_atr <= 0.70 and one_ema and _wr_ok(direction, s1.get('williams_r')):
        pattern = 'PULLBACK_RESUME'
    elif one_break and structure_ok and (adx >= 14 or rv >= 0.65):
        pattern = 'BREAKOUT_CONFIRM'
    elif structure_ok and adx >= 16 and ratio >= 1.08 and rv >= 0.45:
        pattern = 'TREND_CONTINUATION'
    else:
        return False, 'V5 wait: no clean pullback/breakout/continuation trigger'

    a5 = max(_f(s5.get('atr')), max(_f(s5.get('price')) * 0.0002, 1e-9))
    price = _f(s5.get('price'))
    risk_atr = 0.80
    invalidation = price - risk_atr * a5 if direction == 'BULLISH' else price + risk_atr * a5

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
    snap['active_flow_mode'] = False
    snap['clean_confluence_mode'] = True
    snap['structural_invalidation'] = invalidation
    snap['underlying_risk_atr'] = risk_atr
    snap['major_level_context_only'] = True
    _rewrite_setup_id(snap, direction, pattern)
    return True, f'V5_CLEAN_PASS {pattern}'


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

    min_premium = max(0.05, 3.0 * tick, 1.15 * spread)
    if p < min_premium:
        return False, f'premium<{min_premium:.4g} floor', {'spread_pct': spread_pct, 'min_premium': min_premium}

    s = _f(spot, 0)
    if s > 0 and p / s > PREMIUM_SPOT_CAP.get(underlying, 0.03):
        return False, 'premium/spot above V5 cap', {'spread_pct': spread_pct}

    d = None if delta is None else abs(_f(delta, -1))
    if d is not None and d >= 0:
        lo, hi = ((0.20, 0.70) if action == 'OPTION BUY' else (0.10, 0.40))
        if not (lo <= d <= hi):
            return False, f'delta outside V5 {lo:.2f}-{hi:.2f}', {'spread_pct': spread_pct, 'abs_delta': d}

    score = _f(python_score, 100)
    if score < MIN_ALERT_SCORE:
        return False, f'Python score<{MIN_ALERT_SCORE}', {'spread_pct': spread_pct}

    if minutes_to_expiry is not None:
        mte = _f(minutes_to_expiry, -1)
        if 0 <= mte < 60:
            return False, 'expiry<60m', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}

    return True, 'V5_CONTRACT_PASS', {
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

    score += min(30.0, _votes(direction, s5) * 6.0)
    score += min(20.0, _votes(direction, s1) * 4.0)
    if _votes(direction, s15) >= 3: score += 8
    if not _strong_opposite(direction, s15): score += 5
    if not _strong_opposite(direction, s1h, 30, 5): score += 3

    adx = _f(s5.get('adx'))
    ratio = _di_ratio(direction, s5)
    rv = max(_f(s5.get('rel_volume')), _f(s1.get('rel_volume')))
    score += 7 if adx >= 20 else (5 if adx >= 14 else (2 if adx >= 10 else 0))
    score += 6 if ratio >= 1.20 else (4 if ratio >= 1.08 else 0)
    score += 6 if rv >= 1.0 else (4 if rv >= 0.65 else (2 if rv >= 0.45 else 0))
    if _rsi_ok(direction, s1.get('rsi')): score += 4
    if _wr_ok(direction, s1.get('williams_r')): score += 4
    if _structure_ok(direction, str(snap.get('structure') or '')): score += 5
    if _pivot_ok(direction, str(snap.get('five_zone') or '')): score += 2

    pattern = str(snap.get('pattern') or '')
    if pattern == 'PULLBACK_RESUME': score += 7
    elif pattern == 'BREAKOUT_CONFIRM': score += 6
    elif pattern == 'TREND_CONTINUATION': score += 5

    score += max(0.0, min(5.0, _f(contract_score) * 0.05))
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
    if d == 'REJECT': return -2 if c >= 90 else -1
    return 0
