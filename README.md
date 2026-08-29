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
