from delta_market_service import DeltaMarketService
from delta_options_service import DeltaOptionsService

def test_symbol_aliases():
    assert DeltaMarketService.normalize_symbol('BTCUSDT')=='BTCUSD'
    assert DeltaMarketService.normalize_symbol('ETH')=='ETHUSD'

def test_option_symbol():
    p=DeltaOptionsService.parse_symbol('C-BTC-77400-290826')
    assert p['side']=='CE' and p['strike']==77400
