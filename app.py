import asyncio,time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from config import settings,logger
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from delta_account_read import delta_account_read_service
from strategy_store import strategy_store
from strategy_engine import engine
from bot import telegram_bot
from market_agent import market_agent
from delta_signal_engine import delta_auto_engine
from master_mind_scalp import master_mind_scalp_engine
from short_signal_formatter import format_short_signal
from precision_overlay import install_precision_overlay
from quick_option_shortcuts import install_quick_option_shortcuts
from balance_shortcut import install_balance_shortcut
from futures_paper_robo import futures_paper_robo
from paper_robo_controls import install_paper_robo_controls
from paper_robo_hook import install_paper_robo_hook
from fo_asthra_live import fo_asthra_live
from fo_asthra_controls import install_fo_asthra_controls
from fo_asthra_hook import install_fo_asthra_hook
from live_review_gate import live_review_gate
from live_review_controls import install_live_review_controls
from live_review_hook import install_live_review_hook

async def heartbeat_loop():
    """Lightweight internal health heartbeat. It does not bypass Render sleep; it confirms recovery once the service is awake."""
    while True:
        try:
            active=len(strategy_store.list_active()) if strategy_store.conn else 0
            ws_age=(time.time()-delta_market_service.last_ws_message) if delta_market_service.last_ws_message else None
            logger.info('[HEARTBEAT] app=alive delta_ws=%s ws_age=%s active_scanners=%s reconnects=%s paper_robo=%s paper_positions=%s asthra=%s asthra_positions=%s auto_trade_prep=%s ready_tickets=%s confirmed_tickets=%s',
                        'connected' if delta_market_service.ws_connected else 'reconnecting/rest',
                        f'{ws_age:.0f}s' if ws_age is not None else 'n/a', active, delta_market_service.reconnect_count,
                        'on' if futures_paper_robo.armed else 'off', len(futures_paper_robo.positions),
                        'on' if fo_asthra_live.armed else 'off', len(fo_asthra_live.positions),
                        'on' if live_review_gate.armed else 'off', len(live_review_gate.latest), len(live_review_gate.confirmed))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('[HEARTBEAT] health check failed safely: %s',exc)
        await asyncio.sleep(max(30,settings.HEARTBEAT_SECONDS))

@asynccontextmanager
async def lifespan(app:FastAPI):
    strategy_store.init()
    restored=len(strategy_store.list_active())
    print('\n'+'='*58)
    print(' DELTA CRYPTO AI BOT V9 - ADVANCED INDICATORS')
    print('='*58)
    print(' [DELTA] Public market data + options: NO API KEY REQUIRED')
    print(f' [SYMBOLS] {settings.delta_symbols()}')
    print(f" [TELEGRAM] {'configured' if settings.TELEGRAM_BOT_TOKEN else 'NOT SET'}")
    print(f" [GEMINI] {'configured' if settings.GEMINI_API_KEY else 'NOT SET'}")
    print(f' [STRATEGIES] saved max={settings.MAX_SAVED_STRATEGIES} active max={settings.MAX_ACTIVE_STRATEGIES}')
    print(f" [DATABASE] {'PostgreSQL persistent' if settings.DATABASE_URL else 'SQLite fallback (ephemeral on free Render)'}")
    print(f' [RESTORE] {restored} previously-active scanner(s) will resume automatically')
    print(' [UPLOAD] Telegram text/photo/PDF/TXT/MD/JSON strategy input: ENABLED')
    print(' [RECOVERY] Delta WS auto-reconnect + heartbeat: ENABLED')
    print(' [ROBO STAFF] V4.1 active local-flow scalp: ENABLED')
    print(' [MASTER MIND] BTCUSD + XAUTUSD (GOLD) isolated scalp alerts: ENABLED')
    print(' [QUICK CHAIN] B=BTC | E=ETH | X=GOLD: ENABLED')
    print(f" [BALANCE] Read-only private wallet fetch: {'ENABLED' if delta_account_read_service.configured else 'WAITING FOR API KEY'}")
    print(' [FUTURES ROBO] PAPER ONLY: 84x sizing model | 10% available capital | restart default OFF')
    print(' [F&O ASTHRA] OPTION BUY LIVE: 84x sizing model | 10% available capital | T1 trailing | restart default OFF')
    print(' [AUTO TRADE PREP] READY manual order tickets only while ON | explicit CONFIRM required | restart default OFF')
    print(' [SAFETY] Exchange order submission: ENABLED when ASTHRA LIVE armed + LIVE_TRADING_ENABLED')
    print('='*58+'\n')
    engine.set_alert_callback(telegram_bot.alert)
    install_precision_overlay(delta_auto_engine)
    install_quick_option_shortcuts(market_agent)
    install_balance_shortcut(telegram_bot)
    install_paper_robo_controls(telegram_bot)
    install_fo_asthra_controls(telegram_bot)
    install_live_review_controls(telegram_bot)
    delta_auto_engine.set_alert_callback(telegram_bot.broadcast)
    delta_auto_engine.format_signal=lambda c: format_short_signal(delta_auto_engine,c)
    futures_paper_robo.set_alert_callback(telegram_bot.broadcast)
    fo_asthra_live.set_alert_callback(telegram_bot.broadcast)
    live_review_gate.set_alert_callback(telegram_bot.broadcast)
    install_paper_robo_hook(delta_auto_engine,futures_paper_robo)
    install_fo_asthra_hook(delta_auto_engine,fo_asthra_live)
    install_live_review_hook(delta_auto_engine,live_review_gate)
    master_mind_scalp_engine.set_alert_callback(telegram_bot.broadcast)
    tasks=[
        asyncio.create_task(telegram_bot.poll(),name='telegram-poll'),
        asyncio.create_task(delta_market_service.websocket_loop(),name='delta-ws'),
        asyncio.create_task(engine.loop(),name='strategy-engine'),
        asyncio.create_task(delta_auto_engine.loop(),name='delta-auto-signal-engine'),
        asyncio.create_task(master_mind_scalp_engine.loop(),name='master-mind-btc-xaut-scalp'),
        asyncio.create_task(futures_paper_robo.monitor_loop(),name='futures-paper-robo-monitor'),
        asyncio.create_task(fo_asthra_live.monitor_loop(),name='fo-asthra-paper-monitor'),
        asyncio.create_task(heartbeat_loop(),name='heartbeat'),
    ]
    logger.info('[APP] Delta crypto bot started; active_flow=%s quick_chain=%s balance=%s futures_paper=%s asthra=%s auto_trade_prep=%s restored=%s',
                getattr(delta_auto_engine,'active_flow_overlay_installed',False),
                getattr(market_agent,'quick_option_shortcuts_installed',False),
                getattr(telegram_bot,'balance_shortcut_installed',False),
                getattr(telegram_bot,'paper_robo_controls_installed',False),
                getattr(telegram_bot,'fo_asthra_controls_installed',False),
                getattr(telegram_bot,'live_review_controls_installed',False),restored)
    yield
    telegram_bot.running=False;engine.running=False;delta_auto_engine.running=False;master_mind_scalp_engine.running=False;delta_market_service.running=False;futures_paper_robo.running=False;fo_asthra_live.running=False
    for t in tasks:t.cancel()
    await asyncio.gather(*tasks,return_exceptions=True)
    await telegram_bot.client.aclose();await delta_market_service.close();await delta_options_service.client.aclose();await delta_account_read_service.client.aclose();await futures_paper_robo.client.aclose()

