import asyncio,time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from config import settings,logger
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from strategy_store import strategy_store
from strategy_engine import engine
from bot import telegram_bot

async def heartbeat_loop():
    """Lightweight internal health heartbeat. It does not bypass Render sleep; it confirms recovery once the service is awake."""
    while True:
        try:
            active=len(strategy_store.list_active()) if strategy_store.conn else 0
            ws_age=(time.time()-delta_market_service.last_ws_message) if delta_market_service.last_ws_message else None
            logger.info('[HEARTBEAT] app=alive delta_ws=%s ws_age=%s active_scanners=%s reconnects=%s',
                        'connected' if delta_market_service.ws_connected else 'reconnecting/rest',
                        f'{ws_age:.0f}s' if ws_age is not None else 'n/a', active, delta_market_service.reconnect_count)
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
    print(' DELTA CRYPTO AI BOT V8 - ADVANCED INDICATORS')
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
    print(' [SAFETY] Auto-trading: DISABLED')
    print('='*58+'\n')
    engine.set_alert_callback(telegram_bot.alert)
    tasks=[
        asyncio.create_task(telegram_bot.poll(),name='telegram-poll'),
        asyncio.create_task(delta_market_service.websocket_loop(),name='delta-ws'),
        asyncio.create_task(engine.loop(),name='strategy-engine'),
        asyncio.create_task(heartbeat_loop(),name='heartbeat'),
    ]
    logger.info('[APP] Delta-only crypto AI bot V8 started; restored_active=%s',restored)
    yield
    telegram_bot.running=False;engine.running=False;delta_market_service.running=False
    for t in tasks:t.cancel()
    await asyncio.gather(*tasks,return_exceptions=True)
    await telegram_bot.client.aclose();await delta_market_service.close();await delta_options_service.client.aclose()

app=FastAPI(title='Delta Crypto AI Bot V8',lifespan=lifespan)
@app.get('/')
def root():return {'service':'Delta Crypto AI Bot V8','status':'online','mode':'signal-only','provider':'Delta Exchange India public APIs','timestamp':time.time()}
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
        'active_strategies':len(strategy_store.list_active()) if strategy_store.conn else 0,
        'database':'postgresql' if strategy_store.pg else 'sqlite',
        'photo_strategy_upload':True,
        'auto_trading':False
    }
