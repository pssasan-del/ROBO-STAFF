import time
import math
import random
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from symbol_universe import SymbolUniverse
from models import StockQuote, MarketStatusOverview

# Base realistic price anchors for Indian market equities & indices
BASE_PRICES: Dict[str, float] = {
    "NSE:NIFTY50-INDEX": 24650.0,
    "NSE:NIFTYBANK-INDEX": 51200.0,
    "NSE:RELIANCE-EQ": 2980.50,
    "NSE:TCS-EQ": 3890.00,
    "NSE:HDFCBANK-EQ": 1645.20,
    "NSE:ICICIBANK-EQ": 1210.80,
    "NSE:INFY-EQ": 1820.40,
    "NSE:BHARTIARTL-EQ": 1560.00,
    "NSE:SBIN-EQ": 815.50,
    "NSE:TATAMOTORS-EQ": 975.30,
    "NSE:MARUTI-EQ": 12450.0,
    "NSE:TITAN-EQ": 3420.00,
    "NSE:BAJFINANCE-EQ": 6850.0,
    "NSE:LT-EQ": 3610.00,
    "NSE:SUNPHARMA-EQ": 1780.00,
    "NSE:ITC-EQ": 485.20,
    "NSE:AXISBANK-EQ": 1180.0,
    "NSE:KOTAKBANK-EQ": 1790.0,
    "NSE:ZOMATO-EQ": 245.0,
    "NSE:ADANIENT-EQ": 3020.0
}

class MockMarketService:
    """
    Deterministic Mock Market Engine for running the bot without live FYERS API
    or during market holidays / off-market testing hours.
    """

    @classmethod
    def get_base_price(cls, symbol: str) -> float:
        clean = SymbolUniverse.format_symbol(symbol)
        if clean in BASE_PRICES:
            return BASE_PRICES[clean]
        # Seed pseudo-random price from hash of symbol
        seed_val = abs(hash(clean)) % 3000 + 100.0
        return float(round(seed_val, 2))

    @classmethod
    def generate_candles(
        cls,
        symbol: str,
        timeframe: str = "5",
        count: int = 100,
        inject_pattern: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Generates realistic OHLCV dataframe.
        Optional pattern injections:
          - 'ema_breakout': EMA20 > EMA50, high RSI, volume breakout
          - 'open_high': Open == High on today's/latest candle
          - 'open_low': Open == Low on today's/latest candle
          - 'rsi_oversold': RSI < 30
          - 'rsi_overbought': RSI > 70
          - 'macd_crossover': Bullish MACD cross
        """
        base_price = cls.get_base_price(symbol)
        clean_sym = SymbolUniverse.clean_symbol_name(symbol)
        
        # Deterministic seed based on symbol string
        seed = abs(hash(symbol)) % 100000
        np.random.seed(seed)
        
        # Volatility percentage per candle
        tf_minutes = 5 if not timeframe.isdigit() else int(timeframe)
        volatility = (0.002 * math.sqrt(tf_minutes / 5.0))
        
        returns = np.random.normal(0.0002, volatility, count)
        
        # Special injection adjustments
        if inject_pattern == "ema_breakout" or clean_sym in ("RELIANCE", "TATAMOTORS"):
            # Uptrending series with surge on last 5 candles
            returns[-10:] += 0.005
        elif inject_pattern == "rsi_oversold" or clean_sym in ("HDFCBANK", "WIPRO"):
            # Strong downtrend series
            returns[-25:] -= 0.006
        elif inject_pattern == "rsi_overbought":
            returns[-25:] += 0.007

        price_series = base_price * np.cumprod(1 + returns)
        
        # Generate OHLC
        df_list = []
        now_ts = int(time.time())
        interval_secs = tf_minutes * 60
        
        for i in range(count):
            candle_ts = now_ts - (count - 1 - i) * interval_secs
            close_p = float(price_series[i])
            prev_p = float(price_series[i-1]) if i > 0 else close_p * 0.998
            
            open_p = prev_p + (np.random.uniform(-0.001, 0.001) * close_p)
            high_p = max(open_p, close_p) + abs(np.random.uniform(0.0005, 0.003) * close_p)
            low_p = min(open_p, close_p) - abs(np.random.uniform(0.0005, 0.003) * close_p)
            vol = int(np.random.uniform(5000, 45000) * (close_p / 100.0))
            
            # Inject open_high or open_low on last candle if requested
            if i == count - 1:
                if inject_pattern == "open_high" or clean_sym == "INFY":
                    open_p = high_p
                    close_p = open_p - (0.008 * open_p)
                    low_p = close_p - (0.002 * open_p)
                elif inject_pattern == "open_low" or clean_sym == "SBIN":
                    open_p = low_p
                    close_p = open_p + (0.012 * open_p)
                    high_p = close_p + (0.003 * open_p)
                elif inject_pattern == "ema_breakout" or clean_sym in ("RELIANCE", "TATAMOTORS"):
                    vol = vol * 3  # Volume breakout
            
            df_list.append({
                "timestamp": candle_ts,
                "open": round(open_p, 2),
                "high": round(high_p, 2),
                "low": round(low_p, 2),
                "close": round(close_p, 2),
                "volume": max(100, vol)
            })
            
        df = pd.DataFrame(df_list)
        return df

    @classmethod
    def get_quote(cls, symbol: str) -> StockQuote:
        candles = cls.generate_candles(symbol, timeframe="5", count=30)
        latest = candles.iloc[-1]
        prev = candles.iloc[-2]
        
        ltp = float(latest["close"])
        prev_close = float(prev["close"])
        change = round(ltp - prev_close, 2)
        change_pct = round((change / prev_close) * 100.0, 2)
        
        return StockQuote(
            symbol=symbol,
            ltp=ltp,
            open=float(latest["open"]),
            high=float(latest["high"]),
            low=float(latest["low"]),
            prev_close=prev_close,
            volume=int(latest["volume"]),
            change=change,
            change_pct=change_pct,
            timestamp=time.time()
        )

    @classmethod
    def get_market_overview(cls) -> MarketStatusOverview:
        nifty_quote = cls.get_quote("NSE:NIFTY50-INDEX")
        bn_quote = cls.get_quote("NSE:NIFTYBANK-INDEX")
        
        sample_stocks = ["NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:HDFCBANK-EQ", "NSE:INFY-EQ", "NSE:SBIN-EQ", "NSE:TATAMOTORS-EQ"]
        quotes = [cls.get_quote(s) for s in sample_stocks]
        
        advances = sum(1 for q in quotes if q.change >= 0)
        declines = sum(1 for q in quotes if q.change < 0)
        
        sorted_gainers = sorted(quotes, key=lambda q: q.change_pct, reverse=True)
        
        return MarketStatusOverview(
            market_status="OPEN (Mock Simulator / Live Engine)",
            nifty_spot=nifty_quote.ltp,
            nifty_change_pct=nifty_quote.change_pct,
            banknifty_spot=bn_quote.ltp,
            banknifty_change_pct=bn_quote.change_pct,
            advances=advances,
            declines=declines,
            top_gainers=[{"symbol": SymbolUniverse.clean_symbol_name(q.symbol), "price": q.ltp, "change_pct": q.change_pct} for q in sorted_gainers[:3]],
            top_losers=[{"symbol": SymbolUniverse.clean_symbol_name(q.symbol), "price": q.ltp, "change_pct": q.change_pct} for q in sorted_gainers[-3:]],
            is_mock=True
        )
