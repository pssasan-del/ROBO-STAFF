from market_agent import resolve_symbol, is_price_question, is_analysis_question


def test_symbol_variants():
    assert resolve_symbol('crypto bit coin current price ethraya') == 'BTCUSDT'
    assert resolve_symbol('Bitcoin ethra') == 'BTCUSDT'
    assert resolve_symbol('BTC/USDT live price') == 'BTCUSDT'
    assert resolve_symbol('etherium current price') == 'ETHUSDT'
    assert resolve_symbol('ETH price') == 'ETHUSDT'


def test_intents():
    assert is_price_question('bitcoin current price ethra')
    assert is_analysis_question('BTC RSI trend analysis')
