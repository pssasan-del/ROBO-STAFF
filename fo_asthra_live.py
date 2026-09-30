"""F&O ASTHRA — REAL option-buy executor for ROBO STAFF signals.

Rules (locked from paper design, now live):
- OPTION BUY signals only
- 10% of current FREE available capital per new underlying
- one open live option position per underlying
- signal Entry / SL / T1 / T2 / T3 unchanged
- T1 activates trailing (no fixed T1 full exit)
- restart/deploy always defaults OFF
- requires LIVE_TRADING_ENABLED + trading API key + runtime ARM

Uses delta_live_trading for actual Delta India order submission.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Optional

from config import logger, settings
from delta_account_read import delta_account_read_service
from delta_options_service import delta_options_service
from delta_live_trading import delta_live, LiveOrderRequest

ALLOCATION_PCT = 0.10
LEVERAGE_MODEL = 84  # sizing model: free_capital × 10% × 84 / premium
USDINR = 85.0


@dataclass
class OptionLiveTrade:
    underlying: str
    option_symbol: str
    product_id: int
    strike: float
    expiry: str
    entry: float
    stop: float
    t1: float
    t2: float
    t3: float
    risk: float
    size: int
    order_id: str
    setup_id: str
    opened_at: float
    margin_display: float
    margin_asset: str
    entry_side: str = "buy"  # buy = long premium, sell = short premium
    trail_active: bool = False
    trail_stop: float | None = None
    best_price: float | None = None
    closed: bool = False


class FOAsthraLive:
    def __init__(self):
        self.armed = False
        self.positions: dict[str, OptionLiveTrade] = {}
        self.seen_setups: dict[str, float] = {}
        self.alert_cb = None
        self.running = True
        self.last_error = ""

    def set_alert_callback(self, cb):
        self.alert_cb = cb

    async def _alert(self, text: str):
        if self.alert_cb:
            await self.alert_cb(text)

    async def arm(self):
        if not settings.LIVE_TRADING_ENABLED:
            return (
                "⛔ *F&O ASTHRA LIVE blocked*\n"
                "`LIVE_TRADING_ENABLED=true` set cheyyuka env-il, trading API key kodukkuka, restart."
            )
        if not delta_live.credentials_ok:
            return "⛔ Delta API key/secret missing. Trading-scoped key required."
        self.armed = True
        delta_live.set_enabled(True)
        return (
            "⚡ *F&O ASTHRA LIVE: ON*\n"
            "OPTION BUY real execution • 10% free capital • signal SL • T1 trailing\n"
            "One position per underlying • restart defaults OFF"
        )

    async def disarm(self):
        self.armed = False
        return "⚡ *F&O ASTHRA LIVE: OFF*\nNew entries stopped. Open positions still monitored."

    async def kill(self):
        self.armed = False
        closed = 0
        for und, t in list(self.positions.items()):
            try:
                await self._close_market(t, reason="KILL")
                closed += 1
            except Exception as exc:
                logger.warning("[ASTHRA_LIVE] kill close %s: %s", t.option_symbol, exc)
        self.positions.clear()
        return f"🛑 *F&O ASTHRA KILLED*\nNew entries OFF • close attempts: {closed}"

    @staticmethod
    def _num(v, default=0.0):
        try:
            x = float(v)
            return x if math.isfinite(x) else default
        except (TypeError, ValueError):
            return default

    async def _available_capital(self):
        """Return (display_amount, asset, usd_estimate). Prefer USD/USDT, else INR."""
        if not delta_account_read_service.configured:
            return 0.0, "USD", 0.0
        rows = await delta_account_read_service.get_balances()
        best_usd = 0.0
        best_inr = 0.0
        for row in rows:
            asset = str(row.get("asset_symbol") or row.get("symbol") or "").upper()
            avail = self._num(row.get("available_balance"))
            if asset in {"USD", "USDT", "USDC"}:
                best_usd = max(best_usd, avail)
            elif asset in {"INR", "IND"}:
                best_inr = max(best_inr, avail)
        if best_usd > 0:
            return best_usd, "USD", best_usd
        if best_inr > 0:
            return best_inr, "INR", best_inr / USDINR
        return 0.0, "USD", 0.0

    async def on_signal(self, candidate):
        if not self.armed:
            return
        if not settings.LIVE_TRADING_ENABLED:
            return
        action = str(getattr(candidate, "action", "") or "").upper()
        if action not in {"OPTION BUY", "OPTION SELL"}:
            return
        underlying = str(getattr(candidate, "underlying", "") or "").upper()
        if underlying not in {"BTC", "ETH", "GOLD"} or underlying in self.positions:
            return
        setup_id = str(getattr(candidate, "setup_id", "") or "")
        if not setup_id or setup_id in self.seen_setups:
            return

        self.seen_setups[setup_id] = time.time()
        try:
            entry = self._num(getattr(candidate, "premium", 0))
            stop = self._num(getattr(candidate, "sl", 0))
            t1 = self._num(getattr(candidate, "t1", 0))
            t2 = self._num(getattr(candidate, "t2", 0))
            t3 = self._num(getattr(candidate, "t3", 0))
            strike = self._num(getattr(candidate, "strike", 0))
            expiry = str(getattr(candidate, "expiry", "") or "")
            symbol = str(getattr(candidate, "option_symbol", "") or "")
            if min(entry, stop, t1, t2, t3, strike) <= 0 or not expiry or not symbol:
                raise RuntimeError("signal option Entry/SL/targets/contract incomplete")
            if action == "OPTION BUY":
                if not (stop < entry < t1 <= t2 <= t3):
                    raise RuntimeError("OPTION BUY levels not ordered SL < Entry < T1 <= T2 <= T3")
                risk = entry - stop
                side = "buy"
            else:
                # OPTION SELL: premium short — SL above entry, targets below
                if not (t3 <= t2 <= t1 < entry < stop):
                    # still accept if engine sent BUY-style numbers on a sell label
                    if stop < entry < t1:
                        risk = entry - stop
                    else:
                        risk = abs(stop - entry)
                else:
                    risk = stop - entry
                side = "sell"

            available_display, asset, available_usd = await self._available_capital()
            if available_usd <= 0 and available_display <= 0:
                raise RuntimeError("no free capital available")
            allocation_display = available_display * ALLOCATION_PCT
            # Same logic as paper: free × 10% × 84x model / premium = contract size
            # Example: ₹2000 free → ₹200 margin → ₹16,800 notional → size = floor(16800/premium)
            model_buying_power_usd = max(available_usd * ALLOCATION_PCT * LEVERAGE_MODEL, 1.0)
            size = max(1, int(math.floor(model_buying_power_usd / max(entry, 1e-9))))
            size = min(size, int(getattr(settings, "LIVE_MAX_CONTRACTS", 5)))

            product_id = await delta_live.resolve_product_id(symbol)
            market = getattr(candidate, "market", None) or {}
            ask = self._num(market.get("ask"), entry)
            bid = self._num(market.get("bid"), entry)
            limit_px = (ask if ask > 0 else entry) if side == "buy" else (bid if bid > 0 else entry)
            req = LiveOrderRequest(
                product_id=product_id,
                symbol=symbol,
                side=side,
                size=size,
                order_type="limit_order",
                limit_price=limit_px,
                client_order_id=f"as{int(time.time()) % 10_000_000}",
                underlying=underlying,
                direction=str(getattr(candidate, "direction", "")),
                setup_id=setup_id,
                score=int(getattr(candidate, "adjusted_score", getattr(candidate, "score", 0)) or 0),
                entry_ref=entry,
                sl=stop,
                t1=t1,
                t2=t2,
                t3=t3,
            )
            pf = delta_live.preflight(req, live_price=limit_px, available_usd=available_usd)
            if not pf.get("ok"):
                raise RuntimeError("preflight: " + ", ".join(pf.get("reasons") or []))

            result = await delta_live.place_order(req, fingerprint=pf.get("fingerprint", ""))
            oid = str(result.get("order_id") or "")

            trade = OptionLiveTrade(
                underlying=underlying,
                option_symbol=symbol,
                product_id=product_id,
                strike=strike,
                expiry=expiry,
                entry=entry,
                stop=stop,
                t1=t1,
                t2=t2,
                t3=t3,
                risk=risk,
                size=size,
                order_id=oid,
                setup_id=setup_id,
                opened_at=time.time(),
                margin_display=allocation_display,
                margin_asset=asset,
                entry_side=side,
            )
            self.positions[underlying] = trade
            await self._alert(
                f"⚡ *ASTHRA LIVE ENTRY*\n"
                f"`{symbol}` {side.upper()} x{size}\n"
                f"Order `{oid}`\n"
                f"Entry `{entry:.6g}` | SL `{stop:.6g}` | T1 `{t1:.6g}`\n"
                f"Alloc ~{allocation_display:.2f} {asset} (10% free) · 84× model BP `${model_buying_power_usd:,.2f}`\n"
                f"T1 → trailing ON (no full exit)"
            )
        except Exception as exc:
            self.last_error = str(exc)[:200]
            logger.warning("[ASTHRA_LIVE] on_signal failed: %s", exc)
            await self._alert(f"⚠️ ASTHRA LIVE skip: {exc}")

    async def _quote(self, t: OptionLiveTrade) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """Return (bid, ask, mid) for the option contract."""
        und = "GOLD" if t.underlying == "GOLD" else t.underlying
        try:
            if und == "GOLD":
                snap = await delta_options_service.get_gold_strike_snapshot(t.strike, t.expiry)
            else:
                snap = await delta_options_service.get_strike_snapshot(und, t.strike, t.expiry)
            opt_side = "ce" if t.option_symbol.startswith("C-") else "pe"
            o = snap.get(opt_side) or {}
            bid = self._num(o.get("best_bid") or o.get("sell_executable"))
            ask = self._num(o.get("best_ask") or o.get("buy_executable"))
            mid = None
            if bid and ask and bid > 0 and ask >= bid:
                mid = (bid + ask) / 2.0
            else:
                mid = self._num(o.get("premium") or o.get("mark_price"))
            return (bid if bid and bid > 0 else None,
                    ask if ask and ask > 0 else None,
                    mid if mid and mid > 0 else None)
        except Exception as exc:
            logger.debug("[ASTHRA_LIVE] quote %s: %s", t.option_symbol, exc)
            return None, None, None

    async def _close_market(self, t: OptionLiveTrade, reason: str = "SL"):
        """Close position: long→sell at bid, short→buy at ask."""
        bid, ask, mid = await self._quote(t)
        close_side = "sell" if t.entry_side == "buy" else "buy"
        limit_px = bid if close_side == "sell" else ask
        req = LiveOrderRequest(
            product_id=t.product_id,
            symbol=t.option_symbol,
            side=close_side,
            size=t.size,
            order_type="limit_order" if limit_px else "market_order",
            limit_price=limit_px,
            reduce_only=True,
            client_order_id=f"ax{int(time.time()) % 10_000_000}",
            underlying=t.underlying,
            setup_id=t.setup_id,
            entry_ref=t.entry,
            sl=t.stop,
            t1=t.t1,
            t2=t.t2,
            t3=t.t3,
        )
        was = delta_live.config.trading_enabled
        delta_live.config.trading_enabled = True
        try:
            pf = delta_live.preflight(req, live_price=limit_px or t.entry, available_usd=1e9)
            result = await delta_live.place_order(req, fingerprint=pf.get("fingerprint", ""))
        finally:
            delta_live.config.trading_enabled = was
        t.closed = True
        px = limit_px or mid or t.entry
        if t.entry_side == "buy":
            pnl_r = (px - t.entry) / max(t.risk, 1e-9)
        else:
            pnl_r = (t.entry - px) / max(t.risk, 1e-9)
        await self._alert(
            f"🛑 *ASTHRA LIVE EXIT* ({reason})\n"
            f"`{t.option_symbol}` {close_side.upper()} x{t.size} @ `{px:.6g}`\n"
            f"PnL ~ `{pnl_r:+.2f}R` | order `{result.get('order_id', '')}`"
        )
        return result

    async def _monitor_one(self, t: OptionLiveTrade):
        if t.closed:
            return
        bid, ask, mid = await self._quote(t)
        # Mark-to-market: long uses bid (exit), short uses ask (exit)
        if t.entry_side == "buy":
            px = bid or mid
        else:
            px = ask or mid
        if px is None:
            return

        is_long = t.entry_side == "buy"
        if is_long:
            if t.best_price is None or px > t.best_price:
                t.best_price = px
        else:
            if t.best_price is None or px < t.best_price:
                t.best_price = px

        active_stop = t.trail_stop if t.trail_active and t.trail_stop is not None else t.stop
        hit_sl = (px <= active_stop) if is_long else (px >= active_stop)
        if hit_sl:
            await self._close_market(t, reason="TRAIL_SL" if t.trail_active else "SL")
            self.positions.pop(t.underlying, None)
            return

        hit_t1 = (px >= t.t1) if is_long else (px <= t.t1)
        if not t.trail_active and hit_t1:
            t.trail_active = True
            fee_buffer = max(0.01 * t.entry, 0.08 * t.risk)
            if is_long:
                base = t.entry + fee_buffer
                trail_gap = max(0.50 * t.risk, 0.04 * t.entry)
                t.trail_stop = max(base, px - trail_gap)
            else:
                base = t.entry - fee_buffer
                trail_gap = max(0.50 * t.risk, 0.04 * t.entry)
                t.trail_stop = min(base, px + trail_gap)
            await self._alert(
                f"✅ *ASTHRA LIVE T1* — `{t.option_symbol}` | trailing ON | trail SL `{t.trail_stop:.6g}`"
            )
            return

        if t.trail_active and t.best_price is not None:
            gap_r = 0.50
            if is_long:
                if px >= t.t3:
                    gap_r = 0.25
                elif px >= t.t2:
                    gap_r = 0.35
                trail_gap = max(gap_r * t.risk, 0.025 * t.entry)
                t.trail_stop = max(float(t.trail_stop or t.stop), t.best_price - trail_gap)
            else:
                if px <= t.t3:
                    gap_r = 0.25
                elif px <= t.t2:
                    gap_r = 0.35
                trail_gap = max(gap_r * t.risk, 0.025 * t.entry)
                t.trail_stop = min(float(t.trail_stop or t.stop), t.best_price + trail_gap)

    async def monitor_loop(self):
        while self.running:
            try:
                for t in list(self.positions.values()):
                    try:
                        await self._monitor_one(t)
                    except Exception as exc:
                        logger.debug("[ASTHRA_LIVE] monitor %s: %s", t.option_symbol, exc)
                cutoff = time.time() - 2 * 86400
                for k, ts in list(self.seen_setups.items()):
                    if ts < cutoff:
                        self.seen_setups.pop(k, None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[ASTHRA_LIVE] monitor loop: %s", exc)
            await asyncio.sleep(5)

    def status_text(self):
        rows = [
            f"⚡ *F&O ASTHRA LIVE: {'ON' if self.armed else 'OFF'}*",
            f"Env LIVE_TRADING_ENABLED: {'true' if settings.LIVE_TRADING_ENABLED else 'false'}",
            f"Credentials: {'OK' if delta_live.credentials_ok else 'MISSING'}",
            "Mode: OPTION BUY/SELL ready path • 10% free × 84x sizing • signal SL • T1 trail",
        ]
        if not self.positions:
            rows.append("Open live option positions: 0")
        else:
            rows.append(f"Open live option positions: {len(self.positions)}")
            for t in self.positions.values():
                trail = f" | Trail `{t.trail_stop:.6g}`" if t.trail_active and t.trail_stop else ""
                rows.append(
                    f"• {t.underlying} `{t.option_symbol}` x{t.size} | Entry `{t.entry:.6g}` | SL `{t.stop:.6g}`{trail}"
                )
        if self.last_error:
            rows.append(f"Last error: `{self.last_error}`")
        return "\n".join(rows)


fo_asthra_live = FOAsthraLive()
