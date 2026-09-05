import time
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.models.schemas import (LoginRequest, Subscription, OrderRequest, InstrumentSearchRequest, OptionResolveRequest,
    SignalEvalRequest, RiskCheckRequest, TradingToggle, OptionScanRequest, OptionRankRequest,
    LifecycleCreateRequest, LifecyclePriceRequest, ExecutionArmRequest, ExecutionIntentRequest, ExecutionConfirmRequest, OrderCancelRequest, OrderModifyRequest, PositionExitRequest, ExitPlanRequest, ExitAllConfirmRequest, ScannerStartRequest)
from app.services.broker import broker
from app.services.market_pipeline import candles
from app.services.instruments import instruments
from app.services.signal_engine import signal_engine
from app.services.risk import risk_engine
from app.services.options import option_selector
from app.services.lifecycle import signal_lifecycle
from app.services.execution import execution_engine
from app.services.positions import position_manager
from app.services.journal import journal
from app.services.recovery import recovery_store
from app.services.scanner import scanner_controller

app = FastAPI(title="NEO Signal Terminal API", version="1.0.0")

@app.middleware("http")
async def app_token_guard(request: Request, call_next):
    # Keep /health reachable for local/systemd health checks. All other routes can be
    # protected by APP_API_TOKEN. Empty token is allowed for local development only.
    if request.url.path != "/health" and settings.app_api_token:
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {settings.app_api_token}":
            return JSONResponse(status_code=401, content={"detail": "Invalid app token"})
    return await call_next(request)


@app.get("/health")
async def health():
    age = None if broker.last_market_message_at is None else max(0, time.time() - broker.last_market_message_at)
    return {"ok": True, "authenticated": broker.authenticated,
            "market_stream_running": bool(broker.market_task and not broker.market_task.done()),
            "order_stream_running": bool(broker.order_task and not broker.order_task.done()),
            "subscriptions": len(broker.subscriptions), "market_message_age_sec": age,
            "market_feed_stale": age is not None and age > 10, "risk": risk_engine.snapshot(), "execution": execution_engine.snapshot(), "live_order_submission_enabled": settings.live_order_submission_enabled, "live_orders_unlocked": settings.live_orders_unlocked, "app_token_protected": bool(settings.app_api_token), "server_time": time.time()}


@app.get("/ready")
async def ready():
    age = None if broker.last_market_message_at is None else max(0, time.time() - broker.last_market_message_at)
    checks = {
        "authenticated": broker.authenticated,
        "market_stream_running": bool(broker.market_task and not broker.market_task.done()),
        "order_stream_running": bool(broker.order_task and not broker.order_task.done()),
        "market_feed_fresh": age is not None and age <= 10,
        "live_orders_unlocked": settings.live_orders_unlocked,
    }
    # Readiness is for live-market validation, not a generic liveness check.
    return {"ready_for_live_market": all([checks["authenticated"], checks["market_stream_running"], checks["order_stream_running"], checks["market_feed_fresh"]]), "checks": checks, "market_message_age_sec": age}


@app.get("/app/bootstrap")
async def app_bootstrap():
    age = None if broker.last_market_message_at is None else max(0, time.time() - broker.last_market_message_at)
    return {
        "health": {
            "ok": True, "authenticated": broker.authenticated,
            "market_stream_running": bool(broker.market_task and not broker.market_task.done()),
            "order_stream_running": bool(broker.order_task and not broker.order_task.done()),
            "market_message_age_sec": age, "market_feed_stale": age is not None and age > 10,
        },
        "risk": risk_engine.snapshot(),
        "execution": execution_engine.snapshot(),
        "positions": position_manager.list(),
        "position_summary": position_manager.summary(),
        "signals": signal_lifecycle.list(),
        "signal_stats": signal_lifecycle.stats(),
        "latest_ticks": broker.latest_ticks,
        "indices": instruments.index_snapshot(),
        "scanner": scanner_controller.status(),
        "journal": journal.list(20),
        "recovery": {"instrument_registry": instruments.registry_snapshot(), "execution_rearmed": False},
        "server_time": time.time(),
    }

@app.get("/signals/lifecycle/{signal_id}")
async def lifecycle_get(signal_id: str):
    item = signal_lifecycle.items.get(signal_id)
    if item is None: raise HTTPException(404, "Signal not found")
    return item.to_dict()

