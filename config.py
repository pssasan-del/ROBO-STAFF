import os
import logging
from typing import Optional, List
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

# Logging Configuration
LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("fyers_bot")
# Prevent httpx/httpcore from logging full Telegram URLs (which contain the bot token).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

class Settings:
    # Telegram Security
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    ALLOWED_TELEGRAM_USER_ID: str = os.getenv("ALLOWED_TELEGRAM_USER_ID", "").strip()

    # FYERS API Configuration
    FYERS_CLIENT_ID: str = os.getenv("FYERS_CLIENT_ID", "").strip()
    FYERS_SECRET_KEY: str = os.getenv("FYERS_SECRET_KEY", "").strip()
    FYERS_REDIRECT_URI: str = os.getenv("FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html").strip()
    FYERS_ACCESS_TOKEN: str = os.getenv("FYERS_ACCESS_TOKEN", "").strip()

    # AI Configuration (Primary: Gemini, Fallback: Groq)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()

    # Scanner Session & Alerts
    MAX_SCANNER_SESSION_HOURS: int = int(os.getenv("MAX_SCANNER_SESSION_HOURS", "6"))
    ALERT_COOLDOWN_MINUTES: int = int(os.getenv("ALERT_COOLDOWN_MINUTES", "15"))
    SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))

    # Mock Data Toggle
    MOCK_MARKET_DATA: bool = os.getenv("MOCK_MARKET_DATA", "false").lower() in ("true", "1", "t", "yes")

    # Render / Server Hosting
    PORT: int = int(os.getenv("PORT", "3000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "fyers_bot.db")

    @classmethod
    def allowed_user_ids(cls) -> List[int]:
        if not cls.ALLOWED_TELEGRAM_USER_ID:
            return []
        ids = []
        for part in cls.ALLOWED_TELEGRAM_USER_ID.split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        return ids

    @classmethod
    def is_user_authorized(cls, user_id: Optional[int]) -> bool:
        allowed = cls.allowed_user_ids()
        if not allowed:
            # If no ID configured yet, warning will be logged in startup check
            return False
        return user_id in allowed

settings = Settings()
