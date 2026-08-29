import logging, os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'), format='%(asctime)s [%(levelname)s] %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger('delta_bot')

@dataclass
class Settings:
    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    ALLOWED_TELEGRAM_USER_ID: str = os.getenv('ALLOWED_TELEGRAM_USER_ID','').strip()
    GEMINI_API_KEY: str = os.getenv('GEMINI_API_KEY','').strip()
    GEMINI_MODEL: str = os.getenv('GEMINI_MODEL','gemini-3.5-flash-lite').strip()
    GROQ_API_KEY: str = os.getenv('GROQ_API_KEY','').strip()
    GROQ_MODEL: str = os.getenv('GROQ_MODEL','llama-3.3-70b-versatile').strip()
    DELTA_REST_BASE: str = os.getenv('DELTA_REST_BASE','https://api.india.delta.exchange').rstrip('/')
    DELTA_PUBLIC_WS_URL: str = os.getenv('DELTA_PUBLIC_WS_URL','wss://public-socket.india.delta.exchange').strip()
    DELTA_SYMBOLS: str = os.getenv('DELTA_SYMBOLS','BTCUSD,ETHUSD').strip()
    DATABASE_URL: str = os.getenv('DATABASE_URL','').strip()
    SQLITE_PATH: str = os.getenv('SQLITE_PATH','data/strategies.db').strip()
    SCAN_INTERVAL_SECONDS: int = int(os.getenv('SCAN_INTERVAL_SECONDS','30'))
    ALERT_COOLDOWN_MINUTES: int = int(os.getenv('ALERT_COOLDOWN_MINUTES','15'))
    MAX_SAVED_STRATEGIES: int = int(os.getenv('MAX_SAVED_STRATEGIES','100'))
    MAX_ACTIVE_STRATEGIES: int = int(os.getenv('MAX_ACTIVE_STRATEGIES','10'))
    MIN_RR: float = float(os.getenv('MIN_RR','1.85'))
    HEARTBEAT_SECONDS: int = int(os.getenv('HEARTBEAT_SECONDS','60'))

    def allowed_user_ids(self):
        out=[]
        for x in self.ALLOWED_TELEGRAM_USER_ID.replace(';',',').split(','):
            x=x.strip()
            if x.isdigit(): out.append(int(x))
        return out

    def delta_symbols(self):
        return [x.strip().upper() for x in self.DELTA_SYMBOLS.split(',') if x.strip()]

settings=Settings()
