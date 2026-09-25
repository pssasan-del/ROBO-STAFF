from market_research import MarketReplay, ResearchStore


def test_market_replay_feature_breakout_up():
    rows=[]
    for i in range(45):
        base=100+i*0.2
        rows.append({'time':i,'open':base-.1,'high':base+.2,'low':base-.2,'close':base,'volume':100})
    rows[-1]['close']=120;rows[-1]['high']=120.2;rows[-1]['volume']=250
    f=MarketReplay._features(rows)
    assert f['breakout']=='UP'
    assert f['rvol']>1


def test_research_store_ram_summary_is_bounded_shape():
    r=ResearchStore()
    # This assertion validates the report contract without requiring live Delta data.
    out=r.summary()
    assert set(out)=={'total','recovered','buckets'}
