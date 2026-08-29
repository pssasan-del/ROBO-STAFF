import logging, os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'), format='%(asctime)s [%(levelname)s] %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger('mudrex_bot')

@dataclass
class Settings:
    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    ALLOWED_TELEGRAM_USER_ID: str = os.getenv('ALLOWED_TELEGRAM_USER_ID','').strip()
    GEMINI_API_KEY: str = os.getenv('GEMINI_API_KEY','').strip()
    GEMINI_MODEL: str = os.getenv('GEMINI_MODEL','gemini-3.5-flash-lite').strip()
    GROQ_API_KEY: str = os.getenv('GROQ_API_KEY','').strip()
    GROQ_MODEL: str = os.getenv('GROQ_MODEL','llama-3.3-70b-versatile').strip()
    HOST: str = os.getenv('HOST','0.0.0.0')
    PORT: int = int(os.getenv('PORT','10000'))
    MUDREX_REST_BASE: str = os.getenv('MUDREX_REST_BASE','https://trade.mudrex.com/fapi/v1/price').rstrip('/')
    MUDREX_WS_URL: str = os.getenv('MUDREX_WS_URL','wss://trade.mudrex.com/fapi/v1/price/ws/linear')
    MUDREX_SYMBOLS: str = os.getenv('MUDREX_SYMBOLS','BTCUSDT,ETHUSDT')
    SCAN_INTERVAL_SECONDS: int = int(os.getenv('SCAN_INTERVAL_SECONDS','30'))
    ALERT_COOLDOWN_MINUTES: int = int(os.getenv('ALERT_COOLDOWN_MINUTES','15'))
    MIN_RR: float = float(os.getenv('MIN_RR','1.85'))

    def allowed_user_ids(self):
        out=[]
        for x in self.ALLOWED_TELEGRAM_USER_ID.replace(';',',').split(','):
            x=x.strip()
            if x.isdigit(): out.append(int(x))
        return out

    def symbols(self):
        return [x.strip().upper().replace('/','') for x in self.MUDREX_SYMBOLS.split(',') if x.strip()]

settings=Settings()