@app.get("/auth/status")
async def auth_status():
    return {"authenticated": broker.authenticated, "market_stream_running": bool(broker.market_task and not broker.market_task.done()), "order_stream_running": bool(broker.order_task and not broker.order_task.done())}

@app.post("/auth/logout")
async def logout():
    execution_engine.arm(False)
    risk_engine.set_enabled(False)
    return await broker.logout()

@app.post("/auth/login")
async def login(body: LoginRequest):
    result = await broker.login(body.totp)
    if not result.get("ok"): raise HTTPException(status_code=401, detail=result)
    await broker.start_streams()
    restored = await instruments.restore_core_subscriptions()
    journal.add("system", "login_recovery", restored)
    return {**result, "recovery": restored}

@app.post("/market/subscribe")
async def subscribe(body: Subscription):
    if not broker.authenticated: raise HTTPException(401, "Login required")
    await broker.subscribe(body.exchange_segment, body.instrument_token, body.mode)
    return {"ok": True, "subscription": body.model_dump()}

@app.get("/market/quote")
async def quote(exchange_segment: str, instrument_token: str, quote_type: str = "all"):
    return await broker.quote(exchange_segment, instrument_token, quote_type)

@app.get("/market/latest")
async def latest(): return broker.latest_ticks

@app.get("/market/candles")
async def get_candles(symbol_key: str, timeframe_sec: int = 300, limit: int = 100):
    return {"symbol_key": symbol_key, "timeframe_sec": timeframe_sec, "candles": candles.get_history(symbol_key, timeframe_sec, limit)}

@app.post("/instruments/search")
async def instrument_search(body: InstrumentSearchRequest): return await instruments.search(**body.model_dump())

@app.get("/instruments/registry")
async def instrument_registry():
    return instruments.registry_snapshot()

@app.post("/system/recover")
async def system_recover():
    if not broker.authenticated:
        raise HTTPException(401, "Login required")
    restored = await instruments.restore_core_subscriptions()
    try:
        raw = await broker.positions()
        positions = position_manager.sync_rest(raw)
    except Exception as exc:
        positions = {"error": str(exc)}
    result = {"ok": restored.get("ok", False), "subscriptions": restored, "positions": positions, "registry": instruments.registry_snapshot()}
    journal.add("system", "manual_recovery", result)
    return result

@app.post("/instruments/sync-core")
async def sync_core_instruments():
    if not broker.authenticated: raise HTTPException(401, "Login required")
    result = await instruments.sync_core_indices()
    journal.add("instrument", "sync_core", result)
    return result

@app.get("/market/indices")
async def market_indices():
    return {"indices": instruments.index_snapshot()}

@app.get("/scanner/groups")
async def scanner_groups():
    return scanner_controller.groups()

@app.get("/scanner/status")
async def scanner_status():
    return scanner_controller.status()

@app.post("/scanner/start")
async def scanner_start(body: ScannerStartRequest):
    if not broker.authenticated:
        raise HTTPException(401, "Login required")
    try:
        return await scanner_controller.start(body.group)
    except RuntimeError as exc:
        if str(exc) == "LOGIN_REQUIRED":
            raise HTTPException(401, "Login required")
        raise

@app.post("/scanner/stop")
async def scanner_stop():
    return await scanner_controller.stop()

@app.post("/options/resolve")
async def resolve_option(body: OptionResolveRequest): return await instruments.resolve_option(**body.model_dump())

@app.post("/options/scan")
async def scan_options(body: OptionScanRequest):
    if not broker.authenticated: raise HTTPException(401, "Login required")
    return await instruments.scan_option_candidates(**body.model_dump())

@app.post("/options/rank")
async def rank_options(body: OptionRankRequest):
    return {"candidates": option_selector.rank(body.records, underlying_ltp=body.underlying_ltp,
        option_type=body.option_type, fallback_segment=body.exchange_segment)}

@app.post("/signals/lifecycle")
async def create_lifecycle(body: LifecycleCreateRequest):
    return signal_lifecycle.create(**body.model_dump())

