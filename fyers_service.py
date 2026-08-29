import time
import datetime
import pandas as pd
import requests
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


    def get_history_range(self, symbol: str, timeframe: str, range_from: str, range_to: str) -> pd.DataFrame:
        formatted_sym = SymbolUniverse.format_symbol(symbol)
        self._require_live()
        data = {
            "symbol": formatted_sym, "resolution": timeframe, "date_format": "1",
            "range_from": range_from, "range_to": range_to, "cont_flag": "1"
        }
        response = self._fyers_model.history(data=data)
        if response and response.get("s") == "ok" and response.get("candles"):
            return pd.DataFrame(response["candles"], columns=["timestamp","open","high","low","close","volume"])
        return pd.DataFrame(columns=["timestamp","open","high","low","close","volume"])

    def get_historical_daily_price(self, symbol: str, date_str: str, nearest_previous: bool = True) -> dict:
        target = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        start = target - datetime.timedelta(days=7 if nearest_previous else 0)
        df = self.get_history_range(symbol, "D", start.strftime("%Y-%m-%d"), target.strftime("%Y-%m-%d"))
        if df.empty:
            raise MarketDataUnavailable(f"No FYERS daily candle found for {symbol} on or before {date_str}.")
        row = df.iloc[-1]
        candle_date = datetime.datetime.fromtimestamp(float(row.timestamp)).date().isoformat()
        return {
            "requested_date": date_str, "trading_date": candle_date, "symbol": SymbolUniverse.format_symbol(symbol),
            "open": float(row.open), "high": float(row.high), "low": float(row.low), "close": float(row.close), "volume": int(row.volume),
            "used_previous_trading_day": candle_date != date_str,
        }

    def get_option_chain(self, symbol: str = "NSE:NIFTY50-INDEX", strikecount: int = 8, timestamp: str = "", greeks: bool = True) -> dict:
        self._require_live()
        url = "https://api-t1.fyers.in/data/options-chain-v3"
        headers = {"Authorization": f"{self.client_id}:{self.access_token}", "Content-Type": "application/json"}
        params = {"symbol": SymbolUniverse.format_symbol(symbol), "strikecount": min(max(int(strikecount),1),50)}
        if timestamp:
            params["timestamp"] = str(timestamp)
        if greeks:
            params["greeks"] = "1"
        r = requests.get(url, headers=headers, params=params, timeout=12)
        if r.status_code != 200:
            raise MarketDataUnavailable(f"FYERS option-chain request failed ({r.status_code}).")
        payload = r.json()
        if payload.get("s") == "error" or not payload.get("data"):
            raise MarketDataUnavailable(f"FYERS option-chain returned no valid data: {payload.get('message','unknown error')}")
        return payload

    @staticmethod
    def summarize_nifty_oi(payload: dict) -> dict:
        data = payload.get("data") or {}
        chain = data.get("optionsChain") or []
        spot_row = next((x for x in chain if str(x.get("option_type", "")) == ""), {})
        spot = float(spot_row.get("ltp") or 0)
        strikes = sorted({float(x.get("strike_price")) for x in chain if x.get("option_type") in ("CE","PE") and x.get("strike_price") is not None})
        atm = min(strikes, key=lambda x: abs(x-spot)) if strikes and spot else (strikes[len(strikes)//2] if strikes else 0)
        nearby = [x for x in chain if x.get("option_type") in ("CE","PE") and abs(float(x.get("strike_price",0))-atm) <= 200]
        call_write = sum(max(float(x.get("oich") or 0),0) for x in nearby if x.get("option_type")=="CE" and float(x.get("ltpch") or 0) <= 0)
        put_write = sum(max(float(x.get("oich") or 0),0) for x in nearby if x.get("option_type")=="PE" and float(x.get("ltpch") or 0) <= 0)
        if put_write > call_write * 1.10:
            bias = "BULLISH"
        elif call_write > put_write * 1.10:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"
        call_oi = float(data.get("callOi") or 0)
        put_oi = float(data.get("putOi") or 0)
        pcr = round(put_oi/call_oi, 3) if call_oi else None
        atm_ce = next((x for x in chain if x.get("option_type")=="CE" and float(x.get("strike_price",0))==atm), None)
        atm_pe = next((x for x in chain if x.get("option_type")=="PE" and float(x.get("strike_price",0))==atm), None)
        return {"spot":spot,"atm_strike":atm,"pcr":pcr,"bias":bias,"call_write_oi":call_write,"put_write_oi":put_write,"atm_ce":atm_ce,"atm_pe":atm_pe}

    @staticmethod
    def _expiry_label(item: dict) -> str:
        for key in ("date", "expiry", "expiryDate", "expiry_date"):
            if item.get(key):
                return str(item.get(key))
        return ""

    def get_option_contract_snapshot(self, underlying: str, strike: int, option_type: str, expiry_hint: str = ""):
        """Resolve a requested CE/PE from FYERS option-chain, optionally selecting an expiry month.

        expiry_hint format: YYYY-MM. If FYERS exposes expiryData, the closest matching expiry is selected
        and the chain is re-fetched with its timestamp. Otherwise the nearest/current chain is used.
        """
        underlying = SymbolUniverse.format_symbol(underlying)
        payload = self.get_option_chain(underlying, strikecount=50, timestamp="", greeks=True)
        data = payload.get("data") or {}
        resolved_expiry = None

        expiry_data = data.get("expiryData") or data.get("expiry_data") or []
        if expiry_hint and expiry_data:
            candidates = []
            for item in expiry_data:
                label = self._expiry_label(item)
                if expiry_hint in label:
                    candidates.append(item)
            if candidates:
                chosen = candidates[0]
                ts = chosen.get("expiry") or chosen.get("timestamp") or chosen.get("expiryTimestamp") or chosen.get("expiry_ts")
                resolved_expiry = self._expiry_label(chosen) or str(ts or "")
                if ts:
                    payload = self.get_option_chain(underlying, strikecount=50, timestamp=str(ts), greeks=True)
                    data = payload.get("data") or {}
        elif expiry_data:
            resolved_expiry = self._expiry_label(expiry_data[0])

        chain = data.get("optionsChain") or []
        side = option_type.upper()
        matches = [x for x in chain if str(x.get("option_type", "")).upper() == side and int(float(x.get("strike_price") or 0)) == int(strike)]
        if not matches:
            raise MarketDataUnavailable(
                f"FYERS option chain did not return {underlying} {int(strike)} {side} for the requested/current expiry."
            )
        row = matches[0]
        if not resolved_expiry:
            resolved_expiry = str(row.get("expiry") or row.get("expiryDate") or "current/nearest chain")
        return row, {"resolved_expiry": resolved_expiry, "underlying": underlying}

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
