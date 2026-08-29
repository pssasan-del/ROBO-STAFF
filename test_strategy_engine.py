import pytest
import pandas as pd
from models import StrategyDefinition, StrategyCondition
from strategy_engine import StrategyEngine
from mock_market import MockMarketService

def test_evaluate_open_high_strategy():
    strategy = StrategyDefinition(
        name="Open High Test",
        timeframe="5",
        universe="NIFTY50",
        logic="AND",
        conditions=[StrategyCondition(type="open_high", tolerance_pct=0.05)]
    )

    # Injected open_high candle
    df_match = MockMarketService.generate_candles("NSE:INFY-EQ", timeframe="5", count=30, inject_pattern="open_high")
    match = StrategyEngine.evaluate_strategy(strategy, "NSE:INFY-EQ", df_match, is_mock=True)
    assert match is not None
    assert match.symbol == "NSE:INFY-EQ"
    assert len(match.matched_conditions) == 1
    assert match.matched_conditions[0].passed is True

def test_evaluate_and_vs_or_logic():
    cond_true = StrategyCondition(type="candle_bullish")
    cond_impossible = StrategyCondition(type="rsi", period=14, operator=">", value=99.9)

    # AND logic should fail if one fails
    strat_and = StrategyDefinition(
        name="AND Strategy",
        logic="AND",
        conditions=[cond_true, cond_impossible]
    )
    df = MockMarketService.generate_candles("NSE:RELIANCE-EQ", count=40)
    match_and = StrategyEngine.evaluate_strategy(strat_and, "NSE:RELIANCE-EQ", df)
    assert match_and is None

    # OR logic should pass if at least one passes
    strat_or = StrategyDefinition(
        name="OR Strategy",
        logic="OR",
        conditions=[cond_true, cond_impossible]
    )
    # Ensure bullish candle
    df.iloc[-1, df.columns.get_loc('close')] = df.iloc[-1]['open'] + 10.0
    match_or = StrategyEngine.evaluate_strategy(strat_or, "NSE:RELIANCE-EQ", df)
    assert match_or is not None
