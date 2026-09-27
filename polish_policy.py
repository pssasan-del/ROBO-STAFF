"""ROBO STAFF Delta Structure Breakout V3.2 — deterministic policy.

This module is deliberately signal-only.  It contains hard gates, scoring,
contract quality and research acceptance constants; it never places orders.
"""
from __future__ import annotations

import math

POLISH_VERSION = "FRESH_V3.2_2026-09-27"
MIN_ALERT_SCORE = 82
STRONG_SCORE = 90
ELITE_SCORE = 95

SPREAD_CAP_PCT = {"BTC": 2.5, "ETH": 3.0, "GOLD": 4.0}
DAILY_SIGNAL_CAP = {"BTC": 6, "ETH": 6, "GOLD": 4}
RVOL_MIN = {"BTC": 1.15, "ETH": 1.15, "GOLD": 1.05}
PREMIUM_SPOT_CAP = {"BTC": 0.0075, "ETH": 0.0075, "GOLD": 0.0100}
BASE_COOLDOWN_MINUTES = 20
SUCCESS_COOLDOWN_MINUTES = 15
FAIL_COOLDOWN_MINUTES = 30
CONTRACT_COOLDOWN_MINUTES = 30
CORRELATION_WINDOW_MINUTES = 15
CORRELATION_THRESHOLD = 0.80

ACCEPTANCE_CRITERIA = {
    "min_resolved": 50,
    "preferred_resolved": 75,
    "min_calendar_days": 5,
    "min_t1_success_pct": 44.0,
    "min_profit_factor": 1.35,
    "min_expectancy_r": 0.20,
    "max_median_t1_minutes": 20.0,
    "max_p75_t1_minutes": 35.0,
    "max_fast_sl_pct": 25.0,
    "max_sl_later_t1_pct": 15.0,
    "max_stale_pct": 15.0,
    "bucket_min_n": 15,
    "bucket_min_win_pct": 38.0,
    "bucket_min_pf": 1.0,
}


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _directional_ok(direction: str, state: dict, *, full_ema=False, min_adx=0.0):
    d = str(direction or '').upper()
    px, e5, e9, e20, vw = (_f(state.get(k)) for k in ('price', 'ema5', 'ema9', 'ema20', 'vwap'))
    pdi, mdi, adx = _f(state.get('plus_di')), _f(state.get('minus_di')), _f(state.get('adx'))
    if adx < min_adx:
        return False
    if d == 'BULLISH':
        ema_ok = e5 > e9 > e20 if full_ema else e5 > e9
        return ema_ok and px > vw and pdi > mdi
    if d == 'BEARISH':
        ema_ok = e5 < e9 < e20 if full_ema else e5 < e9
        return ema_ok and px < vw and mdi > pdi
    return False


