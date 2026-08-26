import time
import datetime
import pandas as pd
from config import settings, logger
from models import StockQuote, MarketStatusOverview
from symbol_universe import SymbolUniverse
from mock_market import MockMarketService
from errors import MarketDataUnavailable


class FyersService:
    """Read-only FYERS market-data service. No trading/order methods are implemented."""

    def __init__(self):
        self.client_id = settings.FYERS_CLIENT_ID
        self.access_token = settings.FYERS_ACCESS_TOKEN
        self._fyers_model = None
        self._is_token_valid = False
        self._init_client()

    def _init_client(self):
        if settings.MOCK_MARKET_DATA:
            logger.info("[FYERS] Running in explicit MOCK mode (MOCK_MARKET_DATA=true)")
            return

        if not self.client_id or not self.access_token:
            logger.warning("[FYERS] Live credentials not configured. Live market data is unavailable.")
            return

        try:
            from fyers_apiv3 import fyersModel
            self._fyers_model = fyersModel.FyersModel(
                client_id=self.client_id,
                is_async=False,
                token=self.access_token,
                log_path=""
            )
            profile = self._fyers_model.get_profile()
            if profile and profile.get("s") == "ok":
                self._is_token_valid = True
                logger.info("[FYERS] Token valid. Connected successfully.")
            else:
                self._is_token_valid = False
                logger.warning("[FYERS] Token validation failed; live data disabled until credentials are refreshed.")
        except Exception as e:
            self._is_token_valid = False
            logger.warning(f"[FYERS] Failed to initialize official SDK: {e}")

    def is_healthy(self) -> bool:
        if settings.MOCK_MARKET_DATA:
            return True
        return self._is_token_valid and (self._fyers_model is not None)

    def _require_live(self):
        if settings.MOCK_MARKET_DATA:
            return
        if not self._is_token_valid or not self._fyers_model:
            raise MarketDataUnavailable(
                "FYERS live market data is unavailable or the access token has expired. Refresh FYERS_ACCESS_TOKEN and restart the service."
            )

    def get_quote(self, symbol: str) -> StockQuote:
        formatted_sym = SymbolUniverse.format_symbol(symbol)
        if settings.MOCK_MARKET_DATA:
            return MockMarketService.get_quote(formatted_sym)

        self._require_live()
        try:
            response = self._fyers_model.quotes(data={"symbols": formatted_sym})
            if response and response.get("s") == "ok" and response.get("d"):
                q_data = response["d"][0].get("v", {})
                return StockQuote(
                    symbol=formatted_sym,
                    ltp=float(q_data.get("lp", 0.0)),
                    open=float(q_data.get("open_price", 0.0)),
                    high=float(q_data.get("high_price", 0.0)),
                    low=float(q_data.get("low_price", 0.0)),
                    prev_close=float(q_data.get("prev_close_price", 0.0)),
                    volume=int(q_data.get("volume", 0)),
                    change=float(q_data.get("ch", 0.0)),
                    change_pct=float(q_data.get("chp", 0.0)),
                    timestamp=time.time()
                )
            raise MarketDataUnavailable(f"FYERS returned no valid quote for {formatted_sym}.")
        except MarketDataUnavailable:
            raise
        except Exception as e:
            logger.warning(f"[FYERS] Quote fetch error for {formatted_sym}: {e}")
            raise MarketDataUnavailable(f"FYERS quote fetch failed for {formatted_sym}.") from e

    def get_history(self, symbol: str, timeframe: str = "5", days_back: int = 5) -> pd.DataFrame:
        formatted_sym = SymbolUniverse.format_symbol(symbol)
        if settings.MOCK_MARKET_DATA:
            return MockMarketService.generate_candles(formatted_sym, timeframe=timeframe, count=100)

        self._require_live()
        try:
            tf_param = timeframe.upper() if timeframe.upper() in ("D", "1D") else timeframe
            today = datetime.date.today()
            data = {
                "symbol": formatted_sym,
                "resolution": tf_param,
                "date_format": "1",
                "range_from": (today - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d"),
                "range_to": today.strftime("%Y-%m-%d"),
                "cont_flag": "1"
            }
            response = self._fyers_model.history(data=data)
            if response and response.get("s") == "ok" and response.get("candles"):
                return pd.DataFrame(response["candles"], columns=["timestamp", "open", "high", "low", "close", "volume"])
            raise MarketDataUnavailable(f"FYERS returned no candle history for {formatted_sym}.")
        except MarketDataUnavailable:
            raise
        except Exception as e:
            logger.warning(f"[FYERS] History fetch error for {formatted_sym}: {e}")
            raise MarketDataUnavailable(f"FYERS history fetch failed for {formatted_sym}.") from e

    def get_market_overview(self) -> MarketStatusOverview:
        if settings.MOCK_MARKET_DATA:
            return MockMarketService.get_market_overview()

        self._require_live()
        nifty_quote = self.get_quote("NSE:NIFTY50-INDEX")
        bn_quote = self.get_quote("NSE:NIFTYBANK-INDEX")
        sample_stocks = ["NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:HDFCBANK-EQ", "NSE:INFY-EQ", "NSE:SBIN-EQ"]
        quotes = [self.get_quote(s) for s in sample_stocks]
        advances = sum(1 for q in quotes if q.change >= 0)
        declines = sum(1 for q in quotes if q.change < 0)
        sorted_gainers = sorted(quotes, key=lambda q: q.change_pct, reverse=True)
        return MarketStatusOverview(
            market_status="LIVE (FYERS API)",
            nifty_spot=nifty_quote.ltp,
            nifty_change_pct=nifty_quote.change_pct,
            banknifty_spot=bn_quote.ltp,
            banknifty_change_pct=bn_quote.change_pct,
            advances=advances,
            declines=declines,
            top_gainers=[{"symbol": SymbolUniverse.clean_symbol_name(q.symbol), "price": q.ltp, "change_pct": q.change_pct} for q in sorted_gainers[:3]],
            top_losers=[{"symbol": SymbolUniverse.clean_symbol_name(q.symbol), "price": q.ltp, "change_pct": q.change_pct} for q in sorted_gainers[-3:]],
            is_mock=False
        )


fyers_service = FyersService()
