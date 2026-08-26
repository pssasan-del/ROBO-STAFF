import pytest
from strategy_parser import StrategyParser
from errors import StrategyParseError


def test_quick_parse_open_high():
    strat = StrategyParser.parse_quick_rule("Open high stocks search cheyyu")
    assert strat is not None
    assert strat.conditions[0].type == "open_high"


def test_quick_parse_open_low():
    strat = StrategyParser.parse_quick_rule("open low stocks kaanikk")
    assert strat is not None
    assert strat.conditions[0].type == "open_low"


def test_quick_parse_rsi_below():
    strat = StrategyParser.parse_quick_rule("RSI 30 below stocks scan cheyyu")
    assert strat is not None
    assert strat.conditions[0].type == "rsi"
    assert strat.conditions[0].value == 30.0
    assert strat.conditions[0].operator == "<"


def test_quick_parse_ema_cross():
    strat = StrategyParser.parse_quick_rule("EMA 20 EMA 50 cross scan cheyyu")
    assert strat is not None
    assert strat.conditions[0].type == "ema_compare"
    assert strat.conditions[0].fast == 20
    assert strat.conditions[0].slow == 50


def test_ai_parse_failure_never_invents_fallback(monkeypatch):
    from strategy_parser import ai_router
    monkeypatch.setattr(ai_router, "generate_response", lambda **kwargs: "not json")
    with pytest.raises(StrategyParseError):
        StrategyParser.parse_strategy("random unknown text")
