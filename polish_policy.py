"""ROBO STAFF FRESH V3 research policy.

Fresh V3 intentionally starts a new research/statistics epoch.  Old V1/V2
results are not reused for tuning.  The engine remains SIGNAL ONLY.
"""

POLISH_VERSION = "FRESH_V3_2026-09-27"


def evaluate_entry(underlying: str, action: str, snap: dict):
    """Underlying setup gate. Old W/L buckets are deliberately not reused."""
    return True, "FRESH_V3_RESEARCH"


def evaluate_contract(premium, *, tick_size=None, bid=None, ask=None):
    """Reject tiny, one-sided, wide-spread or noise-dominated option quotes.

    The planned 12% premium stop must have meaningful room beyond live
    bid/ask friction.  This prevents stale/dust contracts and false immediate
    SL outcomes from contaminating Fresh V3 research.
    """
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

    # Fresh V3 is deliberately stricter than V2.  A 12% SL should not be
    # mostly consumed by the bid/ask spread before the trade even moves.
    if spread_pct > 0.06:
        return False, "spread>6%"

    try:
        tick = float(tick_size) if tick_size is not None else 0.01
    except (TypeError, ValueError):
        tick = 0.01
    if tick <= 0:
        tick = 0.01

    # Avoid dust/near-zero option premiums.  These can show mathematically
    # attractive RR while being practically non-executable.
    if p < 0.10 or b < 0.05:
        return False, "tiny premium non-tradeable"

    sl_distance = p * 0.12
    t1_distance = sl_distance * 1.85
    if sl_distance < max(3.0 * tick, 2.0 * spread):
        return False, "12% SL too close to spread/tick noise"
    if t1_distance < max(3.0 * tick, 1.5 * spread):
        return False, "T1 too close to spread/tick noise"

    return True, "TRADEABLE_TWO_SIDED_V3"
