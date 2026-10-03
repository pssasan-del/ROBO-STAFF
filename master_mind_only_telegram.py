"""Telegram presentation layer for the active multi-signal runtime.

MASTER MIND strategy is not modified here. This module only presents status and
performance for MASTER MIND, ROBO STAFF V7.1 and TBR V1. No order execution.
"""
from __future__ import annotations

import time
from types import MethodType

from delta_signal_engine import delta_auto_engine
from performance_store import performance_store
from trend_breakout_retest_v1 import tbr_engine
from trend_breakout_retest_stats import tbr_stats


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


def _master_status(engine, title="🧠 *MASTER MIND STATUS*"):
    btc = engine.last_status_by_symbol.get("BTCUSD", "INIT")
    gold = engine.last_status_by_symbol.get("XAUTUSD", "INIT")
    btc_reason = engine.last_reason_by_symbol.get("BTCUSD", "")
    gold_reason = engine.last_reason_by_symbol.get("XAUTUSD", "")
    return (
        f"{title}\n\n"
        f"BTCUSD: *{btc}*\nReason/setup: `{btc_reason or 'n/a'}`\n"
        f"Last alert: `{_age_text(engine.last_alert_at.get('BTCUSD', 0))}`\n\n"
        f"XAUTUSD (GOLD): *{gold}*\nReason/setup: `{gold_reason or 'n/a'}`\n"
        f"Last alert: `{_age_text(engine.last_alert_at.get('XAUTUSD', 0))}`\n\n"
        f"Last scan: `{_age_text(engine.last_scan_at)}`"
    )


def _v7_pair(r, group, name):
    p = (r.get(group) or {}).get(name) or {}
    w = int(p.get("success", 0)); l = int(p.get("failed", 0)); n = w + l
    return f"{w}W/{l}L ({round(100*w/n,1) if n else 0.0}%)"


def _v7_report(days):
    r = performance_store.report(days)
    wins = int(r.get("success", 0)); losses = int(r.get("failed", 0)); resolved = wins + losses
    rate = round(100 * wins / resolved, 1) if resolved else 0.0
    label = "DAILY" if days == 1 else "WEEKLY"
    return (
        f"📈 *ROBO STAFF V7.1 — {label} SUCCESS ANALYSIS*\n"
        f"Signals: {r.get('total', 0)} | Resolved: {resolved} | Open: {r.get('unresolved', 0)}\n"
        f"Wins: {wins} | Loss/SL: {losses} | *Success rate: {rate}%*\n"
        f"BTC: {_v7_pair(r,'assets','BTC')} | ETH: {_v7_pair(r,'assets','ETH')} | GOLD: {_v7_pair(r,'assets','GOLD')}\n"
        f"OPTION BUY: {_v7_pair(r,'actions','OPTION BUY')} | OPTION SELL: {_v7_pair(r,'actions','OPTION SELL')}\n"
        f"Stale: {r.get('stale',0)} | Invalidated: {r.get('invalidated',0)}"
    )


def _tbr_pair(p):
    p = p or {}; w = int(p.get("wins", 0)); l = int(p.get("losses", 0)); n = w + l
    return f"{w}W/{l}L ({round(100*w/n,1) if n else 0.0}%)"


def _tbr_report(days):
    r = tbr_stats.report(days)
    label = "DAILY" if days == 1 else "WEEKLY"
    return (
        f"⚡ *TBR V1 — {label} SUCCESS ANALYSIS*\n"
        f"Signals: {r.get('signals', 0)} | Resolved: {r.get('resolved', 0)} | "
        f"Wins: {r.get('wins', 0)} | Losses: {r.get('losses', 0)}\n"
        f"*Success rate: {r.get('success_rate', 0)}%* | T1 hit rate: {r.get('t1_hit_rate',0)}%\n"
        f"T1: {r.get('t1_hits', 0)} | T2: {r.get('t2_hits', 0)} | SL: {r.get('sl_exits',0)} | Time exit: {r.get('time_exits',0)}\n"
        f"BTC: {_tbr_pair((r.get('assets') or {}).get('BTCUSD'))} | ETH: {_tbr_pair((r.get('assets') or {}).get('ETHUSD'))}\n"
        f"LONG: {_tbr_pair((r.get('directions') or {}).get('LONG'))} | SHORT: {_tbr_pair((r.get('directions') or {}).get('SHORT'))}\n"
        f"Avg net: {r.get('avg_net_r',0):+.2f}R | Net total: {r.get('net_r_sum',0):+.2f}R | Paper equity: {r.get('realised_equity_pct',0):+.3f}%\n"
        f"Cancelled: {r.get('cancelled',0)} | Expired: {r.get('expired',0)}"
    )


