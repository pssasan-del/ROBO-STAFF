import re
from datetime import datetime, timedelta, timezone

from ai_router import ai_router
from mudrex_service import mudrex_service
from delta_options_service import delta_options_service
from config import logger

ALIASES = {
    'bitcoin': 'BTCUSDT', 'bit coin': 'BTCUSDT', 'btc': 'BTCUSDT',
    'ethereum': 'ETHUSDT', 'etherium': 'ETHUSDT', 'ether': 'ETHUSDT', 'eth': 'ETHUSDT',
    'solana': 'SOLUSDT', 'sol': 'SOLUSDT', 'xrp': 'XRPUSDT', 'ripple': 'XRPUSDT',
    'bnb': 'BNBUSDT', 'ada': 'ADAUSDT', 'cardano': 'ADAUSDT',
}
PRICE_WORDS = ('price','current','live','ltp','rate','premium','ethra','etra','ippo','ഇപ്പോൾ','എത്ര')
ANALYSIS_WORDS = ('rsi','trend','analyse','analysis','buy','sell','support','resistance','signal','entry','target','stop loss','sl','technical')
OPTION_WORDS = (' ce',' pe','call','put','option','options','strike','premium')

MONTHS = {
    'jan':1,'january':1,'feb':2,'february':2,'mar':3,'march':3,'apr':4,'april':4,'may':5,'jun':6,'june':6,
    'jul':7,'july':7,'aug':8,'august':8,'sep':9,'sept':9,'september':9,'oct':10,'october':10,'nov':11,'november':11,'dec':12,'december':12,
}
IST = timezone(timedelta(hours=5, minutes=30))


def _normalized(text: str) -> str:
    t=text.lower().strip()
    t=re.sub(r'\bbit\s+coin\b','bitcoin',t); t=re.sub(r'\beth\s+ereum\b','ethereum',t)
    return re.sub(r'\s+',' ',t)


def resolve_symbol(text: str):
    t=_normalized(text)
    for name in sorted(ALIASES,key=len,reverse=True):
        if re.search(rf'(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])',t): return ALIASES[name]
    m=re.search(r'\b([a-z0-9]{2,12})\s*/?\s*usdt\b',t)
    if m:
        base=m.group(1).upper(); return base if base.endswith('USDT') else base+'USDT'
    return None


def is_price_question(text:str)->bool:
    t=_normalized(text); return any(w in t for w in PRICE_WORDS)


def is_analysis_question(text:str)->bool:
    t=_normalized(text); return any(w in t for w in ANALYSIS_WORDS)


def is_option_question(text:str)->bool:
    t=' '+_normalized(text)+' '
    return any(w in t for w in OPTION_WORDS) or bool(re.search(r'\b\d{3,7}(?:\.\d+)?\s*(?:ce|pe)\b',t))


def extract_strike(text:str):
    t=_normalized(text)
    # Prefer a number attached to CE/PE/call/put.
    m=re.search(r'\b([0-9]{3,7}(?:\.[0-9]+)?)\s*(?:ce|pe|call|put)\b',t)
    if m: return float(m.group(1))
    # In an option-intent sentence, use the plausible large strike number.
    if is_option_question(t):
        nums=[float(x) for x in re.findall(r'\b([0-9]{3,7}(?:\.[0-9]+)?)\b',t)]
        return nums[0] if nums else None
    return None


def extract_expiry(text:str):
    t=_normalized(text)
    # Explicit full dates.
    for pat, fmt in [
        (r'\b(\d{1,2}-\d{1,2}-\d{4})\b','%d-%m-%Y'),
        (r'\b(\d{4}-\d{1,2}-\d{1,2})\b','%Y-%m-%d'),
        (r'\b(\d{1,2}/\d{1,2}/\d{4})\b','%d/%m/%Y'),
    ]:
        m=re.search(pat,t)
        if m:
            try: return datetime.strptime(m.group(1),fmt).date().strftime('%d-%m-%Y')
            except ValueError: pass
    # "29 aug" / "29 august 2026". If year omitted, use next occurrence.
    m=re.search(r'\b(\d{1,2})\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+(\d{4}))?\b',t)
    if m:
        day=int(m.group(1)); month=MONTHS[m.group(2)]; now=datetime.now(IST).date(); year=int(m.group(3)) if m.group(3) else now.year
        try:
            d=datetime(year,month,day).date()
            if not m.group(3) and d < now: d=datetime(year+1,month,day).date()
            return d.strftime('%d-%m-%Y')
        except ValueError: pass
    return None


