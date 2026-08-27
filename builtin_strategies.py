from models import StrategyDefinition, StrategyCondition

# Deterministic stock scanners derived from the Chartink rules supplied by the user.
# Where Chartink has a condition the generic engine cannot represent exactly, we use
# the closest deterministic OHLCV equivalent and keep the strategy clearly named.

def stock_strategy(key: str) -> StrategyDefinition:
    k = key.lower()
    common_bull = [
        StrategyCondition(type='ema_compare', fast=20, slow=50, operator='>', description='EMA20 > EMA50'),
        StrategyCondition(type='rsi', period=14, operator='>', value=55, description='RSI14 > 55'),
        StrategyCondition(type='vwap', operator='>', description='Close > VWAP'),
        StrategyCondition(type='volume_average', period=20, operator='>', value=1.5, description='Volume > 1.5x SMA20'),
        StrategyCondition(type='breakout', lookback=20, description='20-candle breakout'),
    ]
    common_bear = [
        StrategyCondition(type='ema_compare', fast=20, slow=50, operator='<', description='EMA20 < EMA50'),
        StrategyCondition(type='rsi', period=14, operator='<', value=50, description='RSI14 < 50'),
        StrategyCondition(type='vwap', operator='<', description='Close < VWAP'),
        StrategyCondition(type='volume_average', period=20, operator='>', value=1.5, description='Volume > 1.5x SMA20'),
        StrategyCondition(type='breakdown', lookback=20, description='20-candle breakdown'),
    ]
    if k == 'sure_call':
        return StrategyDefinition(id='builtin_sure_call', name='200% Sure Call', timeframe='15', universe='NIFTY100', logic='AND', conditions=common_bull, description='Bullish trend + RSI + VWAP + volume + breakout')
    if k == 'put':
        return StrategyDefinition(id='builtin_200_put', name='200% Put', timeframe='15', universe='NIFTY100', logic='AND', conditions=common_bear, description='Bearish trend + RSI + VWAP + volume + breakdown')
    if k == 'orb_call':
        return StrategyDefinition(id='builtin_orb_call', name='ORB 200% Call', timeframe='15', universe='NIFTY100', logic='AND', conditions=common_bull + [StrategyCondition(type='macd', operator='>', description='MACD positive')], description='ORB-style bullish breakout confirmation')
    if k == 'orb_put':
        return StrategyDefinition(id='builtin_orb_put', name='ORB 200% Put', timeframe='15', universe='NIFTY100', logic='AND', conditions=common_bear + [StrategyCondition(type='macd', operator='<', description='MACD negative')], description='ORB-style bearish breakdown confirmation')
    if k == 'mixed44':
        return StrategyDefinition(id='builtin_mixed44', name='Mid/Small 44 Mixed Momentum', timeframe='15', universe='MIDSMALL44', logic='AND', conditions=[
            StrategyCondition(type='ema_compare', fast=20, slow=50, operator='>', description='EMA20 > EMA50'),
            StrategyCondition(type='rsi', period=14, operator='>', value=52, description='RSI14 > 52'),
            StrategyCondition(type='vwap', operator='>', description='Close > VWAP'),
            StrategyCondition(type='volume_average', period=20, operator='>', value=1.5, description='Volume expansion'),
            StrategyCondition(type='breakout', lookback=20, description='Momentum breakout'),
        ], description='22 midcap + 22 smallcap controlled scanner')
    raise KeyError(key)
