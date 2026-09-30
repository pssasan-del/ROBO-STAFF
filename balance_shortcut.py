"""Compact read-only Delta balance button for Telegram."""
from __future__ import annotations

from config import logger
from delta_account_read import delta_account_read_service


def install_balance_shortcut(telegram_bot):
    if getattr(telegram_bot, 'balance_shortcut_installed', False):
        return telegram_bot

    original_kb = telegram_bot.kb
    original_process_text = telegram_bot.process_text

    def kb_with_balance():
        kb = original_kb()
        rows = list(kb.get('keyboard') or [])
        # Keep the main menu compact: Balance and Home share the last row.
        if rows and any((isinstance(x, dict) and x.get('text') == '🏠 Home') for x in rows[-1]):
            rows[-1] = [{'text':'💰 Balance'}, {'text':'🏠 Home'}]
        else:
            rows.append([{'text':'💰 Balance'}])
        kb['keyboard'] = rows
        return kb

    async def process_text_with_balance(uid, chat, text):
        t = str(text or '').strip().lower()
        if t in {'💰 balance', 'balance', 'wallet balance', 'delta balance'}:
            if not delta_account_read_service.configured:
                return await telegram_bot.send(
                    chat,
                    '💰 *DELTA BALANCE*\nPrivate API is not configured yet. Add `DELTA_API_KEY` and `DELTA_API_SECRET` in Render environment variables. Use a read-only key for balance fetch.',
                    kb_with_balance(),
                )
            try:
                msg = await delta_account_read_service.balance_text()
                return await telegram_bot.send(chat, msg, kb_with_balance())
            except Exception as exc:
                logger.warning('[DELTA_ACCOUNT] balance fetch failed safely: %s', exc)
                return await telegram_bot.send(
                    chat,
                    '⚠️ Delta balance fetch failed. Check API key/secret, account environment, and server clock.',
                    kb_with_balance(),
                )
        return await original_process_text(uid, chat, text)

    telegram_bot.kb = kb_with_balance
    telegram_bot.process_text = process_text_with_balance
    telegram_bot.balance_shortcut_installed = True
    return telegram_bot