class MarketAgent:
    async def answer(self,text:str):
        sym=resolve_symbol(text); wants_price=is_price_question(text); wants_analysis=is_analysis_question(text); wants_option=is_option_question(text)
        strike=extract_strike(text) if wants_option else None
        expiry=extract_expiry(text) if wants_option else None
        market_data='(no market data needed)'

        # Options route FIRST: Delta public options chain. Mudrex remains the live/candle source.
        if wants_option and sym in {'BTCUSDT','ETHUSDT'} and strike is not None:
            underlying='BTC' if sym=='BTCUSDT' else 'ETH'
            try:
                snap=await delta_options_service.get_strike_snapshot(underlying,strike,expiry)
                market_data=(
                    f'DELTA OPTIONS DATA: underlying={snap["underlying"]}; requested strike={snap["requested_strike"]}; '
                    f'selected strike={snap["selected_strike"]}; exact strike listed={snap["strike_exact"]}; expiry={snap["expiry"]}; '
                    f'spot={snap.get("spot_price")}; CE={snap.get("ce")}; PE={snap.get("pe")}; source={snap["source"]}. '
                    'Use CE as Call and PE as Put. If exact strike listed=false, clearly say the requested strike is not listed and that the shown rate is the nearest listed strike. '
                    'If CE or PE is missing, say that side was not returned; never invent it.'
                )
                logger.info('[DELTA_TOOL] supplied %s strike=%s options to AI expiry=%s',underlying,strike,snap.get('expiry'))
            except Exception as exc:
                market_data=f'DELTA OPTIONS DATA unavailable for {underlying} strike {strike}: {exc}'
                logger.warning('[DELTA_TOOL] options failed %s strike=%s: %s',underlying,strike,exc)
        elif wants_option and sym in {'BTCUSDT','ETHUSDT'} and strike is None:
            market_data='Options request detected for BTC/ETH, but strike price is missing. Ask for the strike (for example BTC 77500 CE/PE).'
        elif sym and (wants_price or wants_analysis):
            try:
                q=await mudrex_service.latest_price(sym)
                market_data=f'MUDREX DATA: symbol={sym}; current/last price={q["price"]}; source={q["source"]}; timestamp={q.get("timestamp")}. '
                logger.info('[MUDREX_TOOL] supplied %s LIVE PRICE to AI price=%s source=%s',sym,q.get('price'),q.get('source'))
                if wants_analysis:
                    try:
                        hist=await mudrex_service.get_klines([sym],'5m',60); rows=hist.get(sym,[])
                        market_data+=f'5m candles available={len(rows)}.'; logger.info('[MUDREX_TOOL] supplied %s 5m history candles=%s',sym,len(rows))
                    except Exception as hist_exc:
                        market_data+=f'5m historical candles temporarily unavailable: {hist_exc}.'; logger.warning('[MUDREX_TOOL] history unavailable for %s: %s',sym,hist_exc)
            except Exception as exc:
                market_data=f'MUDREX DATA unavailable for {sym}: {exc}'; logger.warning('[MUDREX_TOOL] live data failed for %s: %s',sym,exc)
        elif (wants_price or wants_analysis or wants_option) and not sym:
            logger.info('[MARKET_TOOL] market intent detected but symbol unresolved: %s',text)
            market_data='Market-data question detected, but no supported crypto symbol was identified. Ask which coin; do not claim the data providers are unavailable.'

        system=(
            "You are STAFF BOT, a respectful personal crypto-market assistant. Reply in the user's Malayalam/Manglish/English style. "
            "Mudrex PUBLIC read-only data is used for crypto live prices/candles. Delta Exchange India PUBLIC read-only data is used for BTC/ETH options. "
            "When supplied market data includes values, use them as the source of truth and answer directly. For option questions, show expiry, strike, CE/Call premium and PE/Put premium when present; optionally include bid/ask, OI, IV/Greeks briefly if useful. "
            "Do not claim you cannot access options if DELTA OPTIONS DATA is supplied. Never invent prices or Greeks. "
            "This bot generates paper signals/market information only and has no order placement. Do not promise profits. Keep answers concise and useful."
        )
        return await ai_router.answer(f'USER: {text}\n\nMARKET DATA:\n{market_data}\n\nAnswer directly.',system)

market_agent=MarketAgent()
