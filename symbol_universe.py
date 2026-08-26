from typing import List, Dict, Optional
from errors import UnsupportedUniverseError

# Standard NSE:SYMBOL-EQ mappings for Indian Stock Market
NIFTY_50_SYMBOLS = [
    "NSE:RELIANCE-EQ",
    "NSE:TCS-EQ",
    "NSE:HDFCBANK-EQ",
    "NSE:ICICIBANK-EQ",
    "NSE:INFY-EQ",
    "NSE:BHARTIARTL-EQ",
    "NSE:SBIN-EQ",
    "NSE:ITC-EQ",
    "NSE:LT-EQ",
    "NSE:HINDUNILVR-EQ",
    "NSE:AXISBANK-EQ",
    "NSE:KOTAKBANK-EQ",
    "NSE:TATAMOTORS-EQ",
    "NSE:MARUTI-EQ",
    "NSE:SUNPHARMA-EQ",
    "NSE:TITAN-EQ",
    "NSE:BAJFINANCE-EQ",
    "NSE:NTPC-EQ",
    "NSE:ONGC-EQ",
    "NSE:POWERGRID-EQ",
    "NSE:M&M-EQ",
    "NSE:ADANIENT-EQ",
    "NSE:ADANIPORTS-EQ",
    "NSE:COALINDIA-EQ",
    "NSE:TATASTEEL-EQ",
    "NSE:ASIANPAINT-EQ",
    "NSE:BAJAJFINSV-EQ",
    "NSE:JSWSTEEL-EQ",
    "NSE:HCLTECH-EQ",
    "NSE:WIPRO-EQ",
    "NSE:GRASIM-EQ",
    "NSE:SBILIFE-EQ",
    "NSE:TECHM-EQ",
    "NSE:ULTRACEMCO-EQ",
    "NSE:NESTLEIND-EQ",
    "NSE:CIPLA-EQ",
    "NSE:APOLLOHOSP-EQ",
    "NSE:DRREDDY-EQ",
    "NSE:BPCL-EQ",
    "NSE:EICHERMOT-EQ",
    "NSE:BRITANNIA-EQ",
    "NSE:HINDALCO-EQ",
    "NSE:BAJAJ-AUTO-EQ",
    "NSE:TATACONSUM-EQ",
    "NSE:DIVISLAB-EQ",
    "NSE:INDUSINDBK-EQ",
    "NSE:HEROMOTOCO-EQ",
    "NSE:LTIM-EQ",
    "NSE:SHRIRAMFIN-EQ",
    "NSE:TRENT-EQ"
]

BANK_NIFTY_SYMBOLS = [
    "NSE:HDFCBANK-EQ",
    "NSE:ICICIBANK-EQ",
    "NSE:SBIN-EQ",
    "NSE:AXISBANK-EQ",
    "NSE:KOTAKBANK-EQ",
    "NSE:INDUSINDBK-EQ",
    "NSE:BANKBARODA-EQ",
    "NSE:PNB-EQ",
    "NSE:IDFCFIRSTB-EQ",
    "NSE:AUBANK-EQ",
    "NSE:FEDERALBNK-EQ",
    "NSE:BANDHANBNK-EQ"
]

NIFTY_100_EXTRA = [
    "NSE:HAL-EQ",
    "NSE:BEL-EQ",
    "NSE:VEDL-EQ",
    "NSE:ZOMATO-EQ",
    "NSE:JIOFIN-EQ",
    "NSE:CHOLAFIN-EQ",
    "NSE:DLF-EQ",
    "NSE:SIEMENS-EQ",
    "NSE:PIDILITIND-EQ",
    "NSE:HAVELLS-EQ",
    "NSE:VBL-EQ",
    "NSE:TORNTPHARM-EQ",
    "NSE:GODREJCP-EQ",
    "NSE:GAIL-EQ",
    "NSE:IOC-EQ",
    "NSE:ABB-EQ",
    "NSE:INDIGO-EQ",
    "NSE:AMBUJACEM-EQ",
    "NSE:CANBK-EQ",
    "NSE:TVSMOTOR-EQ",
    "NSE:POLYCAB-EQ",
    "NSE:DABUR-EQ",
    "NSE:MOTHERSON-EQ",
    "NSE:NAUKRI-EQ",
    "NSE:LODHA-EQ"
]

DEFAULT_WATCHLIST = [
    "NSE:RELIANCE-EQ",
    "NSE:TCS-EQ",
    "NSE:HDFCBANK-EQ",
    "NSE:INFY-EQ",
    "NSE:TATAMOTORS-EQ",
    "NSE:SBIN-EQ",
    "NSE:ICICIBANK-EQ",
    "NSE:BHARTIARTL-EQ",
    "NSE:TITAN-EQ",
    "NSE:ZOMATO-EQ"
]

INDEX_SYMBOLS = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "NIFTY50": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX"
}

class SymbolUniverse:
    @staticmethod
    def get_universe(name: str) -> List[str]:
        cleaned = name.strip().upper().replace(" ", "").replace("_", "").replace("-", "")
        if cleaned in ("NIFTY50", "N50", "NIFTY"):
            return list(NIFTY_50_SYMBOLS)
        elif cleaned in ("BANKNIFTY", "BANK", "BN"):
            return list(BANK_NIFTY_SYMBOLS)
        elif cleaned in ("NIFTY100", "N100"):
            return list(set(NIFTY_50_SYMBOLS + NIFTY_100_EXTRA))
        elif cleaned in ("WATCHLIST", "MYWATCHLIST"):
            return list(DEFAULT_WATCHLIST)
        elif cleaned in ("NIFTY200", "NIFTY500"):
            raise UnsupportedUniverseError(
                f"{name} is not enabled yet: this build does not ship an unverified partial constituent list. "
                "Use NIFTY50, NIFTY100, BANKNIFTY, WATCHLIST, or explicit symbols."
            )
        else:
            # Check if it is a single stock or comma-separated list
            symbols = [SymbolUniverse.format_symbol(s.strip()) for s in name.split(",") if s.strip()]
            return symbols if symbols else list(NIFTY_50_SYMBOLS)

    @staticmethod
    def format_symbol(raw_symbol: str) -> str:
        s = raw_symbol.strip().upper()
        if s in INDEX_SYMBOLS:
            return INDEX_SYMBOLS[s]
        if s.startswith("NSE:") or s.startswith("BSE:") or s.startswith("MCX:"):
            return s
        # Remove suffixes if any
        s = s.replace(".NS", "").replace(".BO", "")
        return f"NSE:{s}-EQ"

    @staticmethod
    def clean_symbol_name(fyers_symbol: str) -> str:
        s = fyers_symbol.replace("NSE:", "").replace("BSE:", "").replace("-EQ", "").replace("-INDEX", "")
        return s

    @staticmethod
    def is_index(symbol: str) -> bool:
        return "INDEX" in symbol.upper()
