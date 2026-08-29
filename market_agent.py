import re
from datetime import datetime,timezone,timedelta
from ai_router import ai_router
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from config import logger

ALIASES={'bitcoin':'BTCUSD','bit coin':'BTCUSD','btc':'BTCUSD','ethereum':'ETHUSD','etherium':'ETHUSD','ether':'ETHUSD','eth':'ETHUSD'}
PRICE_WORDS=('price','current','live','ltp','rate','premium','ethra','etra','ippo','ഇപ്പോൾ','എത്ര')
ANALYSIS_WORDS=('rsi','trend','analyse','analysis','buy','sell','support','resistance','signal','entry','target','stop loss','sl','technical','pivot','fibonacci','fib','macd','adx','trix','alligator','supertrend','williams','stoch','bollinger','obv','donchian','roc','atr','vwap')
OPTION_WORDS=(' ce',' pe','call','put','option','options','strike','premium')
IST=timezone(timedelta(hours=5,minutes=30))

def norm(t):return re.sub(r'\s+',' ',re.sub(r'\bbit\s+coin\b','bitcoin',t.lower().strip()))
def resolve_symbol(text):
    t=norm(text)
    for n in sorted(ALIASES,key=len,reverse=True):
        if re.search(rf'(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])',t):return ALIASES[n]
    return None
def has(text,words):
    t=norm(text);return any(w in t for w in words)
def option_q(text):
    t=' '+norm(text)+' ';return any(w in t for w in OPTION_WORDS) or bool(re.search(r'\b\d{3,7}(?:\.\d+)?\s*(?:ce|pe)\b',t))
def strike(text):
    t=norm(text);m=re.search(r'\b([0-9]{3,7}(?:\.[0-9]+)?)\s*(?:ce|pe|call|put)\b',t)
    if m:return float(m.group(1))
    nums=[float(x) for x in re.findall(r'\b([0-9]{3,7}(?:\.[0-9]+)?)\b',t)];return nums[0] if option_q(t) and nums else None
def expiry(text):
    t=norm(text)
    for pat,fmt in [(r'\b(\d{1,2}-\d{1,2}-\d{4})\b','%d-%m-%Y'),(r'\b(\d{4}-\d{1,2}-\d{1,2})\b','%Y-%m-%d')]:
        m=re.search(pat,t)
        if m:
            try:return datetime.strptime(m.group(1),fmt).date().strftime('%d-%m-%Y')
            except:pass
    return None
def timeframe(text):
    t=norm(text)
    pats=[(r'\b(1|3|5|15|30)\s*(?:m|min|mins|minute|minutes)\b',lambda m:f'{m.group(1)}m'),(r'\b(1|2|4|6|12)\s*(?:h|hr|hour|hours)\b',lambda m:f'{m.group(1)}h'),(r'\b(?:1\s*)?(?:d|day|daily)\b',lambda m:'1d')]
    for p,f in pats:
        m=re.search(p,t)
        if m:return f(m)
    return '5m'

def indicator_request(text):
    t=norm(text);out=[]
    pairs=[('fib','fib'),('fibonacci','fib'),('pivot','fib'),('alligator','alligator'),('trix','trix'),('macd','macd'),('adx','adx'),('williams','williams_r'),('%r','williams_r'),('supertrend','supertrend'),('stoch','stoch_rsi'),('bollinger','bollinger'),('obv','obv'),('donchian','donchian'),('roc','roc'),('atr','atr'),('vwap','vwap'),('rsi','rsi')]
    for k,v in pairs:
        if k in t and v not in out:out.append(v)
    return out

