"""Telegram controls for the manual AUTO TRADE PREP gate."""
from __future__ import annotations

from live_review_gate import live_review_gate


def install_live_review_controls(telegram_bot):
    if getattr(telegram_bot, 'live_review_controls_installed', False):
        return telegram_bot

    original_kb = telegram_bot.kb
    original_process_text = telegram_bot.process_text

    def kb_with_live_review():
        kb = original_kb()
        rows = list(kb.get('keyboard') or [])
        label = '🤖 AUTO TRADE PREP ON' if live_review_gate.armed else '🤖 AUTO TRADE PREP OFF'
        rows.insert(max(0, len(rows)-1), [{'text': label}, {'text':'📋 READY TICKET'}])
        kb['keyboard'] = rows
        return kb

    async def process_text_with_live_review(uid, chat, text):
        t = str(text or '').strip().lower()
        if t in {
            '🤖 auto trade prep off','auto trade prep on','auto prep on',
            '🟠 live review off','live review on','live gate on'
        }:
            msg = await live_review_gate.arm()
            return await telegram_bot.send(chat, msg, kb_with_live_review())
        if t in {
            '🤖 auto trade prep on','auto trade prep off','auto prep off',
            '🟠 live review on','live review off','live gate off'
        }:
            msg = await live_review_gate.disarm()
            return await telegram_bot.send(chat, msg, kb_with_live_review())
        if t in {'📋 ready ticket','ready ticket','auto prep status','📋 live ticket','live ticket','live review status'}:
            return await telegram_bot.send(chat, live_review_gate.status_text(), kb_with_live_review())
        if t in {'clear ready ticket','clear live ticket','live clear','auto prep clear'}:
            msg = await live_review_gate.clear()
            return await telegram_bot.send(chat, msg, kb_with_live_review())
        return await original_process_text(uid, chat, text)

    telegram_bot.kb = kb_with_live_review
    telegram_bot.process_text = process_text_with_live_review
    telegram_bot.live_review_controls_installed = True
    return telegram_bot
