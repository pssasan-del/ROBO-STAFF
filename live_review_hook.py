"""Attach fresh ROBO STAFF alerts to the manual live-review gate."""
from __future__ import annotations

from config import logger


def install_live_review_hook(engine, review_gate):
    if getattr(engine, 'live_review_hook_installed', False):
        return engine
    original_alert = engine._alert

    async def alert_with_live_review(text):
        await original_alert(text)
        if str(text or '').startswith('⚡ *ROBO STAFF'):
            c = getattr(engine, 'last_signal', None)
            if c is not None:
                try:
                    await review_gate.on_signal(c)
                except Exception as exc:
                    logger.warning('[LIVE_REVIEW] signal hook failed safely: %s', exc)

    engine._alert = alert_with_live_review
    engine.live_review_hook_installed = True
    return engine
