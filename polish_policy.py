"""ROBO STAFF first Delta strategy — Fresh V3.7 BALANCED CONFIRMATION SCALP.

Goal: improve signal quality after the V3.6 ultra-loose research sample showed too
many fast SLs. 1m + 5m remain the execution authority, but a signal now needs a
small confirmation stack similar to the compact Indian-market alert style:
15m price action, 5m EMA context, 1m EMA context, RSI, Williams %R, structure and
pivot context. 15m/1h are context, not absolute blockers.

SIGNAL ONLY. No order placement, modification, cancellation or broker secrets.
MASTER MIND stays separate with its own cooldown.
"""
from __future__ import annotations

import math

POLISH_VERSION = "FRESH_V3.7_BALANCED_SCALP_2026-09-29"
MODE_REVISION = "BALANCED_CONFIRMATION_SCALP_2026-09-29"
MIN_ALERT_SCORE = 58
STRONG_SCORE = 72
ELITE_SCORE = 86
DAILY_RESEARCH_TARGET = 5

SPREAD_CAP_PCT = {"BTC": 4.0, "ETH": 5.0, "GOLD": 6.0}
DAILY_SIGNAL_CAP = {"BTC": 12, "ETH": 12, "GOLD": 10}
PREMIUM_SPOT_CAP = {"BTC": 0.0160, "ETH": 0.0160, "GOLD": 0.0200}

BASE_COOLDOWN_MINUTES = 5
SUCCESS_COOLDOWN_MINUTES = 4
FAIL_COOLDOWN_MINUTES = 9
CONTRACT_COOLDOWN_MINUTES = 6
CORRELATION_WINDOW_MINUTES = 5
CORRELATION_THRESHOLD = 0.94

