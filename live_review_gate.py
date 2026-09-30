"""Human-controlled live trade review gate.

This module prepares a real-market order ticket from qualified ROBO STAFF signals
but deliberately never submits, modifies, cancels, or closes an exchange order.
It is the safe hand-off point for a human to review the exact contract, side,
allocation and risk levels before acting in Delta manually.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from config import logger
from delta_account_read import delta_account_read_service

LEVERAGE_MODEL = 84
ALLOCATION_PCT = 0.10
USDINR = 85.0


@dataclass
class ReviewTicket:
    underlying: str
    action: str
    contract: str
    direction: str
    entry: float
    sl: float
    t1: float
    t2: float
    t3: float
    allocation: float
    allocation_asset: str
    model_buying_power_usd: float
    created_at: float
    setup_id: str


class LiveReviewGate:
    def __init__(self):
        self.armed = False
        self.latest: dict[str, ReviewTicket] = {}
        self.seen_setups: dict[str, float] = {}
        self.alert_cb = None

    def set_alert_callback(self, cb):
        self.alert_cb = cb

    async def _alert(self, text: str):
        if self.alert_cb:
            await self.alert_cb(text)

    async def arm(self):
        self.armed = True
        return (
            "🟠 *LIVE REVIEW GATE: ON*\n"
            "Qualified ROBO STAFF signals will create manual order tickets.\n"
            "🔒 No exchange order is submitted by this module."
        )

    async def disarm(self):
        self.armed = False
        return "🟠 *LIVE REVIEW GATE: OFF*\nNew live-review tickets are stopped."

    async def clear(self):
        self.armed = False
        n = len(self.latest)
        self.latest.clear()
        return f"🧹 *LIVE REVIEW CLEARED*\nGate OFF • {n} stored ticket(s) cleared."

    @staticmethod
    def _num(v, default=0.0):
        try:
            x = float(v)
            return x if math.isfinite(x) else default
        except (TypeError, ValueError):
            return default

    async def _available_capital(self):
        if not delta_account_read_service.configured:
            raise RuntimeError("Balance API key/secret not configured")
        rows = await delta_account_read_service.get_balances()
        usd = None
        inr = None
        for row in rows:
            asset = str(row.get('asset_symbol') or row.get('symbol') or row.get('asset') or '').upper()
            available = self._num(row.get('available_balance'))
            if asset == 'USD' and available > 0:
                usd = available
            elif asset == 'INR' and available > 0:
                inr = available
        if usd is not None:
            return usd, 'USD', usd
        if inr is not None:
            return inr, 'INR', inr / USDINR
        raise RuntimeError("No positive USD/INR available balance returned")

    async def on_signal(self, candidate):
        if not self.armed:
            return
        setup_id = str(getattr(candidate, 'setup_id', '') or '')
        if not setup_id or setup_id in self.seen_setups:
            return
        underlying = str(getattr(candidate, 'underlying', '') or '').upper()
        action = str(getattr(candidate, 'action', '') or '').upper()
        contract = str(getattr(candidate, 'option_symbol', '') or '')
        direction = str(getattr(candidate, 'direction', '') or '').upper()
        if underlying not in {'BTC','ETH','GOLD'} or not contract or action not in {'OPTION BUY','OPTION SELL'}:
            return
        self.seen_setups[setup_id] = time.time()
        try:
            entry = self._num(getattr(candidate, 'premium', 0))
            sl = self._num(getattr(candidate, 'sl', 0))
            t1 = self._num(getattr(candidate, 't1', 0))
            t2 = self._num(getattr(candidate, 't2', 0))
            t3 = self._num(getattr(candidate, 't3', 0))
            if min(entry, sl, t1, t2, t3) <= 0:
                raise RuntimeError("signal levels incomplete")
            available_display, asset, available_usd = await self._available_capital()
            allocation = available_display * ALLOCATION_PCT
            model_bp = available_usd * ALLOCATION_PCT * LEVERAGE_MODEL
            ticket = ReviewTicket(
                underlying=underlying, action=action, contract=contract, direction=direction,
                entry=entry, sl=sl, t1=t1, t2=t2, t3=t3,
                allocation=allocation, allocation_asset=asset,
                model_buying_power_usd=model_bp, created_at=time.time(), setup_id=setup_id,
            )
            self.latest[underlying] = ticket
            await self._alert(self.format_ticket(ticket))
        except Exception as exc:
            logger.warning('[LIVE_REVIEW] %s skipped: %s', underlying, exc)
            await self._alert(f"🟠 LIVE REVIEW SKIP — `{underlying}` | {exc}")

    def format_ticket(self, t: ReviewTicket) -> str:
        return (
            "🟠 *LIVE TRADE REVIEW TICKET*\n"
            f"{t.underlying} • *{t.action}* • `{t.contract}`\n"
            f"Direction: *{t.direction}*\n"
            f"Capital allocation: *{t.allocation:,.2f} {t.allocation_asset}* (10% available)\n"
            f"84x sizing model buying power ≈ `${t.model_buying_power_usd:,.2f}`\n\n"
            f"Entry: `{t.entry:.6g}` | SL: `{t.sl:.6g}`\n"
            f"T1: `{t.t1:.6g}` | T2: `{t.t2:.6g}` | T3: `{t.t3:.6g}`\n\n"
            "Review contract, quantity, margin, fees, liquidation and SL in Delta before acting.\n"
            "🔒 *MANUAL REVIEW ONLY — NO ORDER SENT*"
        )

    def status_text(self):
        rows = [f"🟠 *LIVE REVIEW GATE: {'ON' if self.armed else 'OFF'}*"]
        if not self.latest:
            rows.append('Stored live-review tickets: 0')
        else:
            rows.append(f'Stored live-review tickets: {len(self.latest)}')
            for t in self.latest.values():
                rows.append(f"• {t.underlying} {t.action} `{t.contract}` | Entry `{t.entry:.6g}` | SL `{t.sl:.6g}`")
        rows.append('🔒 No exchange order endpoint is used.')
        return '\n'.join(rows)


live_review_gate = LiveReviewGate()
