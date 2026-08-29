import asyncio,time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from config import settings,logger
from mudrex_service import mudrex_service
from signal_engine import engine
from bot import telegram_bot

@asynccontextmanager
async def lifespan(app:FastAPI):
    print('\n'+'='*52)
    print(' MUDREX CRYPTO AI BOT - TELEGRAM ONLY')
    print('='*52)
    print(' [MUDREX] Public market data: NO API KEY REQUIRED')
    print(f" [SYMBOLS] {settings.symbols()}")
    print(f" [TELEGRAM] {'configured' if settings.TELEGRAM_BOT_TOKEN else 'NOT SET'}")
    print(f" [GEMINI] {'configured' if settings.GEMINI_API_KEY else 'NOT SET'}")
    print(' [SAFETY] Auto-trading: DISABLED')
    print('='*52+'\n')
    engine.set_alert_callback(telegram_bot.alert)
    tasks=[asyncio.create_task(telegram_bot.poll()),asyncio.create_task(mudrex_service.websocket_loop()),asyncio.create_task(engine.loop())]
    logger.info('[APP] Mudrex crypto signal bot started')
    yield
    telegram_bot.running=False
    for t in tasks:t.cancel()
    await telegram_bot.client.aclose(); await mudrex_service.client.aclose()

app=FastAPI(title='Mudrex Crypto AI Bot',lifespan=lifespan)
@app.get('/')
def root(): return {'service':'Mudrex Crypto AI Bot','status':'online','mode':'signal-only','timestamp':time.time()}
@app.head('/')
def head(): return None
@app.get('/health')
def health(): return {'status':'healthy','scanner':engine.running,'ws':mudrex_service.ws_connected,'symbols':settings.symbols(),'auto_trading':False}
