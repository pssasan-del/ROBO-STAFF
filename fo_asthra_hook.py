"""Attach qualified ROBO STAFF OPTION BUY signals to F&O ASTHRA LIVE execution."""
from __future__ import annotations

from config import logger


def install_fo_asthra_hook(engine, asthra):
    if getattr(engine, "fo_asthra_hook_installed", False):
        return engine
    original_alert = engine._alert

    async def alert_with_asthra(text):
        await original_alert(text)
        c = getattr(engine, "last_signal", None)
        if c is not None and str(getattr(c, "action", "") or "").upper() == "OPTION BUY":
            try:
                await asthra.on_signal(c)
            except Exception as exc:
                logger.warning("[FO_ASTHRA] signal hook failed safely: %s", exc)

    engine._alert = alert_with_asthra
    engine.fo_asthra_hook_installed = True
    return engine
