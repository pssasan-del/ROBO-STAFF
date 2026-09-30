"""Telegram controls for F&O ASTHRA LIVE option-buy execution."""
from __future__ import annotations

from fo_asthra_live import fo_asthra_live


def install_fo_asthra_controls(telegram_bot):
    if getattr(telegram_bot, "fo_asthra_controls_installed", False):
        return telegram_bot

    original_kb = telegram_bot.kb
    original_process_text = telegram_bot.process_text

    def kb_with_asthra():
        kb = original_kb()
        rows = list(kb.get("keyboard") or [])
        label = "⚡ F&O ASTHRA ON" if fo_asthra_live.armed else "⚡ F&O ASTHRA OFF"
        rows.insert(max(0, len(rows) - 1), [{"text": label}, {"text": "🛑 ASTHRA KILL"}])
        kb["keyboard"] = rows
        return kb

    async def process_text_with_asthra(uid, chat, text):
        t = str(text or "").strip().lower()
        if t in {
            "⚡ f&o asthra off",
            "f&o asthra on",
            "asthra on",
            "fo asthra on",
            "⚡ f&o asthra on",
        }:
            if fo_asthra_live.armed:
                msg = await fo_asthra_live.disarm()
            else:
                msg = await fo_asthra_live.arm()
            return await telegram_bot.send(chat, msg, kb_with_asthra())
        if t in {"f&o asthra off", "asthra off", "fo asthra off"}:
            msg = await fo_asthra_live.disarm()
            return await telegram_bot.send(chat, msg, kb_with_asthra())
        if t in {"🛑 asthra kill", "asthra kill", "kill asthra"}:
            msg = await fo_asthra_live.kill()
            return await telegram_bot.send(chat, msg, kb_with_asthra())
        if t in {"asthra status", "f&o asthra status", "fo asthra status"}:
            return await telegram_bot.send(chat, fo_asthra_live.status_text(), kb_with_asthra())
        return await original_process_text(uid, chat, text)

    telegram_bot.kb = kb_with_asthra
    telegram_bot.process_text = process_text_with_asthra
    telegram_bot.fo_asthra_controls_installed = True
    return telegram_bot
