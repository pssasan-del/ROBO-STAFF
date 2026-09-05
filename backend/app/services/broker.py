import asyncio
from typing import Any
from neo_api_client import NeoAPI
from neo_api_client.websocket.feed import WsToken
from app.core.config import settings
from app.services.market_pipeline import candles
from app.services.lifecycle import signal_lifecycle
from app.services.execution import execution_engine
from app.services.positions import position_manager
from app.services.journal import journal
from app.services.signal_engine import signal_engine

class BrokerService:
    def __init__(self) -> None:
        self.client: NeoAPI | None = None
        self.authenticated = False
        self.market_ws = None
        self.market_task: asyncio.Task | None = None
        self.order_task: asyncio.Task | None = None
        self.latest_ticks: dict[str, dict[str, Any]] = {}
        self.subscriptions: dict[str, tuple[str, str, str]] = {}
        self.listeners: set[asyncio.Queue] = set()
        self.last_market_message_at: float | None = None
        self.last_order_message_at: float | None = None
        self._lock = asyncio.Lock()
        self.symbol_aliases: dict[str, str] = {}
        self.signal_scan_keys: set[str] = set()
        self.core_signal_keys: set[str] = {"nse_cm|Nifty 50", "nse_cm|Nifty Bank", "bse_cm|Sensex"}

    def _ensure_client(self) -> NeoAPI:
        if not settings.kotak_consumer_key:
            raise RuntimeError("KOTAK_CONSUMER_KEY is not configured")
        if self.client is None:
            self.client = NeoAPI(consumer_key=settings.kotak_consumer_key, environment="prod")
        return self.client

    async def login(self, totp: str) -> dict[str, Any]:
        client = self._ensure_client()
        login = await asyncio.to_thread(client.totp_login, settings.kotak_mobile_number, settings.kotak_ucc, totp)
        if "error" in login or "Error" in login:
            return {"ok": False, "step": "totp_login", "response": login}
        validate = await asyncio.to_thread(client.totp_validate, settings.kotak_mpin)
        if "error" in validate or "Error" in validate:
            return {"ok": False, "step": "totp_validate", "response": validate}
        self.authenticated = True
        journal.add("auth", "login", {"ok": True})
        return {"ok": True, "step": "authenticated"}


    async def logout(self):
        self.authenticated = False
        for task in (self.market_task, self.order_task):
            if task and not task.done(): task.cancel()
        self.market_task = None; self.order_task = None; self.market_ws = None
        try:
            if self.client is not None and hasattr(self.client, "logout"):
                result = await asyncio.to_thread(self.client.logout)
            else:
                result = {"ok": True}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        journal.add("auth", "logout", result)
        return {"ok": True, "broker": result}

    async def start_streams(self) -> None:
        if not self.authenticated or self.client is None:
            raise RuntimeError("Kotak session is not authenticated")
        async with self._lock:
            if not self.market_task or self.market_task.done():
                self.market_task = asyncio.create_task(self._market_loop(), name="kotak-market-feed")
            if not self.order_task or self.order_task.done():
                self.order_task = asyncio.create_task(self._order_loop(), name="kotak-order-feed")

    async def _market_loop(self) -> None:
        assert self.client is not None
        import time
        while self.authenticated:
            try:
                async with self.client.create_websocket(
                    reconnect_delay=2,
                    max_reconnect_attempts=20,
                    max_connect_retries=5,
                    ping_interval=20,
                ) as ws:
                    self.market_ws = ws
                    await self._resubscribe_all(ws)
                    async for msg in ws:
                        self.last_market_message_at = time.time()
                        payload = msg.model_dump() if hasattr(msg, "model_dump") else {"value": str(msg)}
                        token = payload.get("instrument_token")
                        segment = payload.get("exchange_segment")

                        if payload.get("type") == "index" and payload.get("name"):
                            index_name = str(payload.get("name"))
                            index_alias = {
                                "Nifty 50": "Nifty 50",
                                "Nifty Bank": "Nifty Bank",
                                "SENSEX": "Sensex",
                            }.get(index_name, index_name)
                            key = f"{segment}|{index_alias}"
                        else:
                            raw_key = f"{segment}|{token}" if token is not None else f"market|{payload.get('type','event')}"
                            key = self.symbol_aliases.get(raw_key, raw_key)
                        self.latest_ticks[key] = payload
                        ltp = payload.get("last_traded_price")
                        event_ts = payload.get("last_trade_time") or payload.get("last_update_time") or int(time.time())
                        day_volume = payload.get("volume_traded_today")
                        if token is not None and ltp is not None and event_ts:
                            try:
                                price = float(ltp)
                                changed_positions = position_manager.on_tick(str(segment), str(token), price)
                                for pos in changed_positions:
                                    await self._broadcast({"channel": "positions", "event": "mtm", "data": pos})
                                    exit_events = await position_manager.evaluate_exit_plans(pos["key"], price, submitter=self.place_order)
                                    for evt in exit_events:
                                        await self._broadcast({"channel": "exit_plan", "event": evt.get("state", "updated"), "data": evt})
                                closed = candles.ingest(key, price, int(event_ts), int(day_volume) if day_volume is not None else None)
                                for candle in closed:
                                    await self._broadcast({"channel": "candle", "data": candle.to_dict()})

                                    # Auto-evaluate strict strategy on each CLOSED 5M candle.
                                    # Core indices are always eligible; stocks only when their selected 45-stock group is active.
                                    if candle.timeframe_sec == 300 and (key in self.core_signal_keys or key in self.signal_scan_keys):
                                        rows = candles.get_history(key, 300, 100)

                                        # get_history includes the newly forming candle. Remove it.
                                        if rows:
                                            rows = rows[:-1]

                                        result = signal_engine.evaluate(key, rows, 300)

                                        await self._broadcast({
                                            "channel": "signal_scan",
                                            "symbol_key": key,
                                            "data": result,
                                        })

                                        if result.get("status") == "SIGNAL":
                                            signal = result["signal"]
                                            # Cooldown avoids repeating essentially the same setup every 5 minutes.
                                            if not signal_lifecycle.has_recent(key, str(signal.get("side")), 900):
                                                tracked = signal_lifecycle.create(
                                                    symbol_key=key,
                                                    side=str(signal["side"]),
                                                    entry=float(signal["entry"]),
                                                    stop=float(signal["stop"]),
                                                    target1=float(signal["target1"]),
                                                    target2=float(signal["target2"]),
                                                    target3=float(signal.get("target3")) if signal.get("target3") is not None else None,
                                                    score=int(signal.get("score") or 0),
                                                    rr=float(signal.get("rr") or 0),
                                                    reason=str(signal.get("reason") or ""),
                                                    timeframe_sec=int(signal.get("timeframe_sec") or 300),
                                                    rsi14=float(signal.get("rsi14")) if signal.get("rsi14") is not None else None,
                                                    williams_r14=float(signal.get("williams_r14")) if signal.get("williams_r14") is not None else None,
                                                )
                                                await self._broadcast({
                                                    "channel": "signal",
                                                    "event": "new",
                                                    "data": tracked,
                                                })
                                for tracked in list(signal_lifecycle.items.values()):
                                    if tracked.symbol_key == key:
                                        before = tracked.state.value
                                        updated = signal_lifecycle.update_price(tracked.id, price)
                                        if updated["state"] != before:
                                            await self._broadcast({"channel": "signal_lifecycle", "event": "state_changed", "data": updated})
                            except (TypeError, ValueError):
                                pass
                        await self._broadcast({"channel": "market", "data": payload})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._broadcast({"channel": "system", "event": "market_feed_error", "error": str(exc)})
                await asyncio.sleep(2)

    async def _order_loop(self) -> None:
        assert self.client is not None
        import time
        while self.authenticated:
            try:
                async with self.client.create_order_feed(
                    reconnect_delay=2,
                    max_reconnect_attempts=20,
                    max_connect_retries=5,
                    ping_interval=20,
                ) as feed:
                    async for msg in feed:
                        self.last_order_message_at = time.time()
                        payload = msg.model_dump() if hasattr(msg, "model_dump") else {"value": str(msg)}
                        reconciled = execution_engine.on_order_update(payload)
                        position_update = position_manager.on_position_update(payload) if payload.get("type") == "position" else None
                        journal.add("broker", "order_update", payload, str(payload.get("order_id") or payload.get("nOrdNo") or "") or None)
                        await self._broadcast({"channel": "orders", "data": payload})
                        if position_update is not None:
                            await self._broadcast({"channel": "positions", "event": "position_update", "data": position_update})
                        if reconciled is not None:
                            await self._broadcast({"channel": "execution", "event": "state_changed", "data": reconciled})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._broadcast({"channel": "system", "event": "order_feed_error", "error": str(exc)})
                await asyncio.sleep(2)


    async def recycle_market_stream(self) -> None:
        """Reconnect only the market websocket so removed scanner subscriptions truly stop consuming feed data."""
        async with self._lock:
            task = self.market_task
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            self.market_task = None
            self.market_ws = None
            if self.authenticated:
                self.market_task = asyncio.create_task(self._market_loop(), name="kotak-market-feed")

    async def subscribe(self, exchange_segment: str, instrument_token: str, mode: str = "scrip") -> None:
        key = f"{exchange_segment}|{instrument_token}|{mode}"
        self.subscriptions[key] = (exchange_segment, instrument_token, mode)
        if self.market_ws and self.market_ws.is_connected:
            await self._apply_subscription(self.market_ws, exchange_segment, instrument_token, mode)

    async def _resubscribe_all(self, ws) -> None:
        for segment, token, mode in list(self.subscriptions.values()):
            await self._apply_subscription(ws, segment, token, mode)

    @staticmethod
    async def _apply_subscription(ws, segment: str, token: str, mode: str) -> None:
        tokens = [WsToken(segment, token)]
        fn = {
            "scrip": ws.subscribe_scrips,
            "lite": ws.subscribe_scrips_lite,
            "depth": ws.subscribe_depth,
            "full_depth": ws.subscribe_full_depth,
            "index": ws.subscribe_index,
        }[mode]
        await fn(tokens)

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        dead = []
        for q in self.listeners:
            try:
                if q.full():
                    _ = q.get_nowait()  # drop oldest UI update; never block broker feed
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
        for q in dead:
            self.listeners.discard(q)

    def new_listener(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=250)
        self.listeners.add(q)
        return q

    def remove_listener(self, q: asyncio.Queue) -> None:
        self.listeners.discard(q)

    async def quote(self, exchange_segment: str, instrument_token: str, quote_type: str = "all"):
        client = self._ensure_client()
        return await asyncio.to_thread(client.quotes, [{"instrument_token": instrument_token, "exchange_segment": exchange_segment}], quote_type)

    async def search(self, exchange_segment: str, symbol: str):
        client = self._ensure_client()
        return await asyncio.to_thread(client.search_scrip, exchange_segment, symbol)

    async def positions(self):
        return await asyncio.to_thread(self._ensure_client().positions)

    async def holdings(self):
        return await asyncio.to_thread(self._ensure_client().holdings)

    async def limits(self):
        return await asyncio.to_thread(self._ensure_client().limits)

    async def orders(self):
        return await asyncio.to_thread(self._ensure_client().order_report)

    async def order_by_id(self, order_id: str):
        return await asyncio.to_thread(self._ensure_client().order_report, order_id)

    async def cancel_order(self, order_id: str, amo: str = "NO"):
        return await asyncio.to_thread(self._ensure_client().cancel_order, order_id, amo)

    async def modify_order(self, **kwargs):
        return await asyncio.to_thread(self._ensure_client().modify_order, **kwargs)

    async def place_order(self, **kwargs):
        # Stage 12 deployment safety: real order submission is OFF unless explicitly enabled.
        if not settings.live_orders_unlocked:
            raise RuntimeError("LIVE_ORDER_SUBMISSION_LOCKED")
        return await asyncio.to_thread(self._ensure_client().place_order, **kwargs)

broker = BrokerService()