@app.post("/signals/lifecycle/{signal_id}/price")
async def lifecycle_price(signal_id: str, body: LifecyclePriceRequest):
    if signal_id not in signal_lifecycle.items: raise HTTPException(404, "Signal not found")
    return signal_lifecycle.update_price(signal_id, body.price)

@app.get("/signals/lifecycle")
async def lifecycle_list(): return signal_lifecycle.list()

@app.get("/signals/stats")
async def lifecycle_stats(): return signal_lifecycle.stats()

@app.post("/signals/evaluate")
async def evaluate_signal(body: SignalEvalRequest):
    rows = candles.get_history(body.symbol_key, body.timeframe_sec, 100)
    if body.closed_only and rows:
        # Current bucket may still be forming; remove it.
        rows = rows[:-1]
    return signal_engine.evaluate(body.symbol_key, rows, body.timeframe_sec)

@app.get("/risk")
async def risk_state(): return risk_engine.snapshot()

@app.post("/risk/trading")
async def set_trading(body: TradingToggle):
    # This toggles the risk gate only. Live /orders/place remains locked in this milestone.
    risk_engine.set_enabled(body.enabled); return risk_engine.snapshot()

@app.post("/risk/check")
async def risk_check(body: RiskCheckRequest): return risk_engine.preflight(**body.model_dump())

@app.get("/portfolio/positions")
async def positions():
    raw = await broker.positions()
    position_manager.sync_rest(raw)
    return {"raw": raw, "normalized": position_manager.list(), "summary": position_manager.summary()}

@app.post("/portfolio/positions/refresh")
async def refresh_positions():
    if not broker.authenticated: raise HTTPException(401, "Login required")
    raw = await broker.positions()
    return {"positions": position_manager.sync_rest(raw), "summary": position_manager.summary()}

@app.get("/portfolio/positions/live")
async def live_positions(open_only: bool = False):
    return {"positions": position_manager.list(open_only), "summary": position_manager.summary()}

@app.post("/portfolio/exit-plan")
async def create_exit_plan(body: ExitPlanRequest):
    try:
        return position_manager.create_exit_plan(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc))

@app.get("/portfolio/exit-plans")
async def exit_plans():
    return [x.to_dict() for x in position_manager.exit_plans.values()]

@app.post("/portfolio/exit-intent")
async def position_exit_intent(body: PositionExitRequest):
    if not broker.authenticated: raise HTTPException(401, "Login required")
    p = position_manager.get(body.position_key)
    if not p or p.net_quantity == 0: raise HTTPException(404, "Open position not found")
    try:
        order = position_manager.build_exit_order(body.position_key, body.quantity)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    qty = int(order["quantity"]); side = "SELL" if order["transaction_type"] == "S" else "BUY"
    ref = p.ltp or p.average_price
    return execution_engine.create_intent(order=order, symbol=p.trading_symbol, side=side, quantity=qty,
        reference_price=ref, live_price=p.ltp, open_positions=position_manager.summary()["open_positions"],
        day_pnl=position_manager.summary()["day_mtm"], signal_id=None)

@app.post("/portfolio/exit-all")
async def exit_all(body: ExitAllConfirmRequest):
    if body.confirmation_text.strip().upper() != "EXIT ALL": raise HTTPException(400, "confirmation_text must be EXIT ALL")
    if not broker.authenticated: raise HTTPException(401, "Login required")
    if not risk_engine.config.trading_enabled or not execution_engine.armed:
        raise HTTPException(409, "Risk trading and execution arm must both be enabled")
    results=[]
    for p in list(position_manager.items.values()):
        if p.net_quantity == 0: continue
        try:
            response = await broker.place_order(**position_manager.build_exit_order(p.key))
            results.append({"position_key":p.key,"ok":True,"broker_response":response})
        except Exception as exc:
            results.append({"position_key":p.key,"ok":False,"error":str(exc)})
    return {"ok":all(x["ok"] for x in results), "results":results}
@app.get("/portfolio/holdings")
async def holdings(): return await broker.holdings()
@app.get("/portfolio/limits")
async def limits(): return await broker.limits()
@app.get("/orders")
async def orders(): return await broker.orders()

@app.get("/orders/{order_id}")
async def order_detail(order_id: str):
    if not broker.authenticated: raise HTTPException(401, "Login required")
    return await broker.order_by_id(order_id)

