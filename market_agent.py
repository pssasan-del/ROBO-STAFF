import re
from ai_router import ai_router
from mudrex_service import mudrex_service
from config import logger

# Common names / typing variants used in Telegram chat.
ALIASES = {
    'bitcoin': 'BTCUSDT',
    'bit coin': 'BTCUSDT',
    'btc': 'BTCUSDT',
    'ethereum': 'ETHUSDT',
    'etherium': 'ETHUSDT',
    'ether': 'ETHUSDT',
    'eth': 'ETHUSDT',
    'solana': 'SOLUSDT',
    'sol': 'SOLUSDT',
    'xrp': 'XRPUSDT',
    'ripple': 'XRPUSDT',
    'bnb': 'BNBUSDT',
    'ada': 'ADAUSDT',
    'cardano': 'ADAUSDT',
}

PRICE_WORDS = (
    'price', 'current', 'live', 'ltp', 'rate', 'ethra', 'etra', 'ippo', 'ഇപ്പോൾ', 'എത്ര'
)
ANALYSIS_WORDS = (
    'rsi', 'trend', 'analyse', 'analysis', 'buy', 'sell', 'support', 'resistance',
    'signal', 'entry', 'target', 'stop loss', 'sl', 'technical'
)


def _normalized(text: str) -> str:
    t = text.lower().strip()
    # Normalize frequent split spellings without losing ordinary word boundaries.
    t = re.sub(r'\bbit\s+coin\b', 'bitcoin', t)
    t = re.sub(r'\beth\s+ereum\b', 'ethereum', t)
    return re.sub(r'\s+', ' ', t)


def resolve_symbol(text: str):
    t = _normalized(text)
    # Longer aliases first so e.g. "bitcoin" resolves before any shorter fragment.
    for name in sorted(ALIASES, key=len, reverse=True):
        if re.search(rf'(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])', t):
            return ALIASES[name]

    # BTC/USDT, BTCUSDT, BTC USDT
    m = re.search(r'\b([a-z0-9]{2,12})\s*/?\s*usdt\b', t)
    if m:
        base = m.group(1).upper()
        return base if base.endswith('USDT') else base + 'USDT'
    return None


def is_price_question(text: str) -> bool:
    t = _normalized(text)
    return any(word in t for word in PRICE_WORDS)


def is_analysis_question(text: str) -> bool:
    t = _normalized(text)
    return any(word in t for word in ANALYSIS_WORDS)


class MarketAgent:
    async def answer(self, text: str):
        sym = resolve_symbol(text)
        wants_price = is_price_question(text)
        wants_analysis = is_analysis_question(text)
        market_data = '(no market data needed)'

        if sym and (wants_price or wants_analysis):
            try:
                # Price-only questions should not depend on the candle endpoint.
                # This keeps a valid WS/1m price answer working even if 5m history
                # is temporarily unavailable.
                q = await mudrex_service.latest_price(sym)
                market_data = (
                    f'Mudrex symbol={sym}; current/last price={q["price"]}; '
                    f'source={q["source"]}; timestamp={q.get("timestamp")}. '
                )
                logger.info('[MUDREX_TOOL] supplied %s LIVE PRICE to AI price=%s source=%s',
                            sym, q.get('price'), q.get('source'))

                if wants_analysis:
                    try:
                        hist = await mudrex_service.get_klines([sym], '5m', 60)
                        rows = hist.get(sym, [])
                        market_data += f'5m candles available={len(rows)}.'
                        logger.info('[MUDREX_TOOL] supplied %s 5m history candles=%s', sym, len(rows))
                    except Exception as hist_exc:
                        # Do not throw away a valid live price just because history failed.
                        market_data += f'5m historical candles temporarily unavailable: {hist_exc}.'
                        logger.warning('[MUDREX_TOOL] history unavailable for %s: %s', sym, hist_exc)
            except Exception as exc:
                market_data = f'Mudrex market data unavailable for {sym}: {exc}'
                logger.warning('[MUDREX_TOOL] live data failed for %s: %s', sym, exc)
        elif (wants_price or wants_analysis) and not sym:
            logger.info('[MUDREX_TOOL] market intent detected but symbol unresolved: %s', text)
            market_data = (
                'Market-data question detected, but no supported crypto symbol was identified. '
                'Ask the user which coin; do not claim that Mudrex itself is unavailable.'
            )

        system = (
            "You are STAFF BOT, a respectful personal crypto-market assistant. "
            "Reply in the user's Malayalam/Manglish/English style. "
            "You are connected to Mudrex PUBLIC READ-ONLY market data. "
            "When MUDREX DATA includes a price, use it as the source of truth and state the price directly. "
            "Never say Mudrex is unavailable unless MUDREX DATA explicitly says it is unavailable. "
            "If the symbol is unresolved, ask which coin instead. "
            "This bot generates paper signals only and has no order placement. "
            "Do not promise profits. Keep answers concise and useful."
        )
        return await ai_router.answer(
            f'USER: {text}\n\nMUDREX DATA:\n{market_data}\n\nAnswer directly.',
            system,
        )


market_agent = MarketAgent()
