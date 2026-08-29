from strategy_engine import StrategyEngine, fibonacci_pivots, alligator, trix, macd_values, directional_values, bollinger, donchian, supertrend, williams_r, stoch_rsi, roc
from strategy_parser import validate_strategy
from market_agent import timeframe, indicator_request

def candles(n=220):
    out=[]
    for i in range(n):
        p=100+i*0.5
        out.append({'time':i,'open':p-0.2,'high':p+1,'low':p-1,'close':p,'volume':1000+i*3})
    return out

def test_fib_pivot_exact_formula():
    d=fibonacci_pivots({'high':110,'low':100,'close':106})
    assert round(d['pivot'],6)==round((110+100+106)/3,6)
    assert d['fib_r1']>d['pivot']>d['fib_s1']

def test_advanced_indicator_values_are_finite():
    rows=candles();cl=[x['close'] for x in rows]
    vals=[]
    vals += list(alligator(rows))
    vals += [trix(cl,15), *macd_values(cl), *directional_values(rows,14)]
    vals += list(bollinger(cl,20,2)) + list(donchian(rows,20))
    vals += [supertrend(rows,10,3),williams_r(rows,14),stoch_rsi(cl,14),roc(cl,12)]
    assert all(isinstance(v,float) for v in vals)

def test_engine_alligator_and_trix_rules():
    e=StrategyEngine();rows=candles()
    r1={'left':{'indicator':'alligator_lips'},'op':'>','right':{'type':'indicator','indicator':'alligator_teeth'}}
    e._rule(r1,rows)
    r2={'left':{'indicator':'trix','period':15},'op':'>','right':{'type':'value','value':0}}
    ok,_,_=e._rule(r2,rows); assert ok

def test_parser_accepts_new_indicators():
    d={'name':'A','symbol':'BTCUSD','timeframe':'5m','side':'LONG','rules':[
        {'left':{'indicator':'alligator_lips'},'op':'>','right':{'type':'indicator','indicator':'alligator_teeth'}},
        {'left':{'indicator':'trix','period':15},'op':'>','right':{'type':'value','value':0}},
        {'left':{'indicator':'adx','period':14},'op':'>','right':{'type':'value','value':20}},
        {'left':{'indicator':'close'},'op':'>','right':{'type':'indicator','indicator':'fib_r1'}}]}
    assert validate_strategy(d)['rules'][3]['right']['indicator']=='fib_r1'

def test_indicator_query_routing():
    assert timeframe('BTC fib R1 15 min ethra')=='15m'
    req=indicator_request('BTC 5m alligator trix adx fib r1')
    assert {'alligator','trix','adx','fib'}.issubset(set(req))
