"""ROBO STAFF Delta Structure Breakout V3.2 — deterministic policy.

Signal-only strategy policy. No order execution methods live here.

2026-09-28 adaptive momentum patch:
- preserves the original fresh BREAKOUT / one-bar RETEST path;
- preserves the guarded MOMENTUM_CONTINUATION path;
- removes the accidental global structure/overextension blocks that prevented
  strong mature trends from ever reaching the continuation logic;
- allows a stricter SOFT-STRUCTURE continuation when the completed 5m breakout,
  EMA stack, ADX/DI/RVOL, HTF alignment and 1m trigger all agree;
- allows a bounded EXTENDED-IMPULSE continuation only for unusually strong
  momentum, while still rejecting late chases.
"""
from __future__ import annotations

import math

POLISH_VERSION = "FRESH_V3.2_2026-09-27"
MODE_REVISION = "ADAPTIVE_MOMENTUM_2026-09-28"
MIN_ALERT_SCORE = 82
STRONG_SCORE = 90
ELITE_SCORE = 95

SPREAD_CAP_PCT = {"BTC": 2.5, "ETH": 3.0, "GOLD": 4.0}
DAILY_SIGNAL_CAP = {"BTC": 6, "ETH": 6, "GOLD": 4}
RVOL_MIN = {"BTC": 1.15, "ETH": 1.15, "GOLD": 1.05}
MOMENTUM_RVOL_MIN = {"BTC": 1.00, "ETH": 1.00, "GOLD": 0.90}
IMPULSE_RVOL_MIN = {"BTC": 1.20, "ETH": 1.20, "GOLD": 1.05}
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


def _directional_structure_ok(direction: str, structure: str) -> bool:
    return ((direction == 'BULLISH' and structure == 'HH/HL') or
            (direction == 'BEARISH' and structure == 'LH/LL'))


def _pivot_side_ok(direction: str, daily_zone: str, five_zone: str) -> bool:
    if direction == 'BULLISH':
        return daily_zone in {'PIVOT_TO_R1', 'ABOVE_R1'} and five_zone in {'PIVOT_TO_R1', 'ABOVE_R1'}
    if direction == 'BEARISH':
        return daily_zone in {'S1_TO_PIVOT', 'BELOW_S1'} and five_zone in {'S1_TO_PIVOT', 'BELOW_S1'}
    return False


def _full_5m_stack(direction: str, s5: dict) -> bool:
    px, e5, e9, e20 = (_f(s5.get(k)) for k in ('price', 'ema5', 'ema9', 'ema20'))
    if direction == 'BULLISH':
        return px > e5 > e9 > e20
    if direction == 'BEARISH':
        return px < e5 < e9 < e20
    return False


def _continuation_breakout_ok(direction: str, snap: dict) -> bool:
    px = _f(snap.get('last_closed_5m'))
    level = _f(snap.get('breakout_level'))
    if px <= 0 or level <= 0:
        return False
    return px > level if direction == 'BULLISH' else px < level


def _compression(s5: dict) -> bool:
    px = max(_f(s5.get('price')), 1e-9)
    e5, e20, rvol = _f(s5.get('ema5')), _f(s5.get('ema20')), _f(s5.get('rel_volume'))
    return abs(e5 - e20) / px < 0.0004 and rvol < 1.10


def _mark_momentum_pattern(snap: dict, *, relaxed_structure=False, impulse=False):
    snap['pattern'] = 'MOMENTUM_CONTINUATION'
    snap['momentum_mode'] = True
    snap['structure_relaxed'] = bool(relaxed_structure)
    snap['impulse_extension'] = bool(impulse)
    sid = str(snap.get('setup_id') or '')
    if ':NONE:' in sid:
        snap['setup_id'] = sid.replace(':NONE:', ':MOMENTUM_CONTINUATION:', 1)


