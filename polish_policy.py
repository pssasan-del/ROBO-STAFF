"""ROBO STAFF FRESH V3.1 research policy.

V3.1 starts a clean research/statistics epoch after the first V3 live samples
showed very fast SL hits.  The engine remains SIGNAL ONLY; this module only
filters setup/contract quality and never places orders.
"""

import time

POLISH_VERSION = "FRESH_V3.1_2026-09-27"


def _last_5m_bar_closed(snap: dict) -> bool:
    """Infer whether the last candle in the Delta history response is closed.

    Delta history can include the currently forming candle. setup_id ends with
    that candle's start timestamp, so we can avoid treating an intrabar EMA
    cross as a completed 5-minute crossover.
    """
    try:
        stamp = str(snap.get('setup_id') or '').rsplit(':', 1)[-1]
        ts = float(stamp)
        if ts > 100_000_000_000:  # milliseconds -> seconds
            ts /= 1000.0
        if ts < 1_000_000_000:
            return False
        return time.time() >= ts + 300.0 + 2.0
    except (TypeError, ValueError):
        return False


def evaluate_entry(underlying: str, action: str, snap: dict):
    """Strict V3.1 setup gate using only deterministic market data.

    Core intent:
    - crossover must belong to the latest completed 5m candle, never a live bar;
    - price/EMA structure, 5m DI/ADX and RVOL must confirm direction;
    - both Daily and 5m Fib-pivot locations must agree with the trade direction;
    - 15m/1h must not actively oppose the setup.
    """
    direction = str(snap.get('direction') or '').upper()
    cross = snap.get('ema_cross_5m') or {}
    bars_ago = cross.get('bars_ago')
    last_closed = _last_5m_bar_closed(snap)

    # If Delta includes a live 5m candle, the newest completed candle is 1 bar
    # ago. If the endpoint already ends on a completed candle, it is bar 0.
    required_bar = 0 if last_closed else 1
    if bars_ago != required_bar or str(cross.get('side') or '').upper() != direction:
        return False, f"wait closed 5m EMA5/9 cross (need {required_bar}b)"

    if not snap.get('price_ema_aligned'):
        return False, "price/EMA5/EMA9 not aligned"

    tf = snap.get('tf') or {}
    s5 = tf.get('5m') or {}
    s15 = tf.get('15m') or {}
    s1h = tf.get('1h') or {}
    try:
        adx = float(s5.get('adx') or 0)
        rvol = float(s5.get('rel_volume') or 0)
        pdi = float(s5.get('plus_di') or 0)
        mdi = float(s5.get('minus_di') or 0)
    except (TypeError, ValueError):
        return False, "invalid 5m confirmation data"

    if adx < 22:
        return False, "5m ADX<22"
    if rvol < 0.80:
        return False, "5m RVOL<0.80"

    structure = str(snap.get('structure') or '')
    daily_zone = str(snap.get('daily_zone') or '')
    five_zone = str(snap.get('five_zone') or '')
    trend15 = str(s15.get('trend') or '')
    trend1h = str(s1h.get('trend') or '')

    if direction == 'BULLISH':
        if pdi <= mdi:
            return False, "5m +DI not above -DI"
        if structure != 'HH/HL':
            return False, "bullish structure not HH/HL"
        if daily_zone not in {'PIVOT_TO_R1', 'ABOVE_R1'}:
            return False, "bullish price below Daily Pivot"
        if five_zone not in {'PIVOT_TO_R1', 'ABOVE_R1'}:
            return False, "bullish price below 5m Pivot"
        if trend15 == 'BEARISH' or trend1h == 'BEARISH':
            return False, "higher timeframe opposes bullish setup"
    elif direction == 'BEARISH':
        if mdi <= pdi:
            return False, "5m -DI not above +DI"
        if structure != 'LH/LL':
            return False, "bearish structure not LH/LL"
        if daily_zone not in {'S1_TO_PIVOT', 'BELOW_S1'}:
            return False, "bearish price above Daily Pivot"
        if five_zone not in {'S1_TO_PIVOT', 'BELOW_S1'}:
            return False, "bearish price above 5m Pivot"
        if trend15 == 'BULLISH' or trend1h == 'BULLISH':
            return False, "higher timeframe opposes bearish setup"
    else:
        return False, "mixed direction"

    if int(snap.get('score') or 0) < 80:
        return False, "Python score<80"

    return True, "FRESH_V3.1_STRICT_ENTRY"


def evaluate_contract(premium, *, tick_size=None, bid=None, ask=None):
    """Reject dust, one-sided, wide-spread and noise-dominated option quotes."""
    try:
        p = float(premium)
        b = float(bid) if bid is not None else None
        a = float(ask) if ask is not None else None
    except (TypeError, ValueError):
        return False, "invalid premium/bid/ask"

    if p <= 0:
        return False, "non-positive premium"
    if b is None or a is None or b <= 0 or a <= 0 or a < b:
        return False, "no valid two-sided quote"

    mid = (a + b) / 2.0
    spread = a - b
    spread_pct = spread / mid if mid > 0 else 1.0
    if spread_pct > 0.04:
        return False, "spread>4%"

    try:
        tick = float(tick_size) if tick_size is not None else 0.01
    except (TypeError, ValueError):
        tick = 0.01
    if tick <= 0:
        tick = 0.01

    # Explicitly remove low-premium contracts where one/two ticks dominate the
    # entire 12% risk budget. The dynamic tick/spread test below is stricter.
    if p < 0.25 or b < 0.20:
        return False, "premium too small for stable execution"

    sl_distance = p * 0.12
    t1_distance = sl_distance * 1.85
    if sl_distance < max(4.0 * tick, 3.0 * spread):
        return False, "12% SL inside execution noise"
    if t1_distance < max(4.0 * tick, 2.0 * spread):
        return False, "T1 inside execution noise"

    return True, "TRADEABLE_TWO_SIDED_V31"
