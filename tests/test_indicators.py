from indicators import ema,rsi

def test_ema(): assert ema([1,2,3,4,5],3)>3
def test_rsi(): assert rsi(list(range(1,30)))>90