async def build_indicator_snapshot(sym,tf,requested):
    from strategy_engine import StrategyEngine,fibonacci_pivots,macd_values,directional_values,alligator,bollinger,donchian,rsi,ema,trix,stoch_rsi,williams_r,supertrend,obv,roc,atr,vwap
    rows=await delta_market_service.get_candles(sym,tf,180);cl=[x['close'] for x in rows];e=StrategyEngine();d={'symbol':sym,'timeframe':tf,'price':rows[-1]['close'],'candles':len(rows)}
    if 'fib' in requested:
        base=rows[-2] if len(rows)>=2 else rows[-1];d['fibonacci_pivots']=fibonacci_pivots(base);d['pivot_basis']={'time':base['time'],'high':base['high'],'low':base['low'],'close':base['close']}
    if 'alligator' in requested:
        j,t,l=alligator(rows);d['alligator']={'jaw':j,'teeth':t,'lips':l}
    if 'trix' in requested:d['trix15']=trix(cl,15)
    if 'macd' in requested:
        m,s,h=macd_values(cl);d['macd']={'macd':m,'signal':s,'histogram':h}
    if 'adx' in requested:
        a,p,m=directional_values(rows,14);d['adx14']={'adx':a,'plus_di':p,'minus_di':m}
    if 'williams_r' in requested:d['williams_r14']=williams_r(rows,14)
    if 'supertrend' in requested:d['supertrend_10_3']=supertrend(rows,10,3)
    if 'stoch_rsi' in requested:d['stoch_rsi14']=stoch_rsi(cl,14)
    if 'bollinger' in requested:
        u,m,l=bollinger(cl,20,2);d['bollinger_20_2']={'upper':u,'middle':m,'lower':l}
    if 'obv' in requested:d['obv']=obv(rows)
    if 'donchian' in requested:
        u,m,l=donchian(rows,20);d['donchian20']={'upper':u,'middle':m,'lower':l}
    if 'roc' in requested:d['roc12']=roc(cl,12)
    if 'atr' in requested:d['atr14']=atr(rows,14)
    if 'vwap' in requested:d['vwap30']=vwap(rows,30)
    if 'rsi' in requested:d['rsi14']=rsi(cl,14)
    return d

class MarketAgent:
    async def answer(self,text):
        sym=resolve_symbol(text); wopt=option_q(text); wprice=has(text,PRICE_WORDS); wana=has(text,ANALYSIS_WORDS); requested=indicator_request(text); md='(no market data needed)'
        st=strike(text) if wopt else None; ex=expiry(text) if wopt else None
        if wopt and sym in {'BTCUSD','ETHUSD'} and st is not None:
            und='BTC' if sym=='BTCUSD' else 'ETH'
            try:
                snap=await delta_options_service.get_strike_snapshot(und,st,ex); md=f'DELTA OPTIONS DATA: {snap}'
                logger.info('[DELTA_TOOL] supplied %s options strike=%s',und,st)
            except Exception as e:md=f'DELTA OPTIONS DATA unavailable: {e}'
        elif wopt and sym:md='Option request detected but strike missing. Ask user for strike.'
        elif sym and requested:
            tf=timeframe(text)
            try:
                snap=await build_indicator_snapshot(sym,tf,requested);md=f'DELTA INDICATOR DATA (exact deterministic calculations): {snap}'
                logger.info('[INDICATOR_TOOL] supplied %s %s indicators=%s',sym,tf,','.join(requested))
            except Exception as e:md=f'DELTA INDICATOR DATA unavailable: {e}'
        elif sym and (wprice or wana):
            try:
                q=await delta_market_service.get_ticker(sym);md=f'DELTA MARKET DATA: {q}.'
                if wana:
                    rows=await delta_market_service.get_candles(sym,'5m',100);cl=[x['close'] for x in rows]
                    from strategy_engine import rsi,ema,directional_values
                    a,p,m=directional_values(rows,14)
                    md+=f' 5m RSI14={rsi(cl,14):.2f}; EMA20={ema(cl,20):.4f}; EMA50={ema(cl,50):.4f}; ADX14={a:.2f}; +DI={p:.2f}; -DI={m:.2f}; candles={len(rows)}.'
            except Exception as e:md=f'DELTA MARKET DATA unavailable: {e}'
        elif (wprice or wana or wopt) and not sym:md='Market question detected but coin unresolved; ask whether BTC or ETH.'
        system=("You are STAFF BOT, a respectful personal crypto-market assistant. Reply in the user's Malayalam/Manglish/English style. "
                "All live crypto data, candles and BTC/ETH options come from Delta Exchange India public read-only APIs. Deterministic indicator values are calculated by the Python engine from Delta candles. Use supplied values as truth. "
                "Never invent prices, pivots, indicator values, Greeks or signals. If Fibonacci pivot data is supplied, quote the exact requested P/R/S level and timeframe, not an approximation. "
                "For options show expiry, selected strike, CE/Call and PE/Put premiums, and mention nearest strike if exact is false. The app is signal-only and never places orders. Keep answers concise; do not repeat generic warnings unless relevant.")
        return await ai_router.answer(f'USER: {text}\n\nMARKET DATA:\n{md}\n\nAnswer directly.',system)
market_agent=MarketAgent()
