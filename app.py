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
from scalp_opportunity_overlay import install_scalp_opportunity_overlay
from performance_display_overlay import install_performance_display_overlay
from polish_policy import DAILY_SIGNAL_CAP

# Signal-only mode. Master Mind remains independent and unchanged.
DAILY_SIGNAL_CAP.update({'BTC':60,'ETH':60,'GOLD':40})

async def heartbeat_loop():
    while True:
        try:
            ws_age=(time.time()-delta_market_service.last_ws_message) if delta_market_service.last_ws_message else None
            logger.info('[HEARTBEAT] app=alive delta_ws=%s ws_age=%s reconnects=%s',
                        'connected' if delta_market_service.ws_connected else 'reconnecting/rest',
                        f'{ws_age:.0f}s' if ws_age is not None else 'n/a', delta_market_service.reconnect_count)
        except asyncio.CancelledError:raise
        except Exception as exc:logger.warning('[HEARTBEAT] health check failed safely: %s',exc)
        await asyncio.sleep(max(30,settings.HEARTBEAT_SECONDS))

@asynccontextmanager
async def lifespan(app:FastAPI):
    strategy_store.init()
    print('\n'+'='*62)
    print(' DELTA CRYPTO AI BOT V9 - ALERTS ONLY')
    print('='*62)
    print(' [DELTA] Public market data + options: NO API KEY REQUIRED')
    print(f' [SYMBOLS] {settings.delta_symbols()}')
    print(f" [TELEGRAM] {'configured' if settings.TELEGRAM_BOT_TOKEN else 'NOT SET'}")
    print(f" [GEMINI] {'configured' if settings.GEMINI_API_KEY else 'NOT SET'}")
    print(' [RECOVERY] Delta WS auto-reconnect + heartbeat: ENABLED')
    print(' [ROBO STAFF] V4.3 PROFESSIONAL SCALP: ENABLED')
    print(' [V4.3] Underlying 5M EMA5 + EMA9/18 + RSI/W%R + Fib: ENABLED')
    print(' [V4.3] Option premium 5M + option OI/liquidity: ENABLED')
    print(' [V4.3] 1M retest/resume timing + 3-minute opportunity expiry: ENABLED')
    print(' [V4.3] Futures OI + funding context: ENABLED')
    print(' [V4.3] Brokerage/spread/slippage break-even + 3x gross/cost gate: ENABLED')
    print(' [V4.3] OPTION BUY / OPTION SELL / FUTURE opportunity matrix: ENABLED')
    print(' [V4.3] Daily Fib P/R1/S1: CONTEXT ONLY | T1: 1.85R')
    print(f' [ROBO STAFF] Daily caps: BTC {DAILY_SIGNAL_CAP["BTC"]} | ETH {DAILY_SIGNAL_CAP["ETH"]} | GOLD {DAILY_SIGNAL_CAP["GOLD"]}')
    print(' [MASTER MIND] BTCUSD + XAUTUSD (GOLD): ENABLED / UNCHANGED')
    print(' [PAPER/AUTO TRADE/LIVE EXECUTION] DISABLED')
    print('='*62+'\n')
    install_active_flow_indicator_overlay(delta_auto_engine)
    install_precision_overlay(delta_auto_engine)
    install_scalp_opportunity_overlay(delta_auto_engine)
    install_performance_display_overlay(type(telegram_bot))
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
    logger.info('[APP] V4.3 alerts-only active_flow=%s premium_oi=%s professional_scalp=%s cost_gate=%s timing_gate=%s',
                getattr(delta_auto_engine,'active_flow_overlay_installed',False),
                getattr(delta_auto_engine,'premium_oi_overlay_installed',False),
                getattr(delta_auto_engine,'professional_scalp_overlay_installed',False),
                getattr(delta_auto_engine,'cost_gate_installed',False),
                getattr(delta_auto_engine,'one_minute_timing_gate_installed',False))
    yield
    telegram_bot.running=False;delta_auto_engine.running=False;master_mind_scalp_engine.running=False;delta_market_service.running=False
    for t in tasks:t.cancel()
    await asyncio.gather(*tasks,return_exceptions=True)
    await telegram_bot.client.aclose();await delta_market_service.close();await delta_options_service.client.aclose();await option_premium_history_service.close()

app=FastAPI(title='Delta Crypto AI Bot V9',lifespan=lifespan)
@app.get('/')
def root():return {'service':'Delta Crypto AI Bot V9','status':'online','mode':'alerts-only-v43-professional-scalp-plus-master-mind','provider':'Delta Exchange India public APIs','timestamp':time.time()}
@app.head('/')
def head():return None
@app.get('/health')
def health():
    now=time.time()
    return {
        'status':'healthy','mode':'alerts-only-v43-professional-scalp-plus-master-mind',
        'delta_ws':delta_market_service.ws_connected,
        'delta_ws_age_seconds':round(now-delta_market_service.last_ws_message,1) if delta_market_service.last_ws_message else None,
        'delta_ws_reconnects':delta_market_service.reconnect_count,
        'active_flow_overlay':bool(getattr(delta_auto_engine,'active_flow_overlay_installed',False)),
        'requested_indicator_overlay':bool(getattr(delta_auto_engine,'requested_indicator_overlay_installed',False)),
        'premium_oi_overlay':bool(getattr(delta_auto_engine,'premium_oi_overlay_installed',False)),
        'professional_scalp_overlay':bool(getattr(delta_auto_engine,'professional_scalp_overlay_installed',False)),
        'one_minute_timing_gate':bool(getattr(delta_auto_engine,'one_minute_timing_gate_installed',False)),
        'transaction_cost_gate':bool(getattr(delta_auto_engine,'cost_gate_installed',False)),
        'instrument_selector':['OPTION BUY','OPTION SELL','FUTURE LONG','FUTURE SHORT'],
        'active_flow_target_rr':getattr(delta_auto_engine,'active_flow_target_rr',None),
        'robo_staff_v43_enabled':True,'robo_staff_daily_signal_cap':dict(DAILY_SIGNAL_CAP),
        'master_mind_enabled':True,'master_mind_status':master_mind_scalp_engine.last_status,
        'master_mind_status_by_symbol':master_mind_scalp_engine.last_status_by_symbol,
        'master_mind_symbols':['BTCUSD','XAUTUSD'],
        'master_mind_last_scan_age_seconds':round(now-master_mind_scalp_engine.last_scan_at,1) if master_mind_scalp_engine.last_scan_at else None,
        'custom_strategy_engine_running':False,'paper_trading':False,'auto_trade_prep':False,'live_execution':False,
        'symbols':settings.delta_symbols(),'auto_trading':False
    }
