import time
import pytest
from models import StrategyDefinition, StrategyCondition
from scanner import ContinuousScanner

def test_scanner_lifecycle():
    sc = ContinuousScanner()
    strat = StrategyDefinition(
        id="test_strat_1",
        name="Test 5M EMA",
        timeframe="5",
        universe="NIFTY50",
        conditions=[StrategyCondition(type="candle_bullish")]
    )

    state = sc.add_scanner(strat)
    assert state.status == "RUNNING"
    assert len(sc.get_active_scanners()) == 1

    # Pause
    sc.pause_scanner("test_strat_1")
    assert sc.get_active_scanners()[0].status == "PAUSED"

    # Resume
    sc.resume_scanner("test_strat_1")
    assert sc.get_active_scanners()[0].status == "RUNNING"

    # Stop
    sc.stop_scanner("test_strat_1")
    assert len(sc.get_active_scanners()) == 0

def test_scanner_stop_all():
    sc = ContinuousScanner()
    sc.add_scanner(StrategyDefinition(id="s1", name="S1", conditions=[]))
    sc.add_scanner(StrategyDefinition(id="s2", name="S2", conditions=[]))
    assert len(sc.get_active_scanners()) == 2

    stopped = sc.stop_all()
    assert stopped == 2
    assert len(sc.get_active_scanners()) == 0
