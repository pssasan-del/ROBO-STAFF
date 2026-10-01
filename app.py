import asyncio,time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from config import settings,logger
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from option_premium_history_service import option_premium_history_service
from strategy_store import strategy_store
from bot import telegram_bot
from delta_signal_engine import delta_auto_engine
from master_mind_scalp import master_mind_scalp_engine
from short_signal_formatter import format_short_signal
from precision_overlay import install_precision_overlay
from active_flow_indicator_overlay import install_active_flow_indicator_overlay
from polish_policy import DAILY_SIGNAL_CAP

# Signal-only mode: keep the frequency gate high enough that the engine does not
# stop after the earlier 48-signal daily total. Master Mind remains independent.
DAILY_SIGNAL_CAP.update({'BTC':60,'ETH':60,'GOLD':40})

async def heartbeat_loop():
    """Lightweight internal health heartbeat. It does not bypass Render sleep; it confirms recovery once the service is awake."""
    while True:
        try:
            ws_age=(time.time()-delta_market_service.last_ws_message) if delta_market_service.last_ws_message else None
            logger.info('[HEARTBEAT] app=alive delta_ws=%s ws_age=%s reconnects=%s',
                        'connected' if delta_market_service.ws_connected else 'reconnecting/rest',
                        f'{ws_age:.0f}s' if ws_age is not None else 'n/a', delta_market_service.reconnect_count)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('[HEARTBEAT] health check failed safely: %s',exc)
        await asyncio.sleep(max(30,settings.HEARTBEAT_SECONDS))

@asynccontextmanager
async def lifespan(app:FastAPI):
    strategy_store.init()
    print('\n'+'='*58)
    print(' DELTA CRYPTO AI BOT V9 - ALERTS ONLY')
    print('='*58)
    print(' [DELTA] Public market data + options: NO API KEY REQUIRED')
    print(f' [SYMBOLS] {settings.delta_symbols()}')
    print(f" [TELEGRAM] {'configured' if settings.TELEGRAM_BOT_TOKEN else 'NOT SET'}")
    print(f" [GEMINI] {'configured' if settings.GEMINI_API_KEY else 'NOT SET'}")
    print(' [RECOVERY] Delta WS auto-reconnect + heartbeat: ENABLED')
    print(' [ROBO STAFF] V4.2 ACTIVE FLOW — PREMIUM + OI CONFIRMATION: ENABLED')
    print(' [ROBO STAFF] Underlying 5M EMA5 + EMA9/18 + RSI/W%R + Fib P/R1/S1: ENABLED')
    print(' [ROBO STAFF] Option premium 5M EMA5 gate + EMA9/18/RSI/W%R/structure score: ENABLED')
    print(' [ROBO STAFF] Option OI history + nearby strike OI/liquidity score: ENABLED')
    print(' [ROBO STAFF] Daily Fib P/R1/S1: CONTEXT ONLY')
    print(' [ROBO STAFF] T1 target: 1.85R')
    print(f' [ROBO STAFF] Daily caps: BTC {DAILY_SIGNAL_CAP["BTC"]} | ETH {DAILY_SIGNAL_CAP["ETH"]} | GOLD {DAILY_SIGNAL_CAP["GOLD"]}')
    print(' [MASTER MIND] BTCUSD + XAUTUSD (GOLD): ENABLED / UNCHANGED')
    print(' [CUSTOM STRATEGY ENGINE] PAUSED')
    print(' [PAPER/AUTO TRADE/LIVE EXECUTION] DISABLED')
    print('='*58+'\n')
    install_active_flow_indicator_overlay(delta_auto_engine)
    install_precision_overlay(delta_auto_engine)
    delta_auto_engine.set_alert_callback(telegram_bot.broadcast)
    delta_auto_engine.format_signal=lambda c: format_short_signal(delta_auto_engine,c)
    master_mind_scalp_engine.set_alert_callback(telegram_bot.broadcast)
    tasks=[
        asyncio.create_task(telegram_bot.poll(),name='telegram-poll'),
        asyncio.create_task(delta_market_service.websocket_loop(),name='delta-ws'),
        asyncio.create_task(delta_auto_engine.loop(),name='delta-auto-signal-engine'),
        asyncio.create_task(master_mind_scalp_engine.loop(),name='master-mind-btc-xaut-scalp'),
        asyncio.create_task(heartbeat_loop(),name='heartbeat'),
    ]
    logger.info('[APP] ALERTS ONLY started; V4.2 active-flow=%s indicators=%s premium_oi=%s master_mind_symbols=%s daily_caps=%s',
                getattr(delta_auto_engine,'active_flow_overlay_installed',False),
                getattr(delta_auto_engine,'requested_indicator_overlay_installed',False),
                getattr(delta_auto_engine,'premium_oi_overlay_installed',False),
                ['BTCUSD','XAUTUSD'],DAILY_SIGNAL_CAP)
    yield
    telegram_bot.running=False;delta_auto_engine.running=False;master_mind_scalp_engine.running=False;delta_market_service.running=False
    for t in tasks:t.cancel()
    await asyncio.gather(*tasks,return_exceptions=True)
    await telegram_bot.client.aclose();await delta_market_service.close();await delta_options_service.client.aclose();await option_premium_history_service.close()

app=FastAPI(title='Delta Crypto AI Bot V9',lifespan=lifespan)
@app.get('/')
def root():return {'service':'Delta Crypto AI Bot V9','status':'online','mode':'alerts-only-v42-premium-oi-plus-master-mind','provider':'Delta Exchange India public APIs','timestamp':time.time()}
@app.head('/')
def head():return None
@app.get('/health')
def health():
    now=time.time()
    return {
        'status':'healthy',
        'mode':'alerts-only-v42-premium-oi-plus-master-mind',
        'delta_ws':delta_market_service.ws_connected,
        'delta_ws_age_seconds':round(now-delta_market_service.last_ws_message,1) if delta_market_service.last_ws_message else None,
        'delta_ws_reconnects':delta_market_service.reconnect_count,
        'active_flow_overlay':bool(getattr(delta_auto_engine,'active_flow_overlay_installed',False)),
        'requested_indicator_overlay':bool(getattr(delta_auto_engine,'requested_indicator_overlay_installed',False)),
        'premium_oi_overlay':bool(getattr(delta_auto_engine,'premium_oi_overlay_installed',False)),
        'option_premium_ema5_gate':True,
        'option_oi_history_confirmation':True,
        'nearby_strike_oi_confirmation':True,
        'active_flow_target_rr':getattr(delta_auto_engine,'active_flow_target_rr',None),
        'robo_staff_v42_enabled':True,
        'robo_staff_daily_signal_cap':dict(DAILY_SIGNAL_CAP),
        'master_mind_enabled':True,
        'master_mind_status':master_mind_scalp_engine.last_status,
        'master_mind_status_by_symbol':master_mind_scalp_engine.last_status_by_symbol,
        'master_mind_symbols':['BTCUSD','XAUTUSD'],
        'master_mind_last_scan_age_seconds':round(now-master_mind_scalp_engine.last_scan_at,1) if master_mind_scalp_engine.last_scan_at else None,
        'custom_strategy_engine_running':False,
        'paper_trading':False,
        'auto_trade_prep':False,
        'live_execution':False,
        'symbols':settings.delta_symbols(),
        'auto_trading':False
    }