ACCEPTANCE_CRITERIA = {
    "min_resolved": 50,
    "preferred_resolved": 80,
    "min_calendar_days": 3,
    "min_t1_success_pct": 40.0,
    "min_profit_factor": 1.20,
    "min_expectancy_r": 0.10,
    "max_median_t1_minutes": 25.0,
    "max_p75_t1_minutes": 40.0,
    "max_fast_sl_pct": 30.0,
    "max_sl_later_t1_pct": 20.0,
    "max_stale_pct": 20.0,
    "bucket_min_n": 12,
    "bucket_min_win_pct": 36.0,
    "bucket_min_pf": 1.0,
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
        return (px >= e9 and pdi >= mdi) or (px >= vw and pdi > mdi)
    return (px <= e9 and mdi >= pdi) or (px <= vw and mdi > pdi)


def _rsi_ok(direction: str, value) -> bool:
    v = _f(value, 50)
    return 48 <= v <= 76 if direction == 'BULLISH' else 24 <= v <= 52


def _wr_ok(direction: str, value) -> bool:
    v = _f(value, -50)
    return -65 <= v <= -8 if direction == 'BULLISH' else -92 <= v <= -35


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


def _direction_candidates(snap: dict):
    tf = snap.get('tf') or {}
    s1, s5 = tf.get('1m') or {}, tf.get('5m') or {}
    rows = []
    for d in ('BULLISH', 'BEARISH'):
        core = int(_ema_side(d, s5)) * 3 + int(_ema_side(d, s1)) * 3
        core += int(_price_action(d, s5)) * 2 + int(_price_action(d, s1)) * 2
        core += int(_rsi_ok(d, s1.get('rsi'))) + int(_wr_ok(d, s1.get('williams_r')))
        rows.append((core, d))
    rows.sort(reverse=True)
    return rows


def _confirmations(direction: str, snap: dict):
    tf = snap.get('tf') or {}
    s1, s5, s15 = tf.get('1m') or {}, tf.get('5m') or {}, tf.get('15m') or {}
    structure = str(snap.get('structure') or '')
    five_zone = str(snap.get('five_zone') or '')
    items = [
        ('15M price action', _price_action(direction, s15)),
        ('5M EMA 9/20', _ema_side(direction, s5)),
        ('1M EMA 9/20', _ema_side(direction, s1)),
        ('1M price action', _price_action(direction, s1)),
        ('RSI zone', _rsi_ok(direction, s1.get('rsi'))),
        ('Williams %R', _wr_ok(direction, s1.get('williams_r'))),
        ('5M structure', _structure_ok(direction, structure)),
        ('5M pivot side', _pivot_supports(direction, five_zone)),
    ]
    return items


def evaluate_entry(underlying: str, action: str, snap: dict):
    """Balanced scalp gate built around a compact confirmation vote."""
    tf = snap.get('tf') or {}
    s1, s5, s15 = tf.get('1m') or {}, tf.get('5m') or {}, tf.get('15m') or {}

    rows = _direction_candidates(snap)
    best_score, direction = rows[0]
    second = rows[1][0]
    if best_score < 7 or best_score <= second:
        return False, f'V3.7 local direction unresolved {best_score}/{second}'

    # Core execution alignment must exist on both 1m and 5m.
    if not (_ema_side(direction, s5) and _ema_side(direction, s1)):
        return False, 'V3.7 1m/5m EMA alignment missing'

    confirmations = _confirmations(direction, snap)
    passed = [name for name, ok in confirmations if ok]
    failed = [name for name, ok in confirmations if not ok]
    count = len(passed)

    # A normal trade needs 5/8. If 15m disagrees, demand 6/8 and stronger local tape.
    adx = _f(s5.get('adx'))
    rvol = _f(s5.get('rel_volume'))
    ratio = _di_ratio(direction, s5)
    htf15 = _price_action(direction, s15)
    need = 5 if htf15 else 6
    if count < need:
        return False, f'V3.7 confirmations {count}/8 need {need}'
    if not htf15 and not (adx >= 16 or rvol >= 0.65 or ratio >= 1.15):
        return False, 'V3.7 15m conflict without strong local momentum'

    # The V3.6 sample had many <5m SLs; reject very weak/dead tape and extreme chase.
    if adx < 8 and rvol < 0.20:
        return False, f'V3.7 dead tape ADX/RVOL {adx:.1f}/{rvol:.2f}'
    vwap_atr = _f(snap.get('vwap_distance_atr'))
    ema9_atr = _f(snap.get('ema9_distance_atr'))
    if vwap_atr > 3.0 or ema9_atr > 1.8:
        return False, f'V3.7 chase {vwap_atr:.2f}/{ema9_atr:.2f} ATR'

    # Avoid entering directly into an exhausted 1m oscillator extreme.
    rsi1, wr1 = _f(s1.get('rsi'), 50), _f(s1.get('williams_r'), -50)
    if direction == 'BULLISH' and (rsi1 > 80 or wr1 > -3):
        return False, 'V3.7 bullish micro exhaustion'
    if direction == 'BEARISH' and (rsi1 < 20 or wr1 < -97):
        return False, 'V3.7 bearish micro exhaustion'

    # Classify entry style. Prefer pullbacks and confirmed momentum, not blind flow.
    ema9_atr = _f(snap.get('ema9_distance_atr'))
    structure_ok = _structure_ok(direction, str(snap.get('structure') or ''))
    pivot_ok = _pivot_supports(direction, str(snap.get('five_zone') or ''))
    if ema9_atr <= 0.65 and _price_action(direction, s1):
        pattern = 'PULLBACK_CONFIRM'
    elif structure_ok and pivot_ok and (adx >= 14 or rvol >= 0.45):
        pattern = 'BREAKOUT_CONFIRM'
    elif _price_action(direction, s15) and (adx >= 12 or ratio >= 1.08):
        pattern = 'TREND_SCALP'
    else:
        pattern = 'MICRO_CONFIRM'

    snap['direction'] = direction
    snap['pattern'] = pattern
    snap['confirmation_count'] = count
    snap['confirmation_total'] = len(confirmations)
    snap['confirmations_passed'] = passed
    snap['confirmations_failed'] = failed
    snap['scalp_mode'] = True
    snap['one_min_trigger'] = _price_action(direction, s1)
    snap['one_min_ema_hold'] = _ema_side(direction, s1)
    snap['price_ema_aligned'] = _ema_side(direction, s5)
    snap['major_level_context_only'] = True
    snap['balanced_confirmation_mode'] = True
    _rewrite_setup_id(snap, direction, pattern)
    return True, f'V3.7_BALANCED_PASS {count}/8'


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
    if s > 0 and p / s > PREMIUM_SPOT_CAP.get(underlying, 0.016):
        return False, 'premium/spot above V3.7 cap', {'spread_pct': spread_pct}

    d = None if delta is None else abs(_f(delta, -1))
    if d is not None and d >= 0:
        if d < 0.05:
            return False, 'lottery delta<0.05', {'spread_pct': spread_pct, 'abs_delta': d}
        lo, hi = ((0.10, 0.65) if action == 'OPTION BUY' else (0.07, 0.50))
        if not (lo <= d <= hi):
            return False, f'delta outside V3.7 {lo:.2f}-{hi:.2f}', {'spread_pct': spread_pct, 'abs_delta': d}

    score = _f(python_score, 100)
    if action == 'OPTION BUY' and score < 62:
        return False, 'OPTION BUY requires Python score>=62', {'spread_pct': spread_pct}
    if action == 'OPTION SELL' and score < 58:
        return False, 'OPTION SELL requires Python score>=58', {'spread_pct': spread_pct}

    if minutes_to_expiry is not None:
        mte = _f(minutes_to_expiry, -1)
        if 0 <= mte < 45:
            return False, 'expiry<45m', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}
        if 45 <= mte < 90 and (score < 68 or spread_pct > 4.0):
            return False, 'near-expiry needs score>=68 and spread<=4%', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}

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
    s1, s5, s15 = tf.get('1m') or {}, tf.get('5m') or {}, tf.get('15m') or {}
    count = int(snap.get('confirmation_count') or 0)
    score = 20.0 + count * 8.0

    # Reward the most useful confirmations without making them separate hard gates.
    if _price_action(direction, s15): score += 5
    if _structure_ok(direction, str(snap.get('structure') or '')): score += 5
    if _pivot_supports(direction, str(snap.get('five_zone') or '')): score += 4

    adx, ratio, rvol = _f(s5.get('adx')), _di_ratio(direction, s5), _f(s5.get('rel_volume'))
    score += 5 if adx >= 22 else (3 if adx >= 14 else 1)
    score += 4 if ratio >= 1.20 else (2 if ratio >= 1.05 else 0)
    score += 4 if rvol >= 1.0 else (2 if rvol >= 0.50 else 0)

    pattern = str(snap.get('pattern') or '')
    if pattern == 'PULLBACK_CONFIRM': score += 5
    elif pattern == 'BREAKOUT_CONFIRM': score += 4
    elif pattern == 'TREND_SCALP': score += 3
    else: score += 1

    # Contract score arrives as 0..10 from the engine.
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
    if d == 'CONFIRM' and c >= 80: return 2
    if d == 'WAIT': return -1
    if d == 'REJECT': return -3 if c >= 90 else -2
    return 0