def evaluate_entry(underlying: str, action: str, snap: dict):
    """V3.2 deterministic entry gates with adaptive mature-trend continuation.

    Fresh BREAKOUT/RETEST remains the preferred path and still requires strict
    structure and the original conservative extension rules. Mature trends are
    evaluated separately so an old EMA cross or a non-perfect 6-vs-6 structure
    label cannot by itself suppress an otherwise strong continuation scalp.
    """
    underlying = str(underlying or '').upper()
    direction = str(snap.get('direction') or '').upper()
    if direction not in {'BULLISH', 'BEARISH'}:
        return False, 'mixed direction'

    tf = snap.get('tf') or {}
    s5 = tf.get('5m') or {}; s15 = tf.get('15m') or {}; s1h = tf.get('1h') or {}

    if not _directional_ok(direction, s1h, full_ema=True, min_adx=18):
        return False, '1H alignment/ADX failed'
    if not _directional_ok(direction, s15, full_ema=False, min_adx=18):
        return False, '15m alignment/ADX failed'
    if not snap.get('price_ema_aligned'):
        return False, '5m price/EMA5/EMA9 not aligned'
    if not snap.get('one_min_trigger'):
        return False, '1m execution trigger failed'

    daily_zone, five_zone = str(snap.get('daily_zone') or ''), str(snap.get('five_zone') or '')
    if not _pivot_side_ok(direction, daily_zone, five_zone):
        return False, 'Daily/5m pivot side opposes direction'

    structure = str(snap.get('structure') or '')
    structure_strict = _directional_structure_ok(direction, structure)
    adx = _f(s5.get('adx')); pdi = _f(s5.get('plus_di')); mdi = _f(s5.get('minus_di')); rvol = _f(s5.get('rel_volume'))
    di_ratio = (pdi / max(mdi, 1.0)) if direction == 'BULLISH' else (mdi / max(pdi, 1.0))

    cross = snap.get('ema_cross_5m') or {}
    bars_ago = cross.get('bars_ago')
    cross_side = str(cross.get('side') or '').upper()
    pattern = str(snap.get('pattern') or '')
    fresh_path = cross_side == direction and bars_ago in (0, 1) and (
        (bars_ago == 0 and pattern == 'BREAKOUT') or
        (bars_ago == 1 and pattern == 'RETEST')
    )

    if fresh_path:
        if not structure_strict:
            return False, f'{direction.lower()} fresh structure invalid'
        if snap.get('choppy'):
            return False, 'fresh setup choppy/compressed'
        if snap.get('overextended'):
            return False, 'fresh setup overextended from VWAP/EMA9'
        if adx < 22:
            return False, '5m ADX<22'
        if di_ratio < 1.20:
            return False, '5m DI ratio<1.20'
        if rvol < RVOL_MIN.get(underlying, 1.15):
            return False, f'5m RVOL<{RVOL_MIN.get(underlying, 1.15):.2f}'
        if _f(snap.get('distance_to_next_pivot_atr')) < 0.75:
            return False, 'insufficient room to next pivot/swing'
        if _f(snap.get('breakout_extension_atr')) > 0.80:
            return False, 'late breakout extension>0.80 ATR'
    else:
        if not _full_5m_stack(direction, s5):
            return False, 'no fresh cross and no full 5m continuation stack'
        if not _continuation_breakout_ok(direction, snap):
            return False, 'momentum continuation has not cleared 5m breakout level'
        if _compression(s5):
            return False, 'momentum EMA5/20 compression'
        if adx < 25:
            return False, f'momentum ADX<25 ({adx:.1f})'
        if di_ratio < 1.35:
            return False, f'momentum DI ratio<1.35 ({di_ratio:.2f})'
        if rvol < MOMENTUM_RVOL_MIN.get(underlying, 1.0):
            return False, f'momentum RVOL<{MOMENTUM_RVOL_MIN.get(underlying, 1.0):.2f} ({rvol:.2f})'

        # The old 6-vs-6 HH/HL/LH/LL classifier can briefly report RANGE or
        # the wrong label during a strong impulse. For continuation only, allow
        # that label to be overridden by stronger completed-bar evidence.
        relaxed_structure = False
        if not structure_strict:
            soft_rvol = max(MOMENTUM_RVOL_MIN.get(underlying, 1.0), 1.05 if underlying != 'GOLD' else 0.95)
            if adx < 28 or di_ratio < 1.50 or rvol < soft_rvol:
                return False, (
                    f'{direction.lower()} structure invalid; soft continuation needs '
                    f'ADX>=28/DI>=1.50/RVOL>={soft_rvol:.2f} '
                    f'(got {adx:.1f}/{di_ratio:.2f}/{rvol:.2f})'
                )
            relaxed_structure = True

        vwap_atr = _f(snap.get('vwap_distance_atr'))
        ema9_atr = _f(snap.get('ema9_distance_atr'))
        ext_atr = _f(snap.get('breakout_extension_atr'))
        room_atr = _f(snap.get('distance_to_next_pivot_atr'))

        # Normal mature continuation limits.
        normal_extension = (
            vwap_atr <= 1.75 and ema9_atr <= 0.75 and
            ext_atr <= 0.65 and room_atr >= 0.60
        )

        # A controlled exception for high-energy impulse markets. This is not a
        # generic relaxation: all strength conditions and absolute chase caps
        # must pass. It exists specifically for fast BTC/ETH/XAUT sessions where
        # VWAP/EMA9 lag price during a genuine directional impulse.
        impulse_rvol = IMPULSE_RVOL_MIN.get(underlying, 1.20)
        impulse_strength = adx >= 32 and di_ratio >= 1.55 and rvol >= impulse_rvol
        impulse_extension = (
            impulse_strength and
            vwap_atr <= 2.40 and ema9_atr <= 1.10 and
            ext_atr <= 0.85 and room_atr >= 0.75
        )
        if not normal_extension and not impulse_extension:
            return False, (
                'momentum extension/room failed '
                f'(VWAP {vwap_atr:.2f}ATR, EMA9 {ema9_atr:.2f}ATR, '
                f'breakout {ext_atr:.2f}ATR, room {room_atr:.2f}ATR, '
                f'ADX {adx:.1f}, DI {di_ratio:.2f}, RVOL {rvol:.2f})'
            )

        _mark_momentum_pattern(
            snap,
            relaxed_structure=relaxed_structure,
            impulse=(not normal_extension and impulse_extension),
        )

    rsi5, wr5 = _f(s5.get('rsi')), _f(s5.get('williams_r'))
    if direction == 'BULLISH' and (rsi5 > 82 or wr5 > -3):
        return False, 'bullish momentum already exhausted'
    if direction == 'BEARISH' and (rsi5 < 18 or wr5 < -97):
        return False, 'bearish momentum already exhausted'

    if snap.get('impulse_extension'):
        return True, 'V3.2_EXTENDED_IMPULSE_PASS'
    if snap.get('structure_relaxed'):
        return True, 'V3.2_SOFT_STRUCTURE_MOMENTUM_PASS'
    return True, 'V3.2_MOMENTUM_GATES_PASS' if snap.get('momentum_mode') else 'V3.2_HARD_GATES_PASS'


