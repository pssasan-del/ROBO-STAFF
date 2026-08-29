from photo_agent import _norm_symbol, _json

def test_photo_symbol_normalization():
    assert _norm_symbol('BTC/USDT') == 'BTCUSD'
    assert _norm_symbol('ETH') == 'ETHUSD'
    assert _norm_symbol('SOL') is None

def test_photo_json_extract():
    d=_json('```json\n{"image_type":"position","symbol":"BTCUSD"}\n```')
    assert d['image_type']=='position'