def evaluate_entry(underlying: str, action: str, snap: dict):
    """Hard deterministic V3.2 entry gates. Score is calculated only after pass."""
    underlying = str(underlying or '').upper()
    direction = str(snap.get('direction') or '').upper()
    if direction not in {'BULLISH', 'BEARISH'}:
        return False, 'mixed direction'

    tf = snap.get('tf') or {}
    s1 = tf.get('1m') or {}; s5 = tf.get('5m') or {}; s15 = tf.get('15m') or {}; s1h = tf.get('1h') or {}

    if not _directional_ok(direction, s1h, full_ema=True, min_adx=18):
        return False, '1H alignment/ADX failed'
    if not _directional_ok(direction, s15, full_ema=False, min_adx=18):
        return False, '15m alignment/ADX failed'

    cross = snap.get('ema_cross_5m') or {}
    bars_ago = cross.get('bars_ago')
    if str(cross.get('side') or '').upper() != direction or bars_ago not in (0, 1):
        return False, 'EMA5/9 cross is late or opposite'
    pattern = str(snap.get('pattern') or '')
    if bars_ago == 0 and pattern != 'BREAKOUT':
        return False, 'fresh cross lacks 5m breakout'
    if bars_ago == 1 and pattern != 'RETEST':
        return False, 'one-bar cross lacks valid retest'

    structure = str(snap.get('structure') or '')
    if direction == 'BULLISH' and structure != 'HH/HL':
        return False, 'bullish structure not HH/HL'
    if direction == 'BEARISH' and structure != 'LH/LL':
        return False, 'bearish structure not LH/LL'

    adx, pdi, mdi, rvol = _f(s5.get('adx')), _f(s5.get('plus_di')), _f(s5.get('minus_di')), _f(s5.get('rel_volume'))
    if adx < 22:
        return False, '5m ADX<22'
    di_ratio = (pdi / max(mdi, 1.0)) if direction == 'BULLISH' else (mdi / max(pdi, 1.0))
    if di_ratio < 1.20:
        return False, '5m DI ratio<1.20'
    if rvol < RVOL_MIN.get(underlying, 1.15):
        return False, f'5m RVOL<{RVOL_MIN.get(underlying, 1.15):.2f}'

    if not snap.get('price_ema_aligned'):
        return False, '5m price/EMA5/EMA9 not aligned'
    if not snap.get('one_min_trigger'):
        return False, '1m execution trigger failed'

    daily_zone, five_zone = str(snap.get('daily_zone') or ''), str(snap.get('five_zone') or '')
    if direction == 'BULLISH':
        if daily_zone not in {'PIVOT_TO_R1', 'ABOVE_R1'}:
            return False, 'bullish below Daily Pivot'
        if five_zone not in {'PIVOT_TO_R1', 'ABOVE_R1'}:
            return False, 'bullish below 5m Pivot'
    else:
        if daily_zone not in {'S1_TO_PIVOT', 'BELOW_S1'}:
            return False, 'bearish above Daily Pivot'
        if five_zone not in {'S1_TO_PIVOT', 'BELOW_S1'}:
            return False, 'bearish above 5m Pivot'

    if snap.get('choppy'):
        return False, 'choppy/compressed 5m setup'
    if snap.get('overextended'):
        return False, 'overextended from VWAP/EMA9'
    if _f(snap.get('distance_to_next_pivot_atr')) < 0.75:
        return False, 'insufficient room to next pivot/swing'
    if _f(snap.get('breakout_extension_atr')) > 0.80:
        return False, 'late breakout extension>0.80 ATR'

    rsi5, wr5 = _f(s5.get('rsi')), _f(s5.get('williams_r'))
    if direction == 'BULLISH' and (rsi5 > 82 or wr5 > -3):
        return False, 'bullish momentum already exhausted'
    if direction == 'BEARISH' and (rsi5 < 18 or wr5 < -97):
        return False, 'bearish momentum already exhausted'

    return True, 'V3.2_HARD_GATES_PASS'


def contract_gate(underlying: str, action: str, *, entry, bid, ask, spot=None, delta=None,
                  tick_size=0.01, minutes_to_expiry=None, python_score=None):
    """Return (allowed, reason, metrics) for an executable option quote."""
    underlying = str(underlying or '').upper()
    action = str(action or '').upper()
    p, b, a, tick = _f(entry, -1), _f(bid, -1), _f(ask, -1), max(_f(tick_size, 0.01), 1e-9)
    if p <= 0 or b <= 0 or a <= 0 or a < b:
        return False, 'invalid two-sided quote', {}
    mid = (a + b) / 2.0
    spread = a - b
    spread_pct = spread / mid * 100.0 if mid > 0 else 999.0
    cap = SPREAD_CAP_PCT.get(underlying, 3.0)
    if spread_pct > cap:
        return False, f'spread>{cap:.1f}%', {'spread_pct': spread_pct}

    min_premium = max(0.10, 10.0 * tick, 4.0 * spread)
    if p < min_premium:
        return False, f'premium<{min_premium:.4g} execution floor', {'spread_pct': spread_pct, 'min_premium': min_premium}

    s = _f(spot, 0)
    if s > 0 and p / s > PREMIUM_SPOT_CAP.get(underlying, 0.0075):
        return False, 'premium/spot above V3.2 cap', {'spread_pct': spread_pct}

    d = None if delta is None else abs(_f(delta, -1))
    if d is not None and d >= 0:
        if d < 0.10:
            return False, 'lottery delta<0.10', {'spread_pct': spread_pct, 'abs_delta': d}
        lo, hi = ((0.25, 0.50) if action == 'OPTION BUY' else (0.15, 0.35))
        if not (lo <= d <= hi):
            return False, f'delta outside {lo:.2f}-{hi:.2f}', {'spread_pct': spread_pct, 'abs_delta': d}

    if minutes_to_expiry is not None:
        mte = _f(minutes_to_expiry, -1)
        if 0 <= mte < 90:
            return False, 'expiry<90m', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}
        if 90 <= mte < 240:
            if _f(python_score, 0) < 90 or spread_pct > 2.0 or d is None:
                return False, 'near-expiry requires score>=90, spread<=2%, valid delta', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}

    return True, 'CONTRACT_GATE_PASS', {
        'spread_pct': spread_pct, 'spread_abs': spread, 'min_premium': min_premium,
        'abs_delta': d, 'tick_size': tick,
    }


