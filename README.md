# Mudrex Crypto AI Bot V1

Telegram-only crypto paper-signal bot. **No auto-trading and no order endpoints.**

## Data architecture
`Telegram -> Gemini` for casual chat. For crypto price/analysis questions: `Telegram -> Mudrex public read-only market data -> Gemini -> Telegram`.

Mudrex public market data base used by this project:
- REST: `https://trade.mudrex.com/fapi/v1/price`
- Historical OHLCV: `GET /price/kline`
- WebSocket: `wss://trade.mudrex.com/fapi/v1/price/ws/linear`
- WS ticker subscription: `ticker@5s`

The code intentionally contains **no Mudrex API secret**, wallet, leverage, position or order functions.

## Trial scope
Default symbols: BTCUSDT, ETHUSDT. Scanner uses 5m + prior daily candle: Fibonacci pivot, EMA20/50, VWAP, RSI14, volume confirmation, 20-candle breakout/breakdown, ATR stop, min R:R 1:1.85.

## Render
Build: `pip install -r requirements.txt`
Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`

Required env: `TELEGRAM_BOT_TOKEN`, `ALLOWED_TELEGRAM_USER_ID`, `GEMINI_API_KEY`. Optional: `GROQ_API_KEY`.

No Mudrex key/token/TOTP is required for this market-data-only version.


## V2 Mudrex connector fix (2026-08-29)

This build follows Mudrex public market-data v1.0.9 conventions:

- REST base: `https://trade.mudrex.com/fapi/v1/price`
- Historical endpoint: `/kline`
- REST symbols: `BTC/USDT`, `ETH/USDT`
- Mudrex interval aliases are translated automatically (`5m -> 5t`, `15m -> 15t`).
- WebSocket ticker: `ticker@5s` with assets such as `btcusdt`, `ethusdt`.
- WebSocket ticker payload arrays are parsed correctly (`data: [{s,p,mp}, ...]`).
- REST failures now log HTTP status and Mudrex response body for fast Render debugging.
- Still public/read-only and signal-only. No Mudrex API secret is required.

## V3 natural-language routing fix
- Recognizes `bit coin`, `bitcoin`, `BTC`, `BTC/USDT`, common ETH variants.
- Price-only questions fetch only the live/latest price first; they no longer fail just because 5m history is unavailable.
- 5m history is fetched only for analysis/RSI/trend/signal questions.
- Adds `[MUDREX_TOOL] supplied ... LIVE PRICE` logs so Render clearly shows the data bridge.

## V4 — Delta BTC/ETH Options connector
- Mudrex remains the BTC/ETH live-price + candle + scanner source.
- Delta Exchange India public `/v2/tickers` option-chain endpoint supplies BTC/ETH Call/Put premiums, bid/ask, OI and Greeks when returned.
- No Delta API key/secret is required for this public market-data route.
- Ask: `BTC 77500 CE and PE rate` or `ETH 2500 call put rate`.
- If no expiry is supplied, the nearest non-expired Delta expiry is selected from the returned contracts.
- If the requested strike is not listed, the bot explicitly reports the nearest listed strike rather than inventing a premium.
- This project contains no order-placement methods.