app=FastAPI(title='Delta Crypto AI Bot V9',lifespan=lifespan)
@app.get('/')
def root():return {'service':'Delta Crypto AI Bot V9','status':'online','mode':'signal-plus-paper-plus-manual-trade-prep','provider':'Delta Exchange India public/read-only APIs','timestamp':time.time()}
@app.head('/')
def head():return None
@app.get('/health')
def health():
    now=time.time()
    return {
        'status':'healthy',
        'delta_ws':delta_market_service.ws_connected,
        'delta_ws_age_seconds':round(now-delta_market_service.last_ws_message,1) if delta_market_service.last_ws_message else None,
        'delta_ws_reconnects':delta_market_service.reconnect_count,
        'engine_heartbeat_age_seconds':round(now-engine.last_loop_heartbeat,1) if engine.last_loop_heartbeat else None,
        'last_scan_age_seconds':round(now-engine.last_scan_at,1) if engine.last_scan_at else None,
        'active_flow_overlay':bool(getattr(delta_auto_engine,'active_flow_overlay_installed',False)),
        'quick_option_shortcuts':bool(getattr(market_agent,'quick_option_shortcuts_installed',False)),
        'quick_option_keys':['B','E','X'],
        'balance_button':bool(getattr(telegram_bot,'balance_shortcut_installed',False)),
        'delta_private_read_configured':delta_account_read_service.configured,
        'paper_robo_controls':bool(getattr(telegram_bot,'paper_robo_controls_installed',False)),
        'paper_robo_armed':futures_paper_robo.armed,
        'paper_robo_mode':'futures-only-paper',
        'paper_robo_leverage_model':84,
        'paper_robo_allocation_pct':10,
        'paper_robo_open_positions':len(futures_paper_robo.positions),
        'fo_asthra_controls':bool(getattr(telegram_bot,'fo_asthra_controls_installed',False)),
        'fo_asthra_armed':fo_asthra_live.armed,
        'fo_asthra_mode':'option-buy-LIVE',
        'fo_asthra_leverage_model':84,
        'fo_asthra_allocation_pct':10,
        'fo_asthra_t1_trailing':True,
        'fo_asthra_open_positions':len(fo_asthra_live.positions),
        'auto_trade_prep_controls':bool(getattr(telegram_bot,'live_review_controls_installed',False)),
        'auto_trade_prep_armed':live_review_gate.armed,
        'auto_trade_prep_restart_default':'OFF',
        'auto_trade_prep_tickets':len(live_review_gate.latest),
        'auto_trade_prep_confirmed_tickets':len(live_review_gate.confirmed),
        'auto_trade_prep_exchange_order_submission':False,
        'master_mind_status':master_mind_scalp_engine.last_status,
        'master_mind_status_by_symbol':master_mind_scalp_engine.last_status_by_symbol,
        'master_mind_symbols':['BTCUSD','XAUTUSD'],
        'master_mind_last_scan_age_seconds':round(now-master_mind_scalp_engine.last_scan_at,1) if master_mind_scalp_engine.last_scan_at else None,
        'active_strategies':len(strategy_store.list_active()) if strategy_store.conn else 0,
        'database':'postgresql' if strategy_store.pg else 'sqlite',
        'photo_strategy_upload':True,
        'symbols':settings.delta_symbols(),
        'exchange_order_submission': bool(__import__('config').settings.LIVE_TRADING_ENABLED)
    }
