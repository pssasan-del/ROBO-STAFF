from mudrex_service import MudrexService
from market_agent import resolve_symbol

def test_rest_symbol(): assert MudrexService.rest_symbol('BTCUSDT')=='BTC/USDT'
def test_aliases(): assert resolve_symbol('btc current price')=='BTCUSDT' and resolve_symbol('Ethereum rate')=='ETHUSDT'
