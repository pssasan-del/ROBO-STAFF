from mudrex_service import MudrexService


def test_mudrex_aggregation_aliases():
    assert MudrexService.api_aggregation('1m') == '1m'
    assert MudrexService.api_aggregation('5m') == '5t'
    assert MudrexService.api_aggregation('15m') == '15t'
    assert MudrexService.api_aggregation('1d') == '1d'


def test_kline_schema_parser():
    payload = {
        'success': True,
        'data': {
            'asset_ticks': {
                'btc/usdt': [[1680312600, 28436.6, 28449.81, 28436.6, 28449.81, 0.742521]],
                'eth/usdt': [[1680312600, 1812.4, 1813.9, 1811.0, 1813.2, 15.20831]],
            }
        },
    }
    out = MudrexService._parse_kline_response(payload, 100)
    assert out['BTCUSDT'][0][4] == 28449.81
    assert out['ETHUSDT'][0][5] == 15.20831


def test_websocket_ticker_array_schema():
    msg = {
        'stream': 'ticker@5s',
        'data': [
            {'s': 'btcusdt', 'p': 67200.0, 'mp': 67210.0},
            {'s': 'ethusdt', 'p': 3500.0},
        ],
    }
    ticks = MudrexService._extract_tickers(msg)
    assert ticks[0][0] == 'BTCUSDT'
    assert ticks[0][1] == 67200.0
    assert ticks[0][2] == 67210.0
    assert ticks[1][0] == 'ETHUSDT'
