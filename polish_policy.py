"""ROBO STAFF Delta Structure Breakout V3.2 — deterministic policy.

Signal-only strategy policy. No order execution methods live here.

2026-09-28 frequency-balance patch:
- preserves strict BREAKOUT / RETEST rules;
- preserves guarded MOMENTUM_CONTINUATION and SCALP_CONTINUATION;
- adds a BIAS_SCALP / COUNTERTREND_SCALP research path when the old snapshot
  reports MIXED but 15m+5m+1m (or 1h+5m+1m) provide a usable directional bias;
- relaxes the 1m trigger only to EMA/DI micro-confirmation for scalp research;
- keeps option quote quality, delta/expiry, dynamic SL, cooldown/correlation and
  SIGNAL-ONLY protections intact.

The engine aims for a usable research sample (roughly 3+ opportunities/day on
active sessions) but never fabricates a signal simply to satisfy a quota.
"""
from __future__ import annotations

import math

POLISH_VERSION = "FRESH_V3.2_2026-09-27"
MODE_REVISION = "FREQUENCY_BALANCED_SCALP_2026-09-28"
MIN_ALERT_SCORE = 78
STRONG_SCORE = 90
ELITE_SCORE = 95
DAILY_RESEARCH_TARGET = 3

SPREAD_CAP_PCT = {"BTC": 2.5, "ETH": 3.0, "GOLD": 4.0}
DAILY_SIGNAL_CAP = {"BTC": 6, "ETH": 6, "GOLD": 4}
RVOL_MIN = {"BTC": 1.10, "ETH": 1.10, "GOLD": 1.00}
MOMENTUM_RVOL_MIN = {"BTC": 0.85, "ETH": 0.85, "GOLD": 0.75}
SCALP_RVOL_MIN = {"BTC": 0.70, "ETH": 0.70, "GOLD": 0.65}
BIAS_RVOL_MIN = {"BTC": 0.50, "ETH": 0.50, "GOLD": 0.45}
IMPULSE_RVOL_MIN = {"BTC": 1.10, "ETH": 1.10, "GOLD": 0.95}
PREMIUM_SPOT_CAP = {"BTC": 0.0075, "ETH": 0.0075, "GOLD": 0.0100}
BASE_COOLDOWN_MINUTES = 15
SUCCESS_COOLDOWN_MINUTES = 10
FAIL_COOLDOWN_MINUTES = 20
CONTRACT_COOLDOWN_MINUTES = 20
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


def _scalp_pivot_ok(direction: str, daily_zone: str, five_zone: str) -> bool:
    """For scalp research, 5m pivot must agree; Daily must not be extreme opposite."""
    if direction == 'BULLISH':
        return five_zone in {'PIVOT_TO_R1', 'ABOVE_R1'} and daily_zone != 'BELOW_S1'
    if direction == 'BEARISH':
        return five_zone in {'S1_TO_PIVOT', 'BELOW_S1'} and daily_zone != 'ABOVE_R1'
    return False


def _full_5m_stack(direction: str, s5: dict) -> bool:
    px, e5, e9, e20 = (_f(s5.get(k)) for k in ('price', 'ema5', 'ema9', 'ema20'))
    if direction == 'BULLISH':
        return px > e5 > e9 > e20
    if direction == 'BEARISH':
        return px < e5 < e9 < e20
    return False


def _micro_trigger(direction: str, s1: dict) -> bool:
    """Lightweight 1m confirmation used only for scalp research.

    It does not require a new 3-bar breakout; it requires price/EMA5/EMA9 and DI
    to agree on the latest completed 1m state. This specifically fixes the old
    '1m execution trigger failed' dead-zone during smooth trend resumption.
    """
    px, e5, e9 = (_f(s1.get(k)) for k in ('price', 'ema5', 'ema9'))
    pdi, mdi = _f(s1.get('plus_di')), _f(s1.get('minus_di'))
    adx = _f(s1.get('adx'))
    if direction == 'BULLISH':
        return px > e5 > e9 and pdi > mdi and adx >= 8
    if direction == 'BEARISH':
        return px < e5 < e9 and mdi > pdi and adx >= 8
    return False


def _di_ratio(direction: str, state: dict) -> float:
    pdi, mdi = _f(state.get('plus_di')), _f(state.get('minus_di'))
    return (pdi / max(mdi, 1.0)) if direction == 'BULLISH' else (mdi / max(pdi, 1.0))


def _strong_opposite(direction: str, state: dict) -> bool:
    opposite = 'BEARISH' if direction == 'BULLISH' else 'BULLISH'
    return _directional_ok(opposite, state, full_ema=True, min_adx=22) and _di_ratio(opposite, state) >= 1.20


