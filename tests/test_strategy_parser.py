from strategy_parser import validate_strategy

def test_valid_strategy():
    d=validate_strategy({'name':'BTC Trend','symbol':'BTCUSD','timeframe':'5m','side':'LONG','rules':[{'left':{'indicator':'ema','period':20},'op':'>','right':{'type':'indicator','indicator':'ema','period':50}}]})
    assert d['symbol']=='BTCUSD' and d['rules'][0]['left']['period']==20

def test_reject_bad_indicator():
    import pytest
    with pytest.raises(ValueError):
        validate_strategy({'name':'x','symbol':'BTCUSD','timeframe':'5m','rules':[{'left':{'indicator':'magic','period':2},'op':'>','right':{'type':'value','value':1}}]})
