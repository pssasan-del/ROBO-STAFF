"""ROBO STAFF FRESH V2 research policy.

Fresh epoch: do not tune from the old success/fail buckets. Live engine remains
signal-only. V2 focuses on entry timing and genuinely executable contracts.
"""

POLISH_VERSION = "FRESH_V2.1_2026-09-27"


def evaluate_entry(underlying: str, action: str, snap: dict):
    """Underlying setup gate. Old V1 W/L buckets are deliberately not reused."""
    return True, "FRESH_V2_RESEARCH"


def evaluate_contract(premium, *, tick_size=None, bid=None, ask=None):
    """Reject tiny, one-sided, wide-spread or noise-dominated option quotes.

    This is a signal/research quality gate, not an order function.  The 12% SL
    must be meaningfully wider than the live bid/ask friction; otherwise a
    signal can appear to hit SL immediately simply because the reference quote
    was stale or the book was too wide.
    """
    try:
        p = float(premium)
    except (TypeError, ValueError):
        return False, "invalid premium"
    if p <= 0:
        return False, "non-positive premium"

    try:
        b = float(bid) if bid is not None else None
        a = float(ask) if ask is not None else None
    except (TypeError, ValueError):
        return False, "invalid bid/ask"

    # Fresh research must be based on a real two-sided market.  Do not grade a
    # contract from last-trade/mark alone.
    if b is None or a is None or b <= 0 or a <= 0 or a < b:
        return False, "no valid two-sided quote"

    mid = (a + b) / 2.0
    spread = a - b
    spread_pct = spread / mid if mid > 0 else 1.0
    if spread_pct > 0.08:
        return False, "spread>8%"

    try:
        tick = float(tick_size) if tick_size is not None else 0.01
    except (TypeError, ValueError):
        tick = 0.01
    if tick <= 0:
        tick = 0.01

    # Absolute dust protection remains, but the important test is whether the
    # planned 12% stop has enough room beyond spread/tick microstructure noise.
    if p < 0.05:
        return False, "premium<0.05 non-tradeable"
    sl_distance = p * 0.12
    t1_distance = sl_distance * 1.85
    if sl_distance < max(3.0 * tick, 1.5 * spread):
        return False, "12% SL inside spread/tick noise"
    if t1_distance < max(3.0 * tick, spread):
        return False, "T1 inside spread/tick noise"

    return True, "TRADEABLE_TWO_SIDED"