def contract_gate(underlying: str, action: str, *, entry, bid, ask, spot=None, delta=None,
                  tick_size=0.01, minutes_to_expiry=None, python_score=None):
    underlying = str(underlying or '').upper()
    action = str(action or '').upper()
    p, b, a, tick = _f(entry, -1), _f(bid, -1), _f(ask, -1), max(_f(tick_size, 0.01), 1e-9)
    if p <= 0 or b <= 0 or a <= 0 or a < b:
        return False, 'invalid two-sided quote', {}
    mid = (a + b) / 2.0
    spread = a - b
    spread_pct = spread / mid * 100.0 if mid > 0 else 999.0
    cap = SPREAD_CAP_PCT.get(underlying, 3.0)
    if spread_pct > cap + 1e-9:
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
            if _f(python_score, 0) < 90 or spread_pct > 2.0 + 1e-9 or d is None:
                return False, 'near-expiry requires score>=90, spread<=2%, valid delta', {'spread_pct': spread_pct, 'minutes_to_expiry': mte}

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
    """Calibrated 0-100 score. Call only after deterministic hard gates pass."""
    direction = str(snap.get('direction') or '').upper()
    tf = snap.get('tf') or {}; s1h=tf.get('1h') or {}; s15=tf.get('15m') or {}; s5=tf.get('5m') or {}
    score = 0.0

    if _directional_ok(direction, s1h, full_ema=True, min_adx=18): score += 10
    if _directional_ok(direction, s15, full_ema=True, min_adx=18): score += 10
    elif _directional_ok(direction, s15, full_ema=False, min_adx=18): score += 5

    if _directional_structure_ok(direction, str(snap.get('structure') or '')):
        score += 8
    elif snap.get('structure_relaxed'):
        score += 4

    cross = snap.get('ema_cross_5m') or {}
    if cross.get('bars_ago') in (0, 1):
        score += 7
    elif snap.get('momentum_mode') and _full_5m_stack(direction, s5):
        score += 5

    if snap.get('pattern') in {'BREAKOUT', 'RETEST', 'MOMENTUM_CONTINUATION'}:
        score += 5

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

    if not snap.get('overextended') and _f(snap.get('vwap_distance_atr')) <= 1.0:
        score += 5
    elif snap.get('impulse_extension'):
        score += 2

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