@app.get("/journal")
async def journal_list(limit: int = 100, category: str | None = None):
    return journal.list(limit, category)

@app.get("/execution")
async def execution_state(): return execution_engine.snapshot()

@app.post("/execution/arm")
async def execution_arm(body: ExecutionArmRequest):
    # Two-gate safety: risk trading AND execution arm must both be enabled.
    if body.enabled and not risk_engine.config.trading_enabled:
        raise HTTPException(409, "Enable risk trading gate first")
    return execution_engine.arm(body.enabled)

@app.post("/execution/intent")
async def execution_intent(body: ExecutionIntentRequest):
    if not broker.authenticated: raise HTTPException(401, "Login required")
    side = "BUY" if body.transaction_type.upper() in {"B", "BUY"} else "SELL"
    order = {
        "exchange_segment": body.exchange_segment, "product": body.product, "price": body.price,
        "order_type": body.order_type, "quantity": str(body.quantity), "validity": body.validity,
        "trading_symbol": body.trading_symbol, "transaction_type": body.transaction_type,
        "trigger_price": body.trigger_price, "amo": body.amo,
        "disclosed_quantity": body.disclosed_quantity,
    }
    # Correlate broker reports with this execution intent using the SDK tag field.
    result = execution_engine.create_intent(order=order, symbol=body.trading_symbol, side=side,
        quantity=body.quantity, reference_price=body.reference_price, live_price=body.live_price,
        open_positions=body.open_positions, day_pnl=body.day_pnl, signal_id=body.signal_id)
    if result.get("ok"):
        order["tag"] = f"NST-{result['intent_id']}"
    return result

@app.post("/execution/{intent_id}/confirm")
async def execution_confirm(intent_id: str, body: ExecutionConfirmRequest):
    if not broker.authenticated: raise HTTPException(401, "Login required")
    result = await execution_engine.confirm(intent_id=intent_id, confirmation_token=body.confirmation_token,
        live_price=body.live_price, open_positions=body.open_positions, day_pnl=body.day_pnl,
        submitter=broker.place_order)
    if not result.get("ok") and "INTENT_NOT_FOUND" in result.get("reasons", []): raise HTTPException(404, result)
    journal.add("execution", "confirm", result, intent_id)
    return result

@app.get("/execution/history")
async def execution_history(limit: int = 100): return execution_engine.list(limit)

@app.get("/execution/{intent_id}")
async def execution_get(intent_id: str):
    item = execution_engine.get(intent_id)
    if not item: raise HTTPException(404, "Execution not found")
    return item

@app.post("/execution/kill-switch")
async def kill_switch():
    risk_engine.set_enabled(False)
    execution_engine.arm(False)
    return {"ok": True, "risk": risk_engine.snapshot(), "execution": execution_engine.snapshot(),
            "note": "New orders blocked immediately; this endpoint does not silently create exit orders."}

@app.post("/orders/cancel")
async def cancel_order(body: OrderCancelRequest):
    if not broker.authenticated: raise HTTPException(401, "Login required")
    if not execution_engine.armed: raise HTTPException(409, "Execution not armed")
    result = await broker.cancel_order(body.order_id, body.amo)
    journal.add("order", "cancel", result, body.order_id)
    return result

@app.post("/orders/modify")
async def modify_order(body: OrderModifyRequest):
    if not broker.authenticated: raise HTTPException(401, "Login required")
    if not execution_engine.armed: raise HTTPException(409, "Execution not armed")
    result = await broker.modify_order(**body.model_dump())
    journal.add("order", "modify", result, body.order_id)
    return result

@app.post("/orders/place")
async def place_order(body: OrderRequest):
    raise HTTPException(status_code=405, detail="Direct live order endpoint disabled. Use /execution/intent then /execution/{intent_id}/confirm.")

@app.websocket("/ws/ticks")
async def ticks(websocket: WebSocket):
    if settings.app_api_token and websocket.query_params.get("token") != settings.app_api_token:
        await websocket.close(code=4401)
        return
    await websocket.accept(); q = broker.new_listener()
    try:
        while True: await websocket.send_json(await q.get())
    except WebSocketDisconnect: pass
    finally: broker.remove_listener(q)
