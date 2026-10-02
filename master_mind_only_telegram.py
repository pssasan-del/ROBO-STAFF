"""Telegram presentation layer for MASTER MIND-only runtime mode.

This module does not alter MASTER MIND signal logic. It only prevents the
Telegram Latest/Daily/Weekly/System buttons from showing stale ROBO STAFF V7.1
or TBR V1 data after those background engines are disabled.
"""
from __future__ import annotations

import time
from types import MethodType


def _age_text(ts):
    try:
        ts = float(ts or 0)
    except (TypeError, ValueError):
        ts = 0.0
    if ts <= 0:
        return "none since restart"
    sec = max(0, int(time.time() - ts))
    if sec < 60:
        return f"{sec}s ago"
    if sec < 3600:
        return f"{sec // 60}m ago"
    return f"{sec // 3600}h {(sec % 3600) // 60}m ago"


def _status_text(engine, title="🧠 *MASTER MIND STATUS*"):
    btc = engine.last_status_by_symbol.get("BTCUSD", "INIT")
    gold = engine.last_status_by_symbol.get("XAUTUSD", "INIT")
    btc_reason = engine.last_reason_by_symbol.get("BTCUSD", "")
    gold_reason = engine.last_reason_by_symbol.get("XAUTUSD", "")
    btc_alert = _age_text(engine.last_alert_at.get("BTCUSD", 0))
    gold_alert = _age_text(engine.last_alert_at.get("XAUTUSD", 0))
    scan_age = _age_text(engine.last_scan_at)
    return (
        f"{title}\n\n"
        f"BTCUSD: *{btc}*\n"
        f"Reason/setup: `{btc_reason or 'n/a'}`\n"
        f"Last alert: `{btc_alert}`\n\n"
        f"XAUTUSD (GOLD): *{gold}*\n"
        f"Reason/setup: `{gold_reason or 'n/a'}`\n"
        f"Last alert: `{gold_alert}`\n\n"
        f"Last scan: `{scan_age}`\n"
        "ROBO STAFF V7.1: *OFF*\n"
        "TBR V1: *OFF*\n"
        "Mode: *MASTER MIND ONLY — SIGNAL ONLY*"
    )


def install_master_mind_only_telegram(telegram_bot, engine):
    original = telegram_bot.process_text

    async def process(self, uid, chat, text):
        t = (text or "").lower().strip()
        if t in {"/start", "start", "help", "🏠 home", "home"}:
            return await self.send(
                chat,
                "👋 *MASTER MIND ONLY MODE*\n\n"
                "Active signal engine: *MASTER MIND BTC + XAUT (GOLD)*\n"
                "ROBO STAFF V7.1 and TBR V1 are disabled.\n"
                "⚠️ Signal only — no order execution.",
                self.kb(),
            )
        if t in {"🔥 latest", "latest", "latest signal"}:
            return await self.send(chat, _status_text(engine, "🔥 *MASTER MIND — LATEST STATUS*"), self.kb())
        if t in {"📊 daily", "daily", "daily report"}:
            return await self.send(
                chat,
                _status_text(engine, "📊 *MASTER MIND — CURRENT STATUS*")
                + "\n\nOld V7/TBR win trackers are intentionally hidden because those engines are no longer active.",
                self.kb(),
            )
        if t in {"📅 weekly", "weekly", "weekly report"}:
            return await self.send(
                chat,
                _status_text(engine, "📅 *MASTER MIND — CURRENT STATUS*")
                + "\n\nNo V7/TBR weekly statistics are shown in Master Mind-only mode.",
                self.kb(),
            )
        if t in {"💾 system", "system", "system status"}:
            return await self.send(chat, _status_text(engine, "💾 *SYSTEM — MASTER MIND ONLY*"), self.kb())
        if t in {"tbr", "tbr status", "tbr daily", "tbr weekly", "tbr latest"}:
            return await self.send(chat, "TBR V1 is disabled. Active engine: *MASTER MIND only*.", self.kb())
        return await original(uid, chat, text)

    telegram_bot.process_text = MethodType(process, telegram_bot)
    return telegram_bot
