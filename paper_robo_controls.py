"""Telegram controls for the futures-only paper ROBO."""
from __future__ import annotations

from futures_paper_robo import futures_paper_robo


def install_paper_robo_controls(telegram_bot):
    if getattr(telegram_bot, 'paper_robo_controls_installed', False):
        return telegram_bot

    original_kb = telegram_bot.kb
    original_process_text = telegram_bot.process_text

    def kb_with_robo():
        kb = original_kb()
        rows = list(kb.get('keyboard') or [])
        label = '🤖 ROBO PAPER ON' if futures_paper_robo.armed else '🤖 ROBO PAPER OFF'
        # Keep controls compact and separate from Balance/Home.
        rows.insert(max(0, len(rows)-1), [{'text': label}, {'text':'🛑 PAPER KILL'}])
        kb['keyboard'] = rows
        return kb

    async def process_text_with_robo(uid, chat, text):
        t = str(text or '').strip().lower()
        if t in {'🤖 robo paper off','robo paper on','paper robo on','robo on'}:
            msg = await futures_paper_robo.arm()
            return await telegram_bot.send(chat, msg, kb_with_robo())
        if t in {'🤖 robo paper on','paper robo off','robo off'}:
            msg = await futures_paper_robo.disarm()
            return await telegram_bot.send(chat, msg, kb_with_robo())
        if t in {'🛑 paper kill','paper kill','kill robo','robo kill'}:
            msg = await futures_paper_robo.kill()
            return await telegram_bot.send(chat, msg, kb_with_robo())
        if t in {'robo status','paper robo status'}:
            return await telegram_bot.send(chat, futures_paper_robo.status_text(), kb_with_robo())
        return await original_process_text(uid, chat, text)

    telegram_bot.kb = kb_with_robo
    telegram_bot.process_text = process_text_with_robo
    telegram_bot.paper_robo_controls_installed = True
    return telegram_bot
