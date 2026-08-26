import time
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI

from config import settings, logger
from storage import storage
from fyers_service import fyers_service
from scanner import scanner
from bot import telegram_bot


def run_startup_self_check():
    print("\n" + "=" * 52)
    print(" FYERS AI MARKET BOT - TELEGRAM ONLY")
    print("=" * 52)
    print(f" [TELEGRAM] Token: {'configured' if settings.TELEGRAM_BOT_TOKEN else 'NOT SET'}")
    print(f" [TELEGRAM] Allowed users: {settings.allowed_user_ids() or 'NOT SET'}")
    print(f" [AI] Gemini: {'configured' if settings.GEMINI_API_KEY else 'NOT SET'}")
    print(f" [AI] Groq fallback: {'configured' if settings.GROQ_API_KEY else 'NOT SET'}")
    if settings.MOCK_MARKET_DATA:
        print(" [FYERS] EXPLICIT MOCK MODE")
    else:
        print(f" [FYERS] Live data: {'connected' if fyers_service.is_healthy() else 'OFFLINE / TOKEN REQUIRED'}")
    print(" [SAFETY] Auto-trading: DISABLED")
    print(f" [SESSION] Scanner auto-stop: {settings.MAX_SCANNER_SESSION_HOURS} hours")
    print("=" * 52 + "\n")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_startup_self_check()
    scanner.set_alert_callback(telegram_bot.broadcast_alert)
    scanner_task = asyncio.create_task(scanner.run_loop())
    telegram_task = asyncio.create_task(telegram_bot.start_polling())
    logger.info("[APP] Telegram-only FYERS AI Market Bot started")
    yield
    logger.info("[APP] Shutting down services...")
    scanner._is_running = False
    telegram_bot._is_running = False
    scanner_task.cancel()
    telegram_task.cancel()
    await telegram_bot.client.aclose()


app = FastAPI(
    title="FYERS AI Market Bot",
    description="Telegram-only personal market scanner. HTTP is used only for cloud health checks.",
    lifespan=lifespan,
)


@app.get("/")
def root_endpoint():
    return {"service": "FYERS AI Market Bot", "status": "online", "ui": "telegram", "timestamp": time.time()}


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "telegram_configured": bool(settings.TELEGRAM_BOT_TOKEN),
        "scanner_loop": "running" if scanner._is_running else "idle",
        "active_scanners": len(scanner.get_active_scanners()),
        "mock_mode": settings.MOCK_MARKET_DATA,
        "fyers_healthy": fyers_service.is_healthy(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=settings.HOST, port=settings.PORT, reload=False)
