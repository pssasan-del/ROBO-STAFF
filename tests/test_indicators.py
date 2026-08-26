import pytest
import pandas as pd
import numpy as np
from indicators import TechnicalIndicators
from mock_market import MockMarketService

def test_sma_calculation():
    series = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    sma_3 = TechnicalIndicators.sma(series, period=3)
    assert pd.isna(sma_3.iloc[0])
    assert pd.isna(sma_3.iloc[1])
    assert pytest.approx(sma_3.iloc[2], 0.01) == 20.0  # (10+20+30)/3
    assert pytest.approx(sma_3.iloc[4], 0.01) == 40.0  # (30+40+50)/3

def test_ema_calculation():
    series = pd.Series([100.0 + i for i in range(30)])
    ema_10 = TechnicalIndicators.ema(series, period=10)
    assert len(ema_10) == 30
    assert not pd.isna(ema_10.iloc[-1])
    assert ema_10.iloc[-1] > 100.0

def test_rsi_calculation():
    # 50 candles
    candles = MockMarketService.generate_candles("NSE:RELIANCE-EQ", timeframe="5", count=50)
    rsi_series = TechnicalIndicators.rsi(candles['close'], period=14)
    assert len(rsi_series) == 50
    latest_rsi = rsi_series.iloc[-1]
    assert 0.0 <= latest_rsi <= 100.0

def test_macd_calculation():
    candles = MockMarketService.generate_candles("NSE:TCS-EQ", timeframe="5", count=60)
    macd_l, sig_l, hist = TechnicalIndicators.macd(candles['close'], fast=12, slow=26, signal=9)
    assert len(macd_l) == 60
    assert not pd.isna(macd_l.iloc[-1])
    assert not pd.isna(sig_l.iloc[-1])
    assert pytest.approx(hist.iloc[-1], 0.001) == (macd_l.iloc[-1] - sig_l.iloc[-1])

def test_vwap_calculation():
    candles = MockMarketService.generate_candles("NSE:INFY-EQ", timeframe="5", count=30)
    vwap_series = TechnicalIndicators.vwap(candles)
    assert len(vwap_series) == 30
    assert vwap_series.iloc[-1] > 0.0

def test_bollinger_bands():
    candles = MockMarketService.generate_candles("NSE:SBIN-EQ", timeframe="5", count=40)
    upper, mid, lower = TechnicalIndicators.bollinger_bands(candles['close'], period=20, std_dev=2.0)
    assert upper.iloc[-1] > mid.iloc[-1] > lower.iloc[-1]

def test_crossover_and_crossunder():
    series_a = pd.Series([10.0, 15.0, 25.0])
    series_b = pd.Series([12.0, 16.0, 20.0])
    # At index -2: 15 <= 16; at index -1: 25 > 20 -> Crossover
    assert TechnicalIndicators.crossover(series_a, series_b) is True
    assert TechnicalIndicators.crossunder(series_a, series_b) is False

    # Reverse
    series_c = pd.Series([25.0, 20.0, 15.0])
    series_d = pd.Series([10.0, 18.0, 22.0])
    assert TechnicalIndicators.crossunder(series_c, series_d) is True

def test_open_high_and_open_low():
    # Exactly equal
    assert TechnicalIndicators.is_open_high(100.0, 100.0, tolerance_pct=0.05) is True
    # Within 0.04% tolerance
    assert TechnicalIndicators.is_open_high(100.0, 100.04, tolerance_pct=0.05) is True
    # Outside tolerance
    assert TechnicalIndicators.is_open_high(100.0, 101.0, tolerance_pct=0.05) is False

    assert TechnicalIndicators.is_open_low(100.0, 100.0, tolerance_pct=0.05) is True
    assert TechnicalIndicators.is_open_low(100.0, 99.96, tolerance_pct=0.05) is True
    assert TechnicalIndicators.is_open_low(100.0, 98.0, tolerance_pct=0.05) is False