def evaluate_contract(premium, *, tick_size=None, bid=None, ask=None, underlying='BTC', action='OPTION BUY',
                      spot=None, delta=None, minutes_to_expiry=None, python_score=None):
    """Backward-compatible two-value wrapper used by older tests/callers."""
    ok, reason, _ = contract_gate(
        underlying, action, entry=premium, bid=bid, ask=ask, spot=spot, delta=delta,
        tick_size=tick_size or 0.01, minutes_to_expiry=minutes_to_expiry,
        python_score=python_score,
    )
    return ok, reason


def quality_score(underlying: str, snap: dict, contract_score: float = 0.0) -> int:
    """Calibrated 0-100 score. Call only after deterministic hard gates pass."""
    direction = str(snap.get('direction') or '').upper()
    tf = snap.get('tf') or {}; s1h=tf.get('1h') or {}; s15=tf.get('15m') or {}; s5=tf.get('5m') or {}
    score = 0.0

    if _directional_ok(direction, s1h, full_ema=True, min_adx=18): score += 10
    if _directional_ok(direction, s15, full_ema=True, min_adx=18): score += 10
    elif _directional_ok(direction, s15, full_ema=False, min_adx=18): score += 5

    if (direction == 'BULLISH' and snap.get('structure') == 'HH/HL') or (direction == 'BEARISH' and snap.get('structure') == 'LH/LL'):
        score += 8
    cross = snap.get('ema_cross_5m') or {}
    if cross.get('bars_ago') in (0, 1): score += 7
    if snap.get('pattern') in {'BREAKOUT', 'RETEST'}: score += 5

    adx, pdi, mdi, rvol = _f(s5.get('adx')), _f(s5.get('plus_di')), _f(s5.get('minus_di')), _f(s5.get('rel_volume'))
    score += 7 if adx >= 28 else (5 if adx >= 25 else 3)
    ratio = (pdi/max(mdi,1)) if direction == 'BULLISH' else (mdi/max(pdi,1))
    score += 4 if ratio >= 1.35 else 2
    score += 4 if rvol >= 1.50 else (3 if rvol >= 1.25 else 1)

    ideal_daily = snap.get('daily_zone') == ('PIVOT_TO_R1' if direction == 'BULLISH' else 'S1_TO_PIVOT')
    ideal_five = snap.get('five_zone') == ('PIVOT_TO_R1' if direction == 'BULLISH' else 'S1_TO_PIVOT')
    if ideal_daily: score += 7
    elif snap.get('pivot_extension_valid'): score += 4
    if ideal_five: score += 5
    elif snap.get('pivot_extension_valid'): score += 3
    if _f(snap.get('distance_to_next_pivot_atr')) >= 1.0: score += 3

    if snap.get('one_min_breakout'): score += 6
    if snap.get('one_min_ema_hold'): score += 4

    if not snap.get('overextended') and _f(snap.get('vwap_distance_atr')) <= 1.0: score += 5

    rsi5, wr5 = _f(s5.get('rsi')), _f(s5.get('williams_r'))
    if direction == 'BULLISH':
        if 45 <= rsi5 <= 72: score += 3
        if -80 <= wr5 <= -10: score += 2
    else:
        if 28 <= rsi5 <= 55: score += 3
        if -90 <= wr5 <= -20: score += 2

    score += max(0.0, min(10.0, _f(contract_score)))
    return int(round(max(0.0, min(100.0, score))))


def quality_label(score: int) -> str:
    if score >= ELITE_SCORE: return 'ELITE'
    if score >= STRONG_SCORE: return 'STRONG'
    if score >= MIN_ALERT_SCORE: return 'VALID'
    return 'NO TRADE'


def ai_adjustment(decision: str, confidence: int) -> int:
    d = str(decision or '').upper(); c = int(max(0, min(100, confidence or 0)))
    if d == 'CONFIRM' and c >= 80: return 3
    if d == 'WAIT': return -3
    if d == 'REJECT': return -7 if c >= 90 else -4
    return 0
