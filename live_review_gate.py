"""Human-controlled manual trade-preparation gate.

This gate is OFF after every restart/deploy. Only when the user turns it ON will
qualified ROBO STAFF signals create a ready-to-submit manual ticket. A second
explicit CONFIRM step marks the latest ticket as approved for MANUAL Delta submit.
It never submits, modifies, cancels or closes an exchange order.
"""
from __future__ import annotations

import time

from config import logger
from delta_account_read import delta_account_read_service
from delta_live_manual_ticket import ManualOrderTicket, build_manual_ticket, format_manual_ticket

USDINR = 85.0


class LiveReviewGate:
    def __init__(self):
        self.armed = False  # hard default: OFF after restart/deploy
        self.latest: dict[str, ManualOrderTicket] = {}
        self.confirmed: dict[str, ManualOrderTicket] = {}
        self.confirmed_at: dict[str, float] = {}
        self.last_underlying: str | None = None
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
            "🤖 *AUTO TRADE PREP: ON*\n"
            "Qualified ROBO STAFF signals will create READY manual order tickets.\n"
            "10% current available capital • 84x sizing model • Entry/SL/T1/T2/T3.\n"
            "A separate ✅ CONFIRM button is required before the ticket is marked approved.\n"
            "🔒 Final exchange submit remains manual."
        )

    async def disarm(self):
        self.armed = False
        return "🤖 *AUTO TRADE PREP: OFF*\nNew ready tickets are stopped. Existing stored tickets remain available."

    async def clear(self):
        self.armed = False
        n = len(self.latest)
        self.latest.clear()
        self.confirmed.clear()
        self.confirmed_at.clear()
        self.last_underlying = None
        return f"🧹 *AUTO TRADE PREP CLEARED*\nGate OFF • {n} stored ticket(s) cleared."

    async def confirm_latest(self):
        """Explicit user confirmation for the newest prepared ticket.

        This is intentionally an approval marker only. It does not call any Delta
        trading endpoint. The user still performs the final submit manually.
        """
        u = self.last_underlying
        if not u or u not in self.latest:
            return "⚠️ *NO READY TICKET*\nWait for a qualified signal or open 📋 READY TICKET first."
        t = self.latest[u]
        self.confirmed[u] = t
        self.confirmed_at[u] = time.time()
        return (
            "✅ *READY TRADE CONFIRMED*\n"
            f"{t.underlying} • *{t.action}* • `{t.contract}`\n"
            f"Model units: `{t.model_units}` | Allocation: *{t.allocation:,.2f} {t.allocation_asset}*\n"
            f"Entry `{t.entry:.6g}` | SL `{t.sl:.6g}` | T1 `{t.t1:.6g}` | T2 `{t.t2:.6g}` | T3 `{t.t3:.6g}`\n\n"
            "This confirms the ticket for your manual Delta submit.\n"
            "🔒 *NO EXCHANGE ORDER WAS SENT*"
        )

    async def reject_latest(self):
        u = self.last_underlying
        if not u or u not in self.latest:
            return "⚠️ *NO READY TICKET TO REJECT*"
        t = self.latest.pop(u)
        self.confirmed.pop(u, None)
        self.confirmed_at.pop(u, None)
        self.last_underlying = next(reversed(self.latest), None) if self.latest else None
        return f"❌ *READY TRADE REJECTED*\n{t.underlying} • `{t.contract}` removed from ready tickets."

    @staticmethod
    def _num(v, default=0.0):
        try:
            return float(v) if v is not None else default
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
        # Critical safety gate: when OFF, absolutely nothing is prepared.
        if not self.armed:
            return
        setup_id = str(getattr(candidate, 'setup_id', '') or '')
        if not setup_id or setup_id in self.seen_setups:
            return

        underlying = str(getattr(candidate, 'underlying', '') or '').upper()
        self.seen_setups[setup_id] = time.time()
        try:
            available_display, asset, available_usd = await self._available_capital()
            ticket = build_manual_ticket(
                candidate,
                available_display=available_display,
                asset=asset,
                available_usd=available_usd,
            )
            self.latest[ticket.underlying] = ticket
            self.confirmed.pop(ticket.underlying, None)
            self.confirmed_at.pop(ticket.underlying, None)
            self.last_underlying = ticket.underlying
            await self._alert(
                format_manual_ticket(ticket)
                + "\n\nPress ✅ *CONFIRM READY* only after checking the ticket."
            )
        except Exception as exc:
            logger.warning('[AUTO_TRADE_PREP] %s skipped: %s', underlying, exc)
            await self._alert(f"🤖 AUTO TRADE PREP SKIP — `{underlying or 'UNKNOWN'}` | {exc}")

    def status_text(self):
        rows = [
            f"🤖 *AUTO TRADE PREP: {'ON' if self.armed else 'OFF'}*",
            "Activation rule: READY tickets are created only while this switch is ON.",
            "Confirmation rule: newest READY ticket needs ✅ CONFIRM READY.",
            "Restart/deploy default: OFF",
        ]
        if not self.latest:
            rows.append('Stored ready tickets: 0')
        else:
            rows.append(f'Stored ready tickets: {len(self.latest)}')
            for t in self.latest.values():
                mark = '✅ CONFIRMED' if t.underlying in self.confirmed else '⏳ NOT CONFIRMED'
                rows.append(
                    f"• {t.underlying} {t.action} `{t.contract}` | {mark} | Model units `{t.model_units}` | Entry `{t.entry:.6g}` | SL `{t.sl:.6g}`"
                )
        rows.append('🔒 Final exchange submit is manual; no order endpoint is used.')
        return '\n'.join(rows)


live_review_gate = LiveReviewGate()
