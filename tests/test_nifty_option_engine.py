import pandas as pd
from indicators import TechnicalIndicators
from nifty_option_engine import NiftyOptionSignalEngine


def test_williams_r_range():
    df = pd.DataFrame({
        'high': list(range(10, 30)), 'low': list(range(5, 25)), 'close': list(range(8, 28)), 'volume':[100]*20
    })
    wr = TechnicalIndicators.williams_r(df, 14)
    assert -100 <= float(wr.iloc[-1]) <= 0


def test_adx_nonnegative():
    df = pd.DataFrame({
        'high': [100+i for i in range(40)], 'low':[98+i for i in range(40)], 'close':[99+i for i in range(40)], 'volume':[100]*40
    })
    adx = TechnicalIndicators.adx(df, 14)
    assert float(adx.iloc[-1]) >= 0


def test_fib_pivot_ordering():
    p = NiftyOptionSignalEngine._fib_pivots(110, 90, 100)
    assert p['S2'] < p['S1'] < p['P'] < p['R1'] < p['R2']
