import asyncio, time
from contextlib import asynccontextmanager
from fastapi import FastAPI

from config import settings, logger
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from option_premium_history_service import option_premium_history_service
from strategy_store import strategy_store
from bot import telegram_bot
from master_mind_scalp import master_mind_scalp_engine, MASTER_MIND_VERSION
from master_mind_only_telegram import install_master_mind_only_telegram
from trend_breakout_retest_v1 import tbr_engine, VERSION as TBR_VERSION
from delta_signal_engine import delta_auto_engine
from precision_overlay import install_precision_overlay


async def heartbeat_loop():
    while True:
        try:
            ws_age = (time.time() - delta_market_service.last_ws_message) if delta_market_service.last_ws_message else None
            logger.info(
                "[HEARTBEAT] app=alive mode=master-mind-only delta_ws=%s ws_age=%s reconnects=%s",
                "connected" if delta_market_service.ws_connected else "reconnecting/rest",
                f"{ws_age:.0f}s" if ws_age is not None else "n/a",
                delta_market_service.reconnect_count,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[HEARTBEAT] health check failed safely: %s", exc)
        await asyncio.sleep(max(30, settings.HEARTBEAT_SECONDS))


@asynccontextmanager
async def lifespan(app: FastAPI):
    strategy_store.init()
    print("\n" + "=" * 64)
    print(" DELTA CRYPTO AI BOT V9 - MULTI SIGNAL / NO EXECUTION")
    print("=" * 64)
    print(f" [MASTER MIND] {MASTER_MIND_VERSION}: ENABLED")
    print(" [MASTER MIND] Symbols: BTCUSD + XAUTUSD (GOLD)")
    print(" [MASTER MIND] Telegram alerts: ENABLED")
    print(" [ROBO STAFF V7.1 OPTION BUY] ENABLED")
    print(f" [TBR V1 FUTURES] {TBR_VERSION}: ENABLED")
    print(" [OTHER BACKGROUND SIGNAL GENERATORS] DISABLED")
    print(" [AUTO/LIVE ORDER EXECUTION] DISABLED")
    print("=" * 64 + "\n")

    install_master_mind_only_telegram(telegram_bot, master_mind_scalp_engine)
    # Preserve MASTER MIND unchanged; add the two signal-only engines in parallel.
    install_precision_overlay(delta_auto_engine)
    master_mind_scalp_engine.set_alert_callback(telegram_bot.broadcast)
    delta_auto_engine.set_alert_callback(telegram_bot.broadcast)
    tbr_engine.set_alert_callback(telegram_bot.broadcast)

    tasks = [
        asyncio.create_task(telegram_bot.poll(), name="telegram-poll"),
        asyncio.create_task(delta_market_service.websocket_loop(), name="delta-ws"),
        asyncio.create_task(master_mind_scalp_engine.loop(), name="master-mind-btc-xaut-scalp"),
        asyncio.create_task(delta_auto_engine.loop(), name="robo-staff-v7-option-buy"),
        asyncio.create_task(tbr_engine.loop(), name="tbr-v1-btc-eth-futures"),
        asyncio.create_task(heartbeat_loop(), name="heartbeat"),
    ]
    logger.info("[APP] MASTER MIND preserved + ROBO STAFF option-buy + TBR futures enabled; no order execution")
    yield

    telegram_bot.running = False
    master_mind_scalp_engine.running = False
    delta_auto_engine.running = False
    tbr_engine.running = False
    delta_market_service.running = False
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await telegram_bot.client.aclose()
    await delta_market_service.close()
    await delta_options_service.client.aclose()
    await option_premium_history_service.close()


app = FastAPI(title="Delta Crypto AI Bot V9", lifespan=lifespan)


@app.get("/")
def root():
    return {
        "service": "Delta Crypto AI Bot V9",
        "status": "online",
        "mode": "multi-signal-no-execution",
        "provider": "Delta Exchange India public APIs",
        "timestamp": time.time(),
    }


@app.head("/")
def head():
    return None


@app.get("/health")
def health():
    now = time.time()
    return {
        "status": "healthy",
        "mode": "multi-signal-no-execution",
        "delta_ws": delta_market_service.ws_connected,
        "delta_ws_age_seconds": round(now - delta_market_service.last_ws_message, 1) if delta_market_service.last_ws_message else None,
        "delta_ws_reconnects": delta_market_service.reconnect_count,
        "telegram_alerts": True,
        "master_mind_enabled": True,
        "master_mind_only": False,
        "master_mind_version": MASTER_MIND_VERSION,
        "master_mind_status": master_mind_scalp_engine.last_status,
        "master_mind_status_by_symbol": master_mind_scalp_engine.last_status_by_symbol,
        "master_mind_reason_by_symbol": master_mind_scalp_engine.last_reason_by_symbol,
        "master_mind_symbols": ["BTCUSD", "XAUTUSD"],
        "master_mind_last_scan_age_seconds": round(now - master_mind_scalp_engine.last_scan_at, 1) if master_mind_scalp_engine.last_scan_at else None,
        "robo_staff_v7_1_enabled": True,
        "robo_staff_v7_1_mode": "OPTION_BUY_SIGNAL_ONLY",
        "tbr_v1_enabled": True,
        "tbr_v1_version": TBR_VERSION,
        "tbr_v1_status": tbr_engine.last_status,
        "tbr_v1_last_scan_age_seconds": round(now - tbr_engine.last_scan_at, 1) if tbr_engine.last_scan_at else None,
        "other_background_signal_generators": False,
        "paper_trading": False,
        "auto_trade_prep": False,
        "live_execution": False,
        "auto_trading": False,
    }
