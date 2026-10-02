import asyncio, time
from contextlib import asynccontextmanager
from fastapi import FastAPI

from config import settings, logger
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from option_premium_history_service import option_premium_history_service
from strategy_store import strategy_store
from bot import telegram_bot
from delta_signal_engine import delta_auto_engine
from master_mind_scalp import master_mind_scalp_engine
from short_signal_formatter import format_short_signal
from precision_overlay import install_precision_overlay
from v7_taker_flow import install_v7_taker_flow, V7_VERSION
from v7_status_overlay import install_v7_status_overlay
from polish_policy import DAILY_SIGNAL_CAP
from trend_breakout_retest_v1 import tbr_engine, VERSION as TBR_VERSION
from trend_breakout_retest_telegram import install_tbr_telegram


async def heartbeat_loop():
    while True:
        try:
            ws_age=(time.time()-delta_market_service.last_ws_message) if delta_market_service.last_ws_message else None
            logger.info("[HEARTBEAT] app=alive delta_ws=%s ws_age=%s reconnects=%s","connected" if delta_market_service.ws_connected else "reconnecting/rest",f"{ws_age:.0f}s" if ws_age is not None else "n/a",delta_market_service.reconnect_count)
        except asyncio.CancelledError:raise
        except Exception as exc:logger.warning("[HEARTBEAT] health check failed safely: %s",exc)
        await asyncio.sleep(max(30,settings.HEARTBEAT_SECONDS))


@asynccontextmanager
async def lifespan(app:FastAPI):
    strategy_store.init()
    print("\n"+"="*64)
    print(" DELTA CRYPTO AI BOT V9 - ALERTS ONLY")
    print("="*64)
    print(f" [ROBO STAFF] {V7_VERSION}: ENABLED")
    print(" [V7.1] 24H scalp alerts: ENABLED; 12:00-17:59 UTC is a quality boost only")
    print(" [V7.1] 15M primary trend; 1H only vetoes strong opposition")
    print(" [V7.1] 5M pullback/resume OR strong continuation; 1M timing supportive")
    print(" [V7.1] RVOL floor: 0.60 liquid window / 0.75 off-window")
    print(" [V7.1] taker-flow + liquid option overlay: ENABLED")
    print(f" [TBR V1] {TBR_VERSION}: SEPARATE BTC/ETH FUTURES SIGNAL ENGINE")
    print(" [TBR V1] minimum 18 completed candles; uses more history when available")
    print(" [TBR V1] 15M trend -> 5M breakout -> <=3 bar retest -> executable bid/ask")
    print(" [TBR V1] cost/obstacle/risk gates + separate paper success-rate tracking")
    print(" [MASTER MIND] BTCUSD + XAUTUSD: ENABLED / UNCHANGED")
    print(" [TELEGRAM] ROBO STAFF + TBR V1 + MASTER MIND alerts: ENABLED")
    print(" [AUTO/LIVE ORDER EXECUTION] DISABLED")
    print("="*64+"\n")

    install_precision_overlay(delta_auto_engine)
    install_v7_taker_flow(delta_auto_engine)
    install_v7_status_overlay(telegram_bot)
    install_tbr_telegram(telegram_bot,tbr_engine)
    delta_auto_engine.set_alert_callback(telegram_bot.broadcast)
    delta_auto_engine.format_signal=lambda c:format_short_signal(delta_auto_engine,c)
    master_mind_scalp_engine.set_alert_callback(telegram_bot.broadcast)
    tbr_engine.set_alert_callback(telegram_bot.broadcast)

    tasks=[
        asyncio.create_task(telegram_bot.poll(),name="telegram-poll"),
        asyncio.create_task(delta_market_service.websocket_loop(),name="delta-ws"),
        asyncio.create_task(delta_auto_engine.loop(),name="delta-auto-signal-engine"),
        asyncio.create_task(master_mind_scalp_engine.loop(),name="master-mind-btc-xaut-scalp"),
        asyncio.create_task(tbr_engine.loop(),name="trend-breakout-retest-v1"),
        asyncio.create_task(heartbeat_loop(),name="heartbeat"),
    ]
    logger.info("[APP] V7.1=%s TBR=%s master_mind=%s",getattr(delta_auto_engine,"v7_1_scalp_opportunity_installed",False),TBR_VERSION,["BTCUSD","XAUTUSD"])
    yield
    telegram_bot.running=False;delta_auto_engine.running=False;master_mind_scalp_engine.running=False;tbr_engine.running=False;delta_market_service.running=False
    for t in tasks:t.cancel()
    await asyncio.gather(*tasks,return_exceptions=True)
    await telegram_bot.client.aclose();await delta_market_service.close();await delta_options_service.client.aclose();await option_premium_history_service.close()


app=FastAPI(title="Delta Crypto AI Bot V9",lifespan=lifespan)

@app.get("/")
def root():
    return {"service":"Delta Crypto AI Bot V9","status":"online","mode":"v7-1-plus-tbr-v1-plus-master-mind-signal-only","provider":"Delta Exchange India public APIs","timestamp":time.time()}

@app.head("/")
def head():return None

@app.get("/health")
def health():
    now=time.time()
    return {
        "status":"healthy","mode":"v7-1-plus-tbr-v1-plus-master-mind-signal-only","strategy_epoch":V7_VERSION,
        "delta_ws":delta_market_service.ws_connected,
        "delta_ws_age_seconds":round(now-delta_market_service.last_ws_message,1) if delta_market_service.last_ws_message else None,
        "delta_ws_reconnects":delta_market_service.reconnect_count,
        "v7_taker_flow":bool(getattr(delta_auto_engine,"v7_taker_flow_installed",False)),
        "v7_1_scalp_opportunity":bool(getattr(delta_auto_engine,"v7_1_scalp_opportunity_installed",False)),
        "v7_alert_window":"24h","v7_liquid_window_utc":"12:00-17:59 boost only",
        "v7_core_short_taker_max":0.49,"v7_core_long_taker_min":0.51,
        "v7_offhour_short_taker_max":0.48,"v7_offhour_long_taker_min":0.52,
        "v7_min_rvol_liquid":0.60,"v7_min_rvol_offhour":0.75,
        "robo_staff_universe":["BTC","ETH"],"robo_staff_daily_signal_cap":dict(DAILY_SIGNAL_CAP),
        "dual_win_status_tracking":True,"telegram_alerts":True,
        "tbr_v1_enabled":True,"tbr_v1_version":TBR_VERSION,"tbr_v1_min_closed_candles":18,
        "tbr_v1_symbols":["BTCUSD","ETHUSD"],"tbr_v1_active_paper_tracks":len(tbr_engine.active),
        "tbr_v1_last_status":tbr_engine.last_status,"tbr_v1_scan_errors":tbr_engine.scan_errors,
        "master_mind_enabled":True,"master_mind_status":master_mind_scalp_engine.last_status,
        "master_mind_status_by_symbol":master_mind_scalp_engine.last_status_by_symbol,
        "master_mind_symbols":["BTCUSD","XAUTUSD"],
        "master_mind_last_scan_age_seconds":round(now-master_mind_scalp_engine.last_scan_at,1) if master_mind_scalp_engine.last_scan_at else None,
        "paper_trading":False,"tbr_paper_tracking":True,"auto_trade_prep":False,"live_execution":False,"symbols":settings.delta_symbols(),"auto_trading":False
    }
