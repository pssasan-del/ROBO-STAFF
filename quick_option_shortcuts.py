"""Single-letter Delta option-chain shortcuts for Telegram.

B -> BTC, E -> ETH, X -> XAUT/GOLD. Read-only public market data only.
This module does not place, modify, or cancel orders.
"""
from __future__ import annotations

from datetime import datetime

from config import logger
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service, IST

SHORTCUTS = {
    "b": {"label": "BTC", "ticker": "BTCUSD", "families": ("BTC",), "settle": "17:30"},
    "e": {"label": "ETH", "ticker": "ETHUSD", "families": ("ETH",), "settle": "17:30"},
    "x": {"label": "GOLD", "ticker": "XAUTUSD", "families": ("XAUT", "PAXG"), "settle": "21:30"},
}


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _fmt(v):
    x = _num(v)
    if x is None:
        return "-"
    if abs(x) >= 1000:
        return f"{x:,.2f}"
    if abs(x) >= 1:
        return f"{x:.2f}"
    if abs(x) >= 0.1:
        return f"{x:.3f}"
    return f"{x:.4f}"


def _premium(snapshot):
    """Display the executable BUY price first; mark price only as fallback."""
    if not snapshot:
        return None
    ask = _num(snapshot.get("best_ask"))
    if ask is not None and ask > 0:
        return ask
    mark = _num(snapshot.get("mark_price"))
    if mark is not None and mark > 0:
        return mark
    return None


async def _load_family(family: str):
    rows = await delta_options_service.get_chain(family)
    today = datetime.now(IST).date()
    parsed = []
    for row in rows:
        meta = delta_options_service.parse_symbol(row.get("symbol"))
        if not meta or meta.get("underlying") != family or meta.get("expiry") < today:
            continue
        parsed.append((row, meta))
    if not parsed:
        raise RuntimeError(f"No live {family} option contracts")
    expiry = min(meta["expiry"] for _, meta in parsed)
    return family, expiry, [(row, meta) for row, meta in parsed if meta["expiry"] == expiry]


async def build_quick_chain(letter: str) -> str:
    key = str(letter or "").strip().lower()
    cfg = SHORTCUTS.get(key)
    if not cfg:
        raise ValueError("Unknown option-chain shortcut")

    errors = []
    selected = None
    for family in cfg["families"]:
        try:
            selected = await _load_family(family)
            break
        except Exception as exc:
            errors.append(f"{family}: {exc}")
    if not selected:
        raise RuntimeError(" | ".join(errors) or "Option chain unavailable")

    family, expiry, rows = selected
    ticker = await delta_market_service.get_ticker(cfg["ticker"])
    spot = _num(ticker.get("price"))
    if spot is None:
        # Delta option rows normally contain spot_price; use it only if ticker is absent.
        for row, _ in rows:
            spot = _num(row.get("spot_price"))
            if spot is not None:
                break
    if spot is None:
        raise RuntimeError("Spot price unavailable")

    strikes = sorted({float(meta["strike"]) for _, meta in rows})
    if not strikes:
        raise RuntimeError("No strikes returned")
    atm = min(strikes, key=lambda s: abs(s - spot))
    idx = strikes.index(atm)
    lo = max(0, idx - 4)
    hi = min(len(strikes), lo + 9)
    lo = max(0, hi - 9)
    window = strikes[lo:hi]

    by_strike = {}
    for row, meta in rows:
        strike = float(meta["strike"])
        if strike not in window:
            continue
        snap = delta_options_service._snapshot(row)
        by_strike.setdefault(strike, {})[meta["side"]] = snap

    title = f"📊 *{cfg['label']} DELTA OPTIONS*"
    if cfg["label"] == "GOLD":
        title = f"📊 *GOLD DELTA OPTIONS* ({family})"
    expiry_text = expiry.strftime("%d-%m-%Y") + f" {cfg['settle']} IST"

    lines = [
        title,
        f"Spot: *{_fmt(spot)}*",
        f"ATM: *{_fmt(atm)}*",
        f"Expiry: *{expiry_text}*",
        "",
        "*CALL            STRIKE             PUT*",
    ]
    for strike in window:
        legs = by_strike.get(strike, {})
        call = _premium(legs.get("CE"))
        put = _premium(legs.get("PE"))
        marker = " ◀ ATM" if abs(strike - atm) < 1e-9 else ""
        lines.append(f"`{_fmt(call):>10}   {_fmt(strike):>12}   {_fmt(put):>10}`{marker}")

    lines.extend([
        "",
        "Premium = *best ask* when available, otherwise mark price.",
        "Read-only display; no order is placed.",
    ])
    logger.info("[QUICK_CHAIN] shortcut=%s family=%s spot=%s atm=%s expiry=%s", key.upper(), family, spot, atm, expiry)
    return "\n".join(lines)


def install_quick_option_shortcuts(agent):
    """Wrap MarketAgent.answer without changing its normal queries."""
    if getattr(agent, "quick_option_shortcuts_installed", False):
        return agent
    original = agent.answer

    async def answer(text):
        key = str(text or "").strip().lower()
        if key in SHORTCUTS:
            try:
                return await build_quick_chain(key)
            except Exception as exc:
                logger.warning("[QUICK_CHAIN] %s failed: %s", key.upper(), exc)
                return f"⚠️ {SHORTCUTS[key]['label']} option chain unavailable right now: {exc}"
        return await original(text)

    agent.answer = answer
    agent.quick_option_shortcuts_installed = True
    return agent