def _success_analysis(days):
    label = "TODAY" if days == 1 else "LAST 7 DAYS"
    return (
        f"📊 *SUCCESS RATE ANALYSIS — {label}*\n\n"
        + _v7_report(days)
        + "\n\n────────────\n"
        + _tbr_report(days)
        + "\n\nℹ️ Rates use resolved tracked signals only; open signals are not counted as wins/losses."
    )


def _multi_status(engine, title="🔥 *LATEST STATUS*"):
    v7_last = delta_auto_engine.last_signal
    if v7_last:
        v7 = delta_auto_engine.format_signal(v7_last)
    else:
        v7 = "ROBO STAFF V7.1: no qualified signal since restart"
    tbr_states = tbr_engine.last_status or {}
    tbr_line = "TBR V1: " + (" | ".join(f"{k}: {v}" for k, v in tbr_states.items()) if tbr_states else "waiting for first scan")
    return (
        _master_status(engine, title)
        + "\n\n────────────\n*ROBO STAFF V7.1 — OPTION BUY*\n" + v7
        + "\n\n────────────\n*TBR V1 — BTC/ETH FUTURES*\n" + tbr_line
        + f"\nLast TBR scan: `{_age_text(tbr_engine.last_scan_at)}`"
        + "\n\nMode: *MULTI SIGNAL — NO ORDER EXECUTION*"
    )


def install_master_mind_only_telegram(telegram_bot, engine):
    """Compatibility entry point: install the multi-engine Telegram view."""
    original = telegram_bot.process_text

    async def process(self, uid, chat, text):
        t = (text or "").lower().strip()
        if t in {"/start", "start", "help", "🏠 home", "home"}:
            return await self.send(
                chat,
                "👋 *ROBO STAFF — MULTI SIGNAL MODE*\n\n"
                "🧠 MASTER MIND: BTC + XAUT (GOLD)\n"
                "📈 ROBO STAFF V7.1: BTC/ETH Option BUY signals\n"
                "⚡ TBR V1: BTC/ETH Futures signals\n\n"
                "📊 Daily / 📅 Weekly: V7.1 + TBR success-rate analysis\n"
                "⚠️ Signal only — no order execution.",
                self.kb(),
            )
        if t in {"🔥 latest", "latest", "latest signal"}:
            return await self.send(chat, _multi_status(engine), self.kb())
        if t in {"📊 daily", "daily", "daily report"}:
            return await self.send(chat, _success_analysis(1), self.kb())
        if t in {"📅 weekly", "weekly", "weekly report"}:
            return await self.send(chat, _success_analysis(7), self.kb())
        if t in {"💾 system", "system", "system status"}:
            msg = (
                _master_status(engine, "💾 *SYSTEM — MULTI SIGNAL*")
                + "\n\nROBO STAFF V7.1: *ON*"
                + f"\nV7 last scan: `{_age_text(delta_auto_engine.last_scan_at)}`"
                + "\nTBR V1: *ON — FAST9 / 180 HISTORY / FIB VERIFY*"
                + f"\nTBR last scan: `{_age_text(tbr_engine.last_scan_at)}`"
                + "\nTrading: *DISABLED — SIGNAL ONLY*"
            )
            return await self.send(chat, msg, self.kb())
        if t in {"v7", "v7 status", "v7 daily"}:
            return await self.send(chat, _v7_report(1), self.kb())
        if t == "v7 weekly":
            return await self.send(chat, _v7_report(7), self.kb())
        if t in {"tbr", "tbr status", "tbr latest", "tbr daily"}:
            return await self.send(chat, _tbr_report(1) + f"\nLast scan: `{_age_text(tbr_engine.last_scan_at)}`", self.kb())
        if t == "tbr weekly":
            return await self.send(chat, _tbr_report(7), self.kb())
        return await original(uid, chat, text)

    telegram_bot.process_text = MethodType(process, telegram_bot)
    return telegram_bot
