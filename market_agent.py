import re
from datetime import datetime,timezone,timedelta
from ai_router import ai_router
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from config import logger

ALIASES={'bitcoin':'BTCUSD','bit coin':'BTCUSD','btc':'BTCUSD','ethereum':'ETHUSD','etherium':'ETHUSD','ether':'ETHUSD','eth':'ETHUSD'}
PRICE_WORDS=('price','current','live','ltp','rate','premium','ethra','etra','ippo','ഇപ്പോൾ','എത്ര')
ANALYSIS_WORDS=('rsi','trend','analyse','analysis','buy','sell','support','resistance','signal','entry','target','stop loss','sl','technical')
OPTION_WORDS=(' ce',' pe','call','put','option','options','strike','premium')
MONTHS={'jan':1,'january':1,'feb':2,'february':2,'mar':3,'march':3,'apr':4,'april':4,'may':5,'jun':6,'june':6,'jul':7,'july':7,'aug':8,'august':8,'sep':9,'sept':9,'september':9,'oct':10,'october':10,'nov':11,'november':11,'dec':12,'december':12}
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

class MarketAgent:
    async def answer(self,text):
        sym=resolve_symbol(text); wopt=option_q(text); wprice=has(text,PRICE_WORDS); wana=has(text,ANALYSIS_WORDS); md='(no market data needed)'
        st=strike(text) if wopt else None; ex=expiry(text) if wopt else None
        if wopt and sym in {'BTCUSD','ETHUSD'} and st is not None:
            und='BTC' if sym=='BTCUSD' else 'ETH'
            try:
                snap=await delta_options_service.get_strike_snapshot(und,st,ex); md=f'DELTA OPTIONS DATA: {snap}'
                logger.info('[DELTA_TOOL] supplied %s options strike=%s',und,st)
            except Exception as e:md=f'DELTA OPTIONS DATA unavailable: {e}'
        elif wopt and sym:md='Option request detected but strike missing. Ask user for strike.'
        elif sym and (wprice or wana):
            try:
                q=await delta_market_service.get_ticker(sym);md=f'DELTA MARKET DATA: {q}.'
                if wana:
                    rows=await delta_market_service.get_candles(sym,'5m',80);cl=[x['close'] for x in rows]
                    from strategy_engine import rsi,ema
                    md+=f' 5m RSI14={rsi(cl,14):.2f}; EMA20={ema(cl,20):.4f}; EMA50={ema(cl,50):.4f}; candles={len(rows)}.'
            except Exception as e:md=f'DELTA MARKET DATA unavailable: {e}'
        elif (wprice or wana or wopt) and not sym:md='Market question detected but coin unresolved; ask whether BTC or ETH.'
        system=("You are STAFF BOT, a respectful personal crypto-market assistant. Reply in the user's Malayalam/Manglish/English style. "
                "All live crypto data, candles and BTC/ETH options come from Delta Exchange India public read-only APIs. Use supplied values as truth. "
                "Never invent prices, Greeks or signals. For options show expiry, selected strike, CE/Call and PE/Put premiums, and mention nearest strike if exact is false. "
                "The app is signal-only and never places orders. Keep answers concise; do not repeat generic warnings unless relevant.")
        return await ai_router.answer(f'USER: {text}\n\nMARKET DATA:\n{md}\n\nAnswer directly.',system)
market_agent=MarketAgent()
