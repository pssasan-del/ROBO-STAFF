"""Attach ROBO STAFF qualified alerts to the futures-only paper executor."""
from __future__ import annotations

from config import logger


def install_paper_robo_hook(engine, paper_robo):
    if getattr(engine, 'paper_robo_hook_installed', False):
        return engine
    original_alert = engine._alert

    async def alert_with_paper_robo(text):
        await original_alert(text)
        # Only fresh ROBO STAFF signal alerts can create a paper futures entry.
        # Outcome/research/SL messages never trigger an entry.
        if str(text or '').startswith('⚡ *ROBO STAFF'):
            c = getattr(engine, 'last_signal', None)
            if c is not None:
                try:
                    await paper_robo.on_signal(c)
                except Exception as exc:
                    logger.warning('[FUTURES_PAPER] signal hook failed safely: %s', exc)

    engine._alert = alert_with_paper_robo
    engine.paper_robo_hook_installed = True
    return engine
