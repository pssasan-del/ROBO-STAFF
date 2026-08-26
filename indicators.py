import numpy as np
import pandas as pd
from typing import Tuple, Optional

class TechnicalIndicators:
    """
    Deterministic, high-performance Technical Indicators Engine.
    Handles historical OHLCV dataFrames with graceful fallback for insufficient candles.
    """

    @staticmethod
    def sma(series: pd.Series, period: int = 20) -> pd.Series:
        if len(series) < period:
            return pd.Series(index=series.index, dtype=float)
        return series.rolling(window=period).mean()

    @staticmethod
    def ema(series: pd.Series, period: int = 20) -> pd.Series:
        if len(series) < period:
            return pd.Series(index=series.index, dtype=float)
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        if len(series) <= period:
            return pd.Series(index=series.index, dtype=float)
        
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        
        # Exponential smoothing for RSI (Wilder's method)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50.0)

    @staticmethod
    def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        if len(series) < slow:
            empty = pd.Series(index=series.index, dtype=float)
            return empty, empty, empty
        
        ema_fast = TechnicalIndicators.ema(series, fast)
        ema_slow = TechnicalIndicators.ema(series, slow)
        macd_line = ema_fast - ema_slow
        signal_line = TechnicalIndicators.ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def vwap(df: pd.DataFrame) -> pd.Series:
        """
        Volume Weighted Average Price.
        Expects columns: 'high', 'low', 'close', 'volume'
        """
        if len(df) == 0 or 'volume' not in df.columns:
            return pd.Series(index=df.index, dtype=float)
        
        typical_price = (df['high'] + df['low'] + df['close']) / 3.0
        pv = typical_price * df['volume']
        
        # If intraday with date groupings, calculate cumulative per day; otherwise overall cumulative
        if 'date' in df.columns:
            cum_pv = pv.groupby(df['date']).cumsum()
            cum_vol = df['volume'].groupby(df['date']).cumsum()
        else:
            cum_pv = pv.cumsum()
            cum_vol = df['volume'].cumsum()
            
        vwap_series = cum_pv / cum_vol.replace(0, np.nan)
        return vwap_series.fillna(typical_price)

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Average True Range.
        """
        if len(df) <= period:
            return pd.Series(index=df.index, dtype=float)
        
        high = df['high']
        low = df['low']
        close_prev = df['close'].shift(1)
        
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_series = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        return atr_series

    @staticmethod
    def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Returns (upper_band, middle_band, lower_band)
        """
        if len(series) < period:
            empty = pd.Series(index=series.index, dtype=float)
            return empty, empty, empty
        
        middle = TechnicalIndicators.sma(series, period)
        std = series.rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        return upper, middle, lower

    @staticmethod
    def volume_average(volume: pd.Series, period: int = 20) -> pd.Series:
        return TechnicalIndicators.sma(volume, period)

    @staticmethod
    def crossover(series_a: pd.Series, series_b: pd.Series) -> bool:
        """
        Returns True if series_a crossed above series_b on the most recent candle.
        """
        if len(series_a) < 2 or len(series_b) < 2:
            return False
        
        prev_a = series_a.iloc[-2]
        prev_b = series_b.iloc[-2]
        curr_a = series_a.iloc[-1]
        curr_b = series_b.iloc[-1]
        
        if pd.isna(prev_a) or pd.isna(prev_b) or pd.isna(curr_a) or pd.isna(curr_b):
            return False
            
        return bool((prev_a <= prev_b) and (curr_a > curr_b))

    @staticmethod
    def crossunder(series_a: pd.Series, series_b: pd.Series) -> bool:
        """
        Returns True if series_a crossed below series_b on the most recent candle.
        """
        if len(series_a) < 2 or len(series_b) < 2:
            return False
            
        prev_a = series_a.iloc[-2]
        prev_b = series_b.iloc[-2]
        curr_a = series_a.iloc[-1]
        curr_b = series_b.iloc[-1]
        
        if pd.isna(prev_a) or pd.isna(prev_b) or pd.isna(curr_a) or pd.isna(curr_b):
            return False
            
        return bool((prev_a >= prev_b) and (curr_a < curr_b))

    @staticmethod
    def is_breakout(df: pd.DataFrame, lookback: int = 20) -> bool:
        """
        Current close is greater than max high of previous `lookback` candles.
        """
        if len(df) <= lookback:
            return False
        
        prev_highs = df['high'].iloc[-(lookback + 1):-1]
        highest_prev = prev_highs.max()
        curr_close = df['close'].iloc[-1]
        
        return curr_close > highest_prev

    @staticmethod
    def is_breakdown(df: pd.DataFrame, lookback: int = 20) -> bool:
        """
        Current close is lower than min low of previous `lookback` candles.
        """
        if len(df) <= lookback:
            return False
        
        prev_lows = df['low'].iloc[-(lookback + 1):-1]
        lowest_prev = prev_lows.min()
        curr_close = df['close'].iloc[-1]
        
        return curr_close < lowest_prev

    @staticmethod
    def is_open_high(open_val: float, high_val: float, tolerance_pct: float = 0.05) -> bool:
        """
        Checks if Open is equal to High within tolerance percentage.
        e.g. For Bearish Open=High setup
        """
        if open_val <= 0:
            return False
        diff_pct = abs(high_val - open_val) / open_val * 100.0
        return diff_pct <= tolerance_pct

    @staticmethod
    def is_open_low(open_val: float, low_val: float, tolerance_pct: float = 0.05) -> bool:
        """
        Checks if Open is equal to Low within tolerance percentage.
        e.g. For Bullish Open=Low setup
        """
        if open_val <= 0:
            return False
        diff_pct = abs(open_val - low_val) / open_val * 100.0
        return diff_pct <= tolerance_pct
