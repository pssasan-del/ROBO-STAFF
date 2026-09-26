"""ROBO STAFF POLISH V1 entry-quality policy.

This module is intentionally conservative. It does not alter RR, premium SL,
AI behaviour, option selection, outcome monitoring, research persistence, or
order execution (the engine remains signal-only).

Policy basis: first research sample showed weak BTC BUY/SELL and ETH BUY,
while ETH SELL and GOLD did not justify broad tightening. Re-check after the
next research window before changing these thresholds again.
"""

POLISH_VERSION = "POLISH_V1_2026-09-26"


def evaluate_entry(underlying: str, action: str, snap: dict):
    """Return (allowed, reason).

    Existing core eligibility runs first. These are additive quality gates only.
    GOLD is deliberately unchanged. ETH SELL is deliberately unchanged.
    """
    und = str(underlying or "").upper()
    action = str(action or "").upper()
    score = int(snap.get("score") or 0)
    tf5 = (snap.get("tf") or {}).get("5m") or {}
    adx = float(tf5.get("adx") or 0.0)
    rvol = float(tf5.get("rel_volume") or 0.0)

    # BTC first sample was weak on both BUY and SELL. Require a cleaner trend
    # and participation instead of widening the existing 12% premium stop.
    if und == "BTC":
        if score < 79:
            return False, "BTC score<79"
        if adx < 22:
            return False, "BTC ADX<22"
        if rvol < 0.35:
            return False, "BTC RVOL<0.35"

    # ETH BUY was the weakest observed bucket. Tighten only that family.
    # ETH SELL is left on the original core rules until more samples arrive.
    if und == "ETH" and action == "OPTION BUY":
        if score < 82:
            return False, "ETH BUY score<82"
        if adx < 22:
            return False, "ETH BUY ADX<22"
        if rvol < 0.75:
            return False, "ETH BUY RVOL<0.75"

    return True, "PASS"