def _infer_mixed_bias(underlying: str, snap: dict):
    """Infer a scalp-only direction when snapshot direction is MIXED.

    Preferred route is 15m+5m+1m agreement with 1h only acting as a veto. A
    controlled countertrend route is allowed only when 5m force is materially
    stronger. A second fallback uses 1h+5m+1m when 15m is merely neutral.
    """
    tf = snap.get('tf') or {}
    s1 = tf.get('1m') or {}; s5 = tf.get('5m') or {}; s15 = tf.get('15m') or {}; s1h = tf.get('1h') or {}

    for direction in ('BULLISH', 'BEARISH'):
        if not _full_5m_stack(direction, s5) or not _micro_trigger(direction, s1):
            continue
        fifteen = _directional_ok(direction, s15, full_ema=False, min_adx=12)
        onehour = _directional_ok(direction, s1h, full_ema=True, min_adx=14)
        opp_15 = _strong_opposite(direction, s15)
        opp_1h = _strong_opposite(direction, s1h)
        adx5 = _f(s5.get('adx')); ratio5 = _di_ratio(direction, s5); rvol5 = _f(s5.get('rel_volume'))

        if fifteen and not opp_1h:
            return direction, False, '15m+5m+1m bias; 1h not strongly opposite'

        # Countertrend scalp: only when local force is strong enough to justify
        # a short-duration research alert against the 1h stack.
        counter_rvol = 0.80 if underlying != 'GOLD' else 0.70
        if fifteen and opp_1h and adx5 >= 24 and ratio5 >= 1.30 and rvol5 >= counter_rvol:
            return direction, True, 'countertrend 15m+5m+1m impulse against 1h'

        # 15m can lag during fast reversals. 1h+5m+1m is accepted only if 15m
        # is not strongly opposite.
        if onehour and not opp_15:
            return direction, False, '1h+5m+1m bias; 15m neutral/not strongly opposite'

    return None, False, 'no directional bias from mixed state'


def _continuation_breakout_ok(direction: str, snap: dict) -> bool:
    px = _f(snap.get('last_closed_5m'))
    level = _f(snap.get('breakout_level'))
    if px <= 0 or level <= 0:
        return False
    return px > level if direction == 'BULLISH' else px < level


def _compression(s5: dict) -> bool:
    px = max(_f(s5.get('price')), 1e-9)
    e5, e20, rvol = _f(s5.get('ema5')), _f(s5.get('ema20')), _f(s5.get('rel_volume'))
    return abs(e5 - e20) / px < 0.00035 and rvol < 0.90


def _rewrite_setup_id(snap: dict, direction: str, pattern: str):
    sid = str(snap.get('setup_id') or '')
    parts = sid.split(':')
    if len(parts) >= 4:
        parts[1] = direction
        parts[2] = pattern
        snap['setup_id'] = ':'.join(parts)
    else:
        snap['setup_id'] = f"{snap.get('symbol','UNK')}:{direction}:{pattern}:{sid}"


def _mark_momentum_pattern(snap: dict, *, pattern='MOMENTUM_CONTINUATION', relaxed_structure=False, impulse=False):
    snap['pattern'] = pattern
    snap['momentum_mode'] = True
    snap['scalp_mode'] = pattern in {'SCALP_CONTINUATION', 'BIAS_SCALP', 'COUNTERTREND_SCALP'}
    snap['structure_relaxed'] = bool(relaxed_structure)
    snap['impulse_extension'] = bool(impulse)
    _rewrite_setup_id(snap, str(snap.get('direction') or 'MIXED'), pattern)


