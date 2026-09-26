"""ROBO STAFF FRESH V2 research policy.

Fresh epoch: do not tune from the old success/fail buckets.  The live engine
remains signal-only.  V2 focuses on entry timing and executable contracts.
"""

POLISH_VERSION = "FRESH_V2_2026-09-26"


def evaluate_entry(underlying: str, action: str, snap: dict):
    """Return (allowed, reason) for the underlying setup.

    V2 deliberately removes the V1 BTC/ETH thresholds that were fitted to the
    old result buckets.  Existing core eligibility still runs before this hook.
    EMA/pivot observations are research variables until enough fresh samples
    exist; they must not be converted into arbitrary hard thresholds here.
    """
    return True, "FRESH_V2_RESEARCH"


def evaluate_contract(premium, *, tick_size=None, bid=None, ask=None):
    """Reject obviously non-executable/tiny option contracts.

    The previous 0.01 -> near-zero target case is not a valid 1:1.85 trade.
    A premium must leave enough tick room for the existing 12% stop and
    1.85R first target.  When a tick size is supplied, use it; otherwise apply
    a conservative absolute floor so 0.01-style contracts cannot become
    Telegram trade signals or contaminate fresh performance statistics.
    """
    try:
        p = float(premium)
    except (TypeError, ValueError):
        return False, "invalid premium"
    if p <= 0:
        return False, "non-positive premium"

    try:
        tick = float(tick_size) if tick_size is not None else 0.0
    except (TypeError, ValueError):
        tick = 0.0

    # Existing engine geometry: 12% premium SL and T1 at 1.85R.
    sl_distance = p * 0.12
    t1_distance = sl_distance * 1.85
    min_tick = tick if tick > 0 else 0.01

    # Require meaningful executable room, not a target collapsed to ~zero.
    if p < 0.05:
        return False, "premium<0.05 non-tradeable"
    if sl_distance < min_tick or t1_distance < min_tick:
        return False, "SL/T1 below executable tick room"

    # If live bid/ask are available, reject pathological spreads.  Missing
    # quotes are not fabricated; the caller can continue its existing logic.
    try:
        b = float(bid) if bid is not None else None
        a = float(ask) if ask is not None else None
        if b is not None and a is not None and b > 0 and a >= b:
            mid = (a + b) / 2.0
            if mid > 0 and (a - b) / mid > 0.20:
                return False, "spread>20%"
    except (TypeError, ValueError):
        pass

    return True, "TRADEABLE"
