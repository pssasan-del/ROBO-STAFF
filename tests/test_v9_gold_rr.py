import asyncio
import pytest
from config import settings
from delta_market_service import DeltaMarketService
from delta_options_service import DeltaOptionsService
from market_agent import resolve_symbol
from strategy_engine import risk_reward_targets
from strategy_parser import validate_strategy


def test_gold_aliases():
    assert DeltaMarketService.normalize_symbol('gold') == 'XAUTUSD'
    assert DeltaMarketService.normalize_symbol('xau') == 'XAUTUSD'
    assert DeltaMarketService.normalize_symbol('xaut') == 'XAUTUSD'
    assert resolve_symbol('gold 5m fib r1 ethra') == 'XAUTUSD'


def test_gold_strategy_is_allowed():
    d=validate_strategy({'name':'Gold Trend','symbol':'GOLD','timeframe':'5m','side':'LONG','rules':[{'left':{'indicator':'ema','period':20},'op':'>','right':{'type':'indicator','indicator':'ema','period':50}}]})
    assert d['symbol']=='XAUTUSD'


def test_rr_targets_long_and_short():
    x=risk_reward_targets(100,90,'LONG')
    assert x['t1_rr']==pytest.approx(1.85)
    assert x['t1']==pytest.approx(118.5)
    assert x['t2']==pytest.approx(123.0)
    assert x['t3']==pytest.approx(130.0)
    y=risk_reward_targets(100,110,'SHORT')
    assert y['t1']==pytest.approx(81.5)
    assert y['t2']==pytest.approx(77.0)
    assert y['t3']==pytest.approx(70.0)


def test_rr_floor_rejects_lower_t1():
    with pytest.raises(ValueError):
        risk_reward_targets(100,90,'LONG',rr1=1.5)


def test_xaut_option_symbol_parse():
    p=DeltaOptionsService.parse_symbol('C-XAUT-4200-300826')
    assert p and p['underlying']=='XAUT' and p['side']=='CE' and p['strike']==4200


def test_default_symbol_set_contains_only_three_assets():
    assert {'BTCUSD','ETHUSD','XAUTUSD'}.issubset(set(settings.delta_symbols()))
