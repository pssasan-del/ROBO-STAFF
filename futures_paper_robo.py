"""Futures-only ROBO paper executor.

This module intentionally DOES NOT submit exchange orders. It mirrors the requested
live sizing/risk logic against Delta public prices and the read-only wallet balance:
- ROBO STAFF direction -> BTCUSD/ETHUSD/XAUTUSD perpetual paper LONG/SHORT
- 10% of current available capital per new symbol
- 84x target leverage for notional sizing
- one open paper trade per symbol
- underlying structural SL from the signal
- T1 at +1R activates a trailing stop; no fixed T1 exit

MASTER MIND and B/E/X remain independent.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass

import httpx

from config import logger, settings
from delta_account_read import delta_account_read_service
from delta_market_service import delta_market_service


LEVERAGE = 84
ALLOCATION_PCT = 0.10
USDINR = 85.0
MAX_STOP_PCT = 0.0065


@dataclass
class PaperTrade:
    symbol: str
    direction: str
    side: str
    size: int
    entry: float
    stop: float
    t1: float
    risk: float
    margin_display: float
    margin_asset: str
    notional_usd: float
    opened_at: float
    setup_id: str
    trail_active: bool = False
    trail_stop: float | None = None
    best_price: float | None = None


class FuturesPaperRobo:
    def __init__(self):
        self.armed = False  # always OFF after restart/deploy
        self.positions: dict[str, PaperTrade] = {}
        self.seen_setups: dict[str, float] = {}
        self.alert_cb = None
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=6.0))
        self.running = True

    def set_alert_callback(self, cb):
        self.alert_cb = cb

    async def _alert(self, text: str):
        if self.alert_cb:
            await self.alert_cb(text)

    async def arm(self):
        self.armed = True
        return "🤖 *ROBO PAPER: ON*\nFutures-only simulation • 84x sizing • 10% available capital • no exchange order is sent."

    async def disarm(self):
        self.armed = False
        return "🤖 *ROBO PAPER: OFF*\nNew simulated entries are stopped. Existing paper positions continue to be monitored."

    async def kill(self):
        self.armed = False
        count = len(self.positions)
        self.positions.clear()
        return f"🛑 *ROBO PAPER KILLED*\nNew entries OFF • {count} simulated position(s) cleared. No Delta position was touched."

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

    async def _product(self, symbol: str):
        r = await self.client.get(f"{settings.DELTA_REST_BASE}/v2/products/{symbol}", headers={'Accept':'application/json'})
        if r.status_code != 200:
            raise RuntimeError(f"product HTTP {r.status_code}")
        obj = r.json()
        p = obj.get('result') or {}
        if not obj.get('success') or not isinstance(p, dict):
            raise RuntimeError("product response invalid")
        if str(p.get('contract_type') or '') != 'perpetual_futures':
            raise RuntimeError(f"{symbol} is not perpetual_futures")
        if str(p.get('state') or 'live') != 'live' or str(p.get('trading_status') or 'operational') != 'operational':
            raise RuntimeError(f"{symbol} is not operational")
        return p

    async def _paper_size(self, symbol: str, price: float):
        available_display, asset, available_usd = await self._available_capital()
        allocation_display = available_display * ALLOCATION_PCT
        allocation_usd = available_usd * ALLOCATION_PCT
        target_notional = allocation_usd * LEVERAGE
        p = await self._product(symbol)
        cv = self._num(p.get('contract_value'))
        unit = str(p.get('contract_unit_currency') or '').upper()
        underlying = str((p.get('underlying_asset') or {}).get('symbol') or symbol.replace('USD','')).upper()
        per_contract = price * cv if cv > 0 and unit == underlying else cv
        if per_contract <= 0:
            raise RuntimeError("cannot derive contract notional")
        size = int(math.floor(target_notional / per_contract))
        if size < 1:
            raise RuntimeError(f"10% allocation too small for 1 contract at {LEVERAGE}x")
        return size, allocation_display, asset, target_notional

    async def on_signal(self, candidate):
        if not self.armed:
            return
        setup_id = str(getattr(candidate, 'setup_id', '') or '')
        if not setup_id or setup_id in self.seen_setups:
            return
        symbol = {'BTC':'BTCUSD','ETH':'ETHUSD','GOLD':'XAUTUSD'}.get(getattr(candidate,'underlying',''))
        if not symbol or symbol in self.positions:
            return
        direction = str(getattr(candidate, 'direction', '')).upper()
        if direction not in {'BULLISH','BEARISH'}:
            return

        self.seen_setups[setup_id] = time.time()
        try:
            q = await delta_market_service.get_ticker(symbol)
            entry = self._num(q.get('price'))
            stop = self._num((getattr(candidate,'market',{}) or {}).get('underlying_invalidation'))
            if entry <= 0 or stop <= 0:
                raise RuntimeError("underlying entry/structural SL unavailable")
            if direction == 'BULLISH' and stop >= entry:
                raise RuntimeError("bullish structural SL is not below entry")
            if direction == 'BEARISH' and stop <= entry:
                raise RuntimeError("bearish structural SL is not above entry")
            risk = abs(entry - stop)
            risk_pct = risk / entry
            if risk_pct > MAX_STOP_PCT:
                raise RuntimeError(f"structural SL {risk_pct*100:.2f}% too wide for 84x paper profile")
            size, margin_display, margin_asset, notional_usd = await self._paper_size(symbol, entry)
            t1 = entry + risk if direction == 'BULLISH' else entry - risk
            trade = PaperTrade(
                symbol=symbol, direction=direction, side='LONG' if direction=='BULLISH' else 'SHORT',
                size=size, entry=entry, stop=stop, t1=t1, risk=risk,
                margin_display=margin_display, margin_asset=margin_asset, notional_usd=notional_usd,
                opened_at=time.time(), setup_id=setup_id, best_price=entry,
            )
            self.positions[symbol] = trade
            await self._alert(
                f"🧪 *ROBO FUTURES PAPER ENTRY*\n{symbol} • *{trade.side}* • {LEVERAGE}x model\n"
                f"Capital allocation: *{margin_display:,.2f} {margin_asset}* (10% available)\n"
                f"Estimated size: `{size}` contracts | Notional ≈ `${notional_usd:,.2f}`\n"
                f"Entry: `{entry:,.4f}` | SL: `{stop:,.4f}` | T1 trail trigger: `{t1:,.4f}`\n"
                f"At T1: no fixed exit; trailing activates.\n🔒 *SIMULATION ONLY — NO DELTA ORDER SENT*"
            )
        except Exception as exc:
            logger.warning('[FUTURES_PAPER] %s skipped: %s', symbol, exc)
            await self._alert(f"🧪 ROBO PAPER SKIP — `{symbol}` | {exc}")

    async def _monitor_one(self, t: PaperTrade):
        q = await delta_market_service.get_ticker(t.symbol)
        px = self._num(q.get('price'))
        if px <= 0:
            return
        if t.best_price is None:
            t.best_price = px
        if t.direction == 'BULLISH':
            t.best_price = max(t.best_price, px)
            if px <= (t.trail_stop if t.trail_active and t.trail_stop is not None else t.stop):
                pnl_r = (px - t.entry) / t.risk
                self.positions.pop(t.symbol, None)
                return await self._alert(f"🧪 PAPER EXIT — `{t.symbol}` LONG @ `{px:,.4f}` | `{pnl_r:+.2f}R`")
            if not t.trail_active and px >= t.t1:
                t.trail_active = True
                fee_buffer = max(0.0012 * t.entry, 0.05 * t.risk)
                base = t.entry + fee_buffer
                trail_gap = max(0.50 * t.risk, 0.0025 * t.entry)
                t.trail_stop = max(base, px - trail_gap)
                await self._alert(f"✅ PAPER T1 — `{t.symbol}` LONG | trailing ON | trail SL `{t.trail_stop:,.4f}`")
            elif t.trail_active:
                trail_gap = max(0.50 * t.risk, 0.0025 * t.entry)
                t.trail_stop = max(float(t.trail_stop or t.stop), t.best_price - trail_gap)
        else:
            t.best_price = min(t.best_price, px)
            if px >= (t.trail_stop if t.trail_active and t.trail_stop is not None else t.stop):
                pnl_r = (t.entry - px) / t.risk
                self.positions.pop(t.symbol, None)
                return await self._alert(f"🧪 PAPER EXIT — `{t.symbol}` SHORT @ `{px:,.4f}` | `{pnl_r:+.2f}R`")
            if not t.trail_active and px <= t.t1:
                t.trail_active = True
                fee_buffer = max(0.0012 * t.entry, 0.05 * t.risk)
                base = t.entry - fee_buffer
                trail_gap = max(0.50 * t.risk, 0.0025 * t.entry)
                t.trail_stop = min(base, px + trail_gap)
                await self._alert(f"✅ PAPER T1 — `{t.symbol}` SHORT | trailing ON | trail SL `{t.trail_stop:,.4f}`")
            elif t.trail_active:
                trail_gap = max(0.50 * t.risk, 0.0025 * t.entry)
                t.trail_stop = min(float(t.trail_stop or t.stop), t.best_price + trail_gap)

    async def monitor_loop(self):
        while self.running:
            try:
                for trade in list(self.positions.values()):
                    try:
                        await self._monitor_one(trade)
                    except Exception as exc:
                        logger.debug('[FUTURES_PAPER] monitor %s: %s', trade.symbol, exc)
                cutoff = time.time() - 2 * 86400
                for k, ts in list(self.seen_setups.items()):
                    if ts < cutoff:
                        self.seen_setups.pop(k, None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning('[FUTURES_PAPER] monitor loop: %s', exc)
            await asyncio.sleep(5)

    def status_text(self):
        rows = [f"🤖 *ROBO PAPER: {'ON' if self.armed else 'OFF'}*", f"Mode: Futures only • {LEVERAGE}x sizing • 10% available capital"]
        if not self.positions:
            rows.append('Open paper positions: 0')
        else:
            rows.append(f'Open paper positions: {len(self.positions)}')
            for t in self.positions.values():
                trail = f" | Trail `{t.trail_stop:,.4f}`" if t.trail_active and t.trail_stop is not None else ''
                rows.append(f"• {t.symbol} {t.side} | Entry `{t.entry:,.4f}` | SL `{t.stop:,.4f}`{trail}")
        rows.append('🔒 Simulation only; no exchange order endpoints are used.')
        return '\n'.join(rows)


futures_paper_robo = FuturesPaperRobo()
