"""F&O ASTHRA option-buy paper executor.

This module deliberately does NOT submit exchange orders. It shadows qualified
ROBO STAFF OPTION BUY signals using Delta public option quotes plus the read-only
wallet balance so sizing, SL and T1 trailing can be validated before any live
trading integration is considered.

Rules:
- OPTION BUY signals only (CE for bullish, PE for bearish as produced by engine)
- 10% of current available capital per new underlying
- 84x requested leverage/buying-power MODEL for sizing display only
- one open paper option position per underlying
- use the signal Entry/SL/T1/T2/T3 unchanged
- T1 activates trailing; no fixed T1 exit
- restart/deploy always defaults OFF
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass

from config import logger
from delta_account_read import delta_account_read_service
from delta_options_service import delta_options_service

LEVERAGE_MODEL = 84
ALLOCATION_PCT = 0.10
USDINR = 85.0


@dataclass
class OptionPaperTrade:
    underlying: str
    option_symbol: str
    strike: float
    expiry: str
    entry: float
    stop: float
    t1: float
    t2: float
    t3: float
    risk: float
    margin_display: float
    margin_asset: str
    model_buying_power_usd: float
    paper_units: int
    opened_at: float
    setup_id: str
    trail_active: bool = False
    trail_stop: float | None = None
    best_price: float | None = None


class FOAsthraPaper:
    def __init__(self):
        self.armed = False
        self.positions: dict[str, OptionPaperTrade] = {}
        self.seen_setups: dict[str, float] = {}
        self.alert_cb = None
        self.running = True

    def set_alert_callback(self, cb):
        self.alert_cb = cb

    async def _alert(self, text: str):
        if self.alert_cb:
            await self.alert_cb(text)

    async def arm(self):
        self.armed = True
        return (
            "⚡ *F&O ASTHRA: ON*\n"
            "OPTION BUY shadow execution • 10% available capital • 84x sizing model • T1 trailing.\n"
            "🔒 No exchange order is submitted."
        )

    async def disarm(self):
        self.armed = False
        return "⚡ *F&O ASTHRA: OFF*\nNew option paper entries stopped; existing ASTHRA paper positions continue monitoring."

    async def kill(self):
        self.armed = False
        count = len(self.positions)
        self.positions.clear()
        return f"🛑 *F&O ASTHRA KILLED*\nNew entries OFF • {count} paper option position(s) cleared. No Delta position was touched."

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
        if str(getattr(candidate, 'action', '') or '').upper() != 'OPTION BUY':
            return
        underlying = str(getattr(candidate, 'underlying', '') or '').upper()
        if underlying not in {'BTC', 'ETH', 'GOLD'} or underlying in self.positions:
            return
        setup_id = str(getattr(candidate, 'setup_id', '') or '')
        if not setup_id or setup_id in self.seen_setups:
            return

        self.seen_setups[setup_id] = time.time()
        try:
            entry = self._num(getattr(candidate, 'premium', 0))
            stop = self._num(getattr(candidate, 'sl', 0))
            t1 = self._num(getattr(candidate, 't1', 0))
            t2 = self._num(getattr(candidate, 't2', 0))
            t3 = self._num(getattr(candidate, 't3', 0))
            strike = self._num(getattr(candidate, 'strike', 0))
            expiry = str(getattr(candidate, 'expiry', '') or '')
            symbol = str(getattr(candidate, 'option_symbol', '') or '')
            if min(entry, stop, t1, t2, t3, strike) <= 0 or not expiry or not symbol:
                raise RuntimeError("signal option Entry/SL/targets/contract incomplete")
            if not (stop < entry < t1 <= t2 <= t3):
                raise RuntimeError("OPTION BUY signal levels are not ordered SL < Entry < T1 <= T2 <= T3")
            risk = entry - stop

            available_display, asset, available_usd = await self._available_capital()
            allocation_display = available_display * ALLOCATION_PCT
            model_buying_power_usd = available_usd * ALLOCATION_PCT * LEVERAGE_MODEL
            # Paper units are only a sizing model; real Delta contract multiplier/margin
            # is deliberately not treated as executable here.
            paper_units = max(1, int(math.floor(model_buying_power_usd / entry)))

            trade = OptionPaperTrade(
                underlying=underlying, option_symbol=symbol, strike=strike, expiry=expiry,
                entry=entry, stop=stop, t1=t1, t2=t2, t3=t3, risk=risk,
                margin_display=allocation_display, margin_asset=asset,
                model_buying_power_usd=model_buying_power_usd, paper_units=paper_units,
                opened_at=time.time(), setup_id=setup_id, best_price=entry,
            )
            self.positions[underlying] = trade
            await self._alert(
                f"🧪 *F&O ASTHRA OPTION PAPER ENTRY*\n"
                f"{underlying} • *OPTION BUY* • `{symbol}`\n"
                f"Capital allocation: *{allocation_display:,.2f} {asset}* (10% available)\n"
                f"84x model buying power ≈ `${model_buying_power_usd:,.2f}` | Paper units `{paper_units}`\n"
                f"Entry: `{entry:.6g}` | SL: `{stop:.6g}`\n"
                f"T1 trail trigger: `{t1:.6g}` | T2 `{t2:.6g}` | T3 `{t3:.6g}`\n"
                "At T1: no fixed exit; trailing activates.\n"
                "🔒 *SHADOW/PAPER ONLY — NO DELTA ORDER SENT*"
            )
        except Exception as exc:
            logger.warning('[FO_ASTHRA] %s skipped: %s', underlying, exc)
            await self._alert(f"🧪 F&O ASTHRA SKIP — `{underlying}` | {exc}")

    async def _quote(self, t: OptionPaperTrade):
        if t.underlying == 'GOLD':
            snap = await delta_options_service.get_gold_strike_snapshot(t.strike, t.expiry)
        else:
            snap = await delta_options_service.get_strike_snapshot(t.underlying, t.strike, t.expiry)
        side = 'ce' if t.option_symbol.upper().startswith('C-') else 'pe'
        row = snap.get(side) or {}
        # For a long option position, executable exit is the best bid.
        px = row.get('best_bid')
        if px is None or self._num(px) <= 0:
            px = row.get('mark_price') or row.get('premium')
        return self._num(px)

    async def _monitor_one(self, t: OptionPaperTrade):
        px = await self._quote(t)
        if px <= 0:
            return
        t.best_price = max(self._num(t.best_price, t.entry), px)
        active_stop = t.trail_stop if t.trail_active and t.trail_stop is not None else t.stop
        if px <= active_stop:
            pnl_r = (px - t.entry) / max(t.risk, 1e-9)
            self.positions.pop(t.underlying, None)
            return await self._alert(
                f"🧪 ASTHRA PAPER EXIT — `{t.option_symbol}` @ `{px:.6g}` | `{pnl_r:+.2f}R`"
            )

        if not t.trail_active and px >= t.t1:
            t.trail_active = True
            fee_buffer = max(0.01 * t.entry, 0.08 * t.risk)
            base = t.entry + fee_buffer
            trail_gap = max(0.50 * t.risk, 0.04 * t.entry)
            t.trail_stop = max(base, px - trail_gap)
            await self._alert(
                f"✅ *F&O ASTHRA T1* — `{t.option_symbol}` | trailing ON | trail SL `{t.trail_stop:.6g}`"
            )
            return

        if t.trail_active:
            gap_r = 0.50
            if px >= t.t3:
                gap_r = 0.25
            elif px >= t.t2:
                gap_r = 0.35
            trail_gap = max(gap_r * t.risk, 0.025 * t.entry)
            t.trail_stop = max(float(t.trail_stop or t.stop), t.best_price - trail_gap)

    async def monitor_loop(self):
        while self.running:
            try:
                for t in list(self.positions.values()):
                    try:
                        await self._monitor_one(t)
                    except Exception as exc:
                        logger.debug('[FO_ASTHRA] monitor %s: %s', t.option_symbol, exc)
                cutoff = time.time() - 2 * 86400
                for k, ts in list(self.seen_setups.items()):
                    if ts < cutoff:
                        self.seen_setups.pop(k, None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning('[FO_ASTHRA] monitor loop: %s', exc)
            await asyncio.sleep(5)

    def status_text(self):
        rows = [
            f"⚡ *F&O ASTHRA: {'ON' if self.armed else 'OFF'}*",
            "Mode: OPTION BUY shadow execution • 10% available capital • 84x sizing model",
        ]
        if not self.positions:
            rows.append('Open ASTHRA paper option positions: 0')
        else:
            rows.append(f'Open ASTHRA paper option positions: {len(self.positions)}')
            for t in self.positions.values():
                trail = f" | Trail `{t.trail_stop:.6g}`" if t.trail_active and t.trail_stop is not None else ''
                rows.append(f"• {t.underlying} `{t.option_symbol}` | Entry `{t.entry:.6g}` | SL `{t.stop:.6g}`{trail}")
        rows.append('🔒 No exchange order endpoints are used.')
        return '\n'.join(rows)


fo_asthra_paper = FOAsthraPaper()