def evaluate_entry(underlying: str, action: str, snap: dict):
    """V3.2 deterministic gates with frequency-balanced scalp research.

    Priority order:
    1) strict BREAKOUT/RETEST;
    2) mature MOMENTUM_CONTINUATION;
    3) SCALP_CONTINUATION;
    4) BIAS_SCALP / COUNTERTREND_SCALP when old snapshot direction is MIXED.
    """
    underlying = str(underlying or '').upper()
    tf = snap.get('tf') or {}
    s1 = tf.get('1m') or {}; s5 = tf.get('5m') or {}; s15 = tf.get('15m') or {}; s1h = tf.get('1h') or {}

    direction = str(snap.get('direction') or '').upper()
    bias_scalp = False
    countertrend = False

    if direction not in {'BULLISH', 'BEARISH'}:
        inferred, countertrend, bias_reason = _infer_mixed_bias(underlying, snap)
        if inferred is None:
            return False, f'mixed direction: {bias_reason}'
        direction = inferred
        snap['direction'] = direction
        snap['bias_scalp_mode'] = True
        snap['countertrend_bias'] = bool(countertrend)
        snap['bias_reason'] = bias_reason
        snap['price_ema_aligned'] = _full_5m_stack(direction, s5)
        snap['one_min_trigger'] = _micro_trigger(direction, s1)
        snap['one_min_ema_hold'] = snap['one_min_trigger']
        snap['micro_trigger'] = snap['one_min_trigger']
        pattern = 'COUNTERTREND_SCALP' if countertrend else 'BIAS_SCALP'
        _mark_momentum_pattern(snap, pattern=pattern, relaxed_structure=True, impulse=False)
        bias_scalp = True

    # For already directional snapshots, allow a micro 1m trend-resumption
    # confirmation when the old breakout/hold trigger is false.
    if direction in {'BULLISH', 'BEARISH'} and not snap.get('one_min_trigger') and _micro_trigger(direction, s1):
        snap['one_min_trigger'] = True
        snap['one_min_ema_hold'] = True
        snap['micro_trigger'] = True

    if not snap.get('price_ema_aligned'):
        snap['price_ema_aligned'] = _full_5m_stack(direction, s5)
    if not snap.get('price_ema_aligned'):
        return False, '5m price/EMA alignment failed'
    if not snap.get('one_min_trigger'):
        return False, '1m execution/micro trigger failed'

    structure = str(snap.get('structure') or '')
    structure_strict = _directional_structure_ok(direction, structure)
    adx = _f(s5.get('adx')); di_ratio = _di_ratio(direction, s5); rvol = _f(s5.get('rel_volume'))
    daily_zone, five_zone = str(snap.get('daily_zone') or ''), str(snap.get('five_zone') or '')

    # Frequency-balanced mixed-direction scalp path.
    if bias_scalp:
        if not _scalp_pivot_ok(direction, daily_zone, five_zone):
            return False, 'bias scalp pivot alignment failed'
        min_rvol = BIAS_RVOL_MIN.get(underlying, 0.50)
        if countertrend:
            ctr_rvol = 0.80 if underlying != 'GOLD' else 0.70
            if adx < 24 or di_ratio < 1.30 or rvol < ctr_rvol:
                return False, f'countertrend scalp force weak ({adx:.1f}/{di_ratio:.2f}/{rvol:.2f})'
        else:
            if adx < 18:
                return False, f'bias scalp ADX<18 ({adx:.1f})'
            if di_ratio < 1.08:
                return False, f'bias scalp DI ratio<1.08 ({di_ratio:.2f})'
            if rvol < min_rvol:
                return False, f'bias scalp RVOL<{min_rvol:.2f} ({rvol:.2f})'

        vwap_atr = _f(snap.get('vwap_distance_atr'))
        ema9_atr = _f(snap.get('ema9_distance_atr'))
        if vwap_atr > 2.50 or ema9_atr > 1.15:
            return False, f'bias scalp overextended VWAP/EMA9 {vwap_atr:.2f}/{ema9_atr:.2f} ATR'
        if not structure_strict and adx < (22 if countertrend else 20):
            return False, f'bias scalp structure weak with ADX {adx:.1f}'
        # Do not rely on distance_to_next_pivot_atr here because the legacy
        # snapshot calculated that metric before MIXED direction was resolved.
        rsi5, wr5 = _f(s5.get('rsi')), _f(s5.get('williams_r'))
        if direction == 'BULLISH' and (rsi5 > 88 or wr5 > -1):
            return False, 'bias bullish momentum exhausted'
        if direction == 'BEARISH' and (rsi5 < 12 or wr5 < -99):
            return False, 'bias bearish momentum exhausted'
        return True, 'V3.2_COUNTERTREND_SCALP_PASS' if countertrend else 'V3.2_BIAS_SCALP_PASS'

    # Normal directional paths retain HTF sanity checks.
    if not _directional_ok(direction, s1h, full_ema=True, min_adx=16):
        return False, '1H alignment failed'
    if not _directional_ok(direction, s15, full_ema=False, min_adx=16):
        return False, '15m alignment failed'

    cross = snap.get('ema_cross_5m') or {}
    bars_ago = cross.get('bars_ago')
    cross_side = str(cross.get('side') or '').upper()
    pattern = str(snap.get('pattern') or '')
    fresh_path = cross_side == direction and bars_ago in (0, 1) and (
        (bars_ago == 0 and pattern == 'BREAKOUT') or
        (bars_ago == 1 and pattern == 'RETEST')
    )

    if fresh_path:
        if not _pivot_side_ok(direction, daily_zone, five_zone):
            return False, 'fresh Daily/5m pivot side opposes direction'
        if not structure_strict:
            return False, f'{direction.lower()} fresh structure invalid'
        if snap.get('choppy'):
            return False, 'fresh setup choppy/compressed'
        if snap.get('overextended'):
            return False, 'fresh setup overextended from VWAP/EMA9'
        # If the strict 1m trigger was replaced by micro confirmation, ask for a
        # slightly stronger 5m tape before accepting a fresh breakout.
        min_adx = 23 if snap.get('micro_trigger') else 21
        if adx < min_adx:
            return False, f'5m ADX<{min_adx}'
        if di_ratio < 1.15:
            return False, '5m DI ratio<1.15'
        if rvol < RVOL_MIN.get(underlying, 1.10):
            return False, f'5m RVOL<{RVOL_MIN.get(underlying, 1.10):.2f}'
        if _f(snap.get('distance_to_next_pivot_atr')) < 0.60:
            return False, 'insufficient room to next pivot/swing'
        if _f(snap.get('breakout_extension_atr')) > 0.90:
            return False, 'late breakout extension>0.90 ATR'
    else:
        if not _full_5m_stack(direction, s5):
            return False, 'no fresh cross and no full 5m continuation stack'
        if _compression(s5):
            return False, 'momentum EMA5/20 compression'
        if not _scalp_pivot_ok(direction, daily_zone, five_zone):
            return False, 'scalp pivot alignment failed'

        vwap_atr = _f(snap.get('vwap_distance_atr'))
        ema9_atr = _f(snap.get('ema9_distance_atr'))
        ext_atr = _f(snap.get('breakout_extension_atr'))
        room_atr = _f(snap.get('distance_to_next_pivot_atr'))
        cleared_5m_breakout = _continuation_breakout_ok(direction, snap)

        if cleared_5m_breakout:
            if adx < 23:
                return False, f'momentum ADX<23 ({adx:.1f})'
            if di_ratio < 1.22:
                return False, f'momentum DI ratio<1.22 ({di_ratio:.2f})'
            if rvol < MOMENTUM_RVOL_MIN.get(underlying, 0.85):
                return False, f'momentum RVOL<{MOMENTUM_RVOL_MIN.get(underlying, 0.85):.2f} ({rvol:.2f})'

            relaxed_structure = False
            if not structure_strict:
                soft_rvol = max(MOMENTUM_RVOL_MIN.get(underlying, 0.85), 0.90 if underlying != 'GOLD' else 0.80)
                if adx < 25 or di_ratio < 1.30 or rvol < soft_rvol:
                    return False, (
                        f'{direction.lower()} structure soft-fail; needs '
                        f'ADX>=25/DI>=1.30/RVOL>={soft_rvol:.2f} '
                        f'(got {adx:.1f}/{di_ratio:.2f}/{rvol:.2f})'
                    )
                relaxed_structure = True

            normal_extension = (
                vwap_atr <= 2.00 and ema9_atr <= 0.90 and
                ext_atr <= 0.80 and room_atr >= 0.45
            )
            impulse_rvol = IMPULSE_RVOL_MIN.get(underlying, 1.10)
            impulse_strength = adx >= 29 and di_ratio >= 1.40 and rvol >= impulse_rvol
            impulse_extension = (
                impulse_strength and vwap_atr <= 2.60 and ema9_atr <= 1.20 and
                ext_atr <= 1.00 and room_atr >= 0.55
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
                pattern='MOMENTUM_CONTINUATION',
                relaxed_structure=relaxed_structure,
                impulse=(not normal_extension and impulse_extension),
            )
        else:
            if adx < 21:
                return False, f'scalp ADX<21 ({adx:.1f})'
            if di_ratio < 1.15:
                return False, f'scalp DI ratio<1.15 ({di_ratio:.2f})'
            if rvol < SCALP_RVOL_MIN.get(underlying, 0.70):
                return False, f'scalp RVOL<{SCALP_RVOL_MIN.get(underlying, 0.70):.2f} ({rvol:.2f})'
            if not structure_strict and (adx < 24 or di_ratio < 1.25):
                return False, f'scalp soft structure needs ADX>=24/DI>=1.25 ({adx:.1f}/{di_ratio:.2f})'
            if vwap_atr > 2.20 or ema9_atr > 1.00:
                return False, f'scalp overextension VWAP/EMA9 {vwap_atr:.2f}/{ema9_atr:.2f} ATR'
            if room_atr < 0.35:
                return False, f'scalp room<0.35ATR ({room_atr:.2f})'
            if ext_atr > 1.10:
                return False, f'scalp late/chasing >1.10ATR ({ext_atr:.2f})'
            _mark_momentum_pattern(
                snap,
                pattern='SCALP_CONTINUATION',
                relaxed_structure=not structure_strict,
                impulse=False,
            )

    rsi5, wr5 = _f(s5.get('rsi')), _f(s5.get('williams_r'))
    if direction == 'BULLISH' and (rsi5 > 86 or wr5 > -1):
        return False, 'bullish momentum exhausted'
    if direction == 'BEARISH' and (rsi5 < 14 or wr5 < -99):
        return False, 'bearish momentum exhausted'

    if snap.get('scalp_mode'):
        return True, 'V3.2_SCALP_RESEARCH_PASS'
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
    """Calibrated 0-100 score. Call after deterministic gates pass."""
    direction = str(snap.get('direction') or '').upper()
    tf = snap.get('tf') or {}; s1=tf.get('1m') or {}; s1h=tf.get('1h') or {}; s15=tf.get('15m') or {}; s5=tf.get('5m') or {}
    score = 0.0

    if _directional_ok(direction, s1h, full_ema=True, min_adx=16): score += 10
    if _directional_ok(direction, s15, full_ema=True, min_adx=16): score += 10
    elif _directional_ok(direction, s15, full_ema=False, min_adx=12): score += 5

    if _directional_structure_ok(direction, str(snap.get('structure') or '')):
        score += 8
    elif snap.get('structure_relaxed'):
        score += 4

    cross = snap.get('ema_cross_5m') or {}
    if cross.get('bars_ago') in (0, 1) and str(cross.get('side') or '').upper() == direction:
        score += 7
    elif (snap.get('momentum_mode') or snap.get('bias_scalp_mode')) and _full_5m_stack(direction, s5):
        score += 5

    if snap.get('pattern') in {'BREAKOUT', 'RETEST', 'MOMENTUM_CONTINUATION', 'SCALP_CONTINUATION', 'BIAS_SCALP', 'COUNTERTREND_SCALP'}:
        score += 5

    adx, rvol = _f(s5.get('adx')), _f(s5.get('rel_volume'))
    score += 7 if adx >= 28 else (5 if adx >= 24 else 3)
    ratio = _di_ratio(direction, s5)
    score += 4 if ratio >= 1.35 else 2
    score += 4 if rvol >= 1.50 else (3 if rvol >= 1.10 else 1)

    ideal_daily = snap.get('daily_zone') == ('PIVOT_TO_R1' if direction == 'BULLISH' else 'S1_TO_PIVOT')
    ideal_five = snap.get('five_zone') == ('PIVOT_TO_R1' if direction == 'BULLISH' else 'S1_TO_PIVOT')
    if ideal_daily: score += 7
    elif snap.get('pivot_extension_valid'): score += 4
    if ideal_five: score += 5
    elif snap.get('pivot_extension_valid'): score += 3
    if not snap.get('bias_scalp_mode') and _f(snap.get('distance_to_next_pivot_atr')) >= 0.75:
        score += 3

    if snap.get('one_min_breakout'): score += 6
    if snap.get('one_min_ema_hold'): score += 4
    if snap.get('micro_trigger') and _micro_trigger(direction, s1): score += 6

    if not snap.get('overextended') and _f(snap.get('vwap_distance_atr')) <= 1.25:
        score += 5
    elif snap.get('impulse_extension'):
        score += 2
    elif snap.get('scalp_mode') and _f(snap.get('vwap_distance_atr')) <= 2.20:
        score += 2

    rsi5, wr5 = _f(s5.get('rsi')), _f(s5.get('williams_r'))
    if direction == 'BULLISH':
        if 42 <= rsi5 <= 76: score += 3
        if -85 <= wr5 <= -8: score += 2
    else:
        if 24 <= rsi5 <= 58: score += 3
        if -92 <= wr5 <= -15: score += 2

    # Mixed-state bias scalps lose the old 1H alignment points by design, so a
    # bounded bonus represents the independent 15m+5m+1m confluence. Countertrend
    # alerts get a smaller bonus and are capped below STRONG quality.
    if snap.get('bias_scalp_mode'):
        score += 10 if snap.get('countertrend_bias') else 16

    score += max(0.0, min(10.0, _f(contract_score)))
    score = max(0.0, min(100.0, score))
    if snap.get('countertrend_bias'):
        score = min(score, 84.0)
    elif snap.get('bias_scalp_mode'):
        score = min(score, 89.0)
    return int(round(score))


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
