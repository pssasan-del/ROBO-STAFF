import tempfile, os
from strategy_store import StrategyStore
from config import settings

def test_sqlite_store():
    old_url,old_path=settings.DATABASE_URL,settings.SQLITE_PATH
    with tempfile.TemporaryDirectory() as d:
        settings.DATABASE_URL='';settings.SQLITE_PATH=os.path.join(d,'x.db')
        s=StrategyStore();s.init()
        x={'name':'A','symbol':'BTCUSD','timeframe':'5m','side':'LONG','rules':[{'left':{'indicator':'rsi','period':14},'op':'>','right':{'type':'value','value':55}}]}
        sid=s.create(1,x,'test'); assert s.count(1)==1
        s.set_active(1,sid,True); assert s.active_count(1)==1
        s.delete(1,sid); assert s.count(1)==0
    settings.DATABASE_URL,settings.SQLITE_PATH=old_url,old_path
