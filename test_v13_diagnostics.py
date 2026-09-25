import json
from performance_store import PerformanceStore
from entry_backtest import EntryBacktester

def test_detailed_stats_and_sl_recovery(tmp_path):
    s=PerformanceStore(str(tmp_path/'stats.json'))
    s.new_signal('OPTION BUY','CONFIRM (85%)','BTC')
    s.resolve('OPTION BUY',False,'BTC','CONFIRM (85%)',120)
    s.mark_sl_recovery('t1')
    r=s.report(1)
    assert r['failed']==1 and r['actions']['OPTION BUY']['failed']==1
    assert r['assets']['BTC']['failed']==1 and r['ai']['confirm']['failed']==1
    assert r['timing']['sl_under_5m']==1 and r['sl_later_t1']==1

def test_ai_groups():
    assert EntryBacktester._structure([{'high':1,'low':0}]*12) in {'RANGE','UNKNOWN'}
