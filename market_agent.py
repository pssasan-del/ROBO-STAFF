import re
from ai_router import ai_router
from mudrex_service import mudrex_service
from config import settings, logger

ALIASES={'bitcoin':'BTCUSDT','btc':'BTCUSDT','ethereum':'ETHUSDT','eth':'ETHUSDT','solana':'SOLUSDT','sol':'SOLUSDT','xrp':'XRPUSDT','bnb':'BNBUSDT','ada':'ADAUSDT'}

def resolve_symbol(text):
    t=text.lower()
    for k,v in ALIASES.items():
        if re.search(rf'(?<![a-z]){re.escape(k)}(?![a-z])',t): return v
    m=re.search(r'\b([a-z0-9]{2,12})\s*/?\s*usdt\b',t)
    return (m.group(1).upper()+'USDT') if m and not m.group(1).upper().endswith('USDT') else (m.group(1).upper() if m else None)

def needs_data(text):
    t=text.lower()
    return any(x in t for x in ['price','live','current','ippo','ethra','rate','rsi','trend','analyse','analysis','buy','sell','support','resistance','btc','bitcoin','eth','ethereum','usdt'])

class MarketAgent:
    async def answer(self,text):
        data='(no market data needed)'
        sym=resolve_symbol(text)
        if needs_data(text) and sym:
            try:
                q=await mudrex_service.latest_price(sym)
                hist=await mudrex_service.get_klines([sym],'5m',60)
                rows=hist.get(sym,[])
                data=f"Mudrex symbol={sym}; current/last price={q['price']}; source={q['source']}; 5m candles available={len(rows)}."
                logger.info('[MUDREX_TOOL] supplied %s market data to AI',sym)
            except Exception as e:
                data=f'Mudrex market data unavailable for {sym}: {e}'
                logger.warning('[MUDREX_TOOL] data failed for %s: %s',sym,e)
        system=("You are STAFF BOT, a respectful personal crypto-market assistant. Reply in the user's Malayalam/Manglish/English style. "
                "You are connected to Mudrex PUBLIC READ-ONLY market data. When MUDREX DATA is supplied, use it as the source of truth and never invent a live price. "
                "This bot generates paper signals only and has no order placement. Do not promise profits. Keep answers concise but useful.")
        return await ai_router.answer(f'USER: {text}\n\nMUDREX DATA:\n{data}\n\nAnswer directly.',system)
market_agent=MarketAgent()
