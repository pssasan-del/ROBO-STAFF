from strategy_engine import StrategyEngine

def candles(n=80):
    out=[]
    for i in range(n):
        p=100+i
        out.append({'time':i,'open':p-1,'high':p+1,'low':p-2,'close':p,'volume':100+i})
    return out

def test_rule_ema():
    e=StrategyEngine(); rows=candles()
    r={'left':{'indicator':'ema','period':20},'op':'>','right':{'type':'indicator','indicator':'ema','period':50}}
    ok,_,_=e._rule(r,rows); assert ok

def test_cross():
    e=StrategyEngine(); rows=candles()
    r={'left':{'indicator':'close'},'op':'>','right':{'type':'indicator','indicator':'sma','period':20}}
    ok,_,_=e._rule(r,rows); assert ok
