# Delta Crypto AI Bot V9 — Telegram-only BTC + ETH + Gold

Telegram-only, signal-only personal crypto market bot. **Mudrex has been removed.** Market data, historical candles and BTC/ETH/Gold options come from Delta Exchange India public read-only APIs. No trading/order methods are included.

## Architecture

**No website/frontend is included. Telegram is the only user interface.**


`Telegram -> Gemini intent/strategy parser -> Delta public market data -> deterministic Python strategy engine -> Telegram alerts`

Gemini is used when you **create/edit a strategy** and for conversational answers. Saved strategies are converted to validated JSON rules and scanned by Python without calling AI every scan.

## Features

- BTC/ETH/Gold current price from Delta public ticker/WebSocket (`BTCUSD`, `ETHUSD`, `XAUTUSD`)
- BTC/ETH/Gold historical candles from `/v2/history/candles`
- BTC/ETH/Gold CE/PE options, expiry, premium, bid/ask, OI and Greeks when Delta supplies them. Gold option discovery tries XAUT first, then PAXG.
- Strategy input by typing, screenshot, TXT, MD, JSON or PDF
- Gemini rule extraction + preview before save
- Maximum 100 saved strategies per Telegram user
- Maximum 10 active strategy scanners per Telegram user
- Start / Stop / Edit / Delete saved strategies
- Scan active strategies now
- Alert cooldown
- Signal-only; no order placement

## Deterministic rule vocabulary

Indicators include `close/open/high/low, EMA, SMA, RSI, VWAP, volume/volume SMA, ATR, highest/lowest, previous high/low, MACD, ADX/+DI/-DI, Williams %R, TRIX, Stoch RSI, Bollinger Bands, OBV, Donchian, ROC, Williams Alligator, Supertrend, Fibonacci Pivot P/R1-R3/S1-S3`.
Operators: `>, >=, <, <=, ==, cross_above, cross_below`.
Timeframes: `1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d`.

A strategy using an unsupported indicator is rejected instead of silently approximated.

## Persistent storage

Set `DATABASE_URL` to a PostgreSQL connection string for persistent saved strategies. If it is absent, V9 falls back to `data/strategies.db` SQLite. **Render free filesystem is ephemeral**, so SQLite can disappear on redeploy/restart/spindown. For real persistence, use PostgreSQL or a persistent disk.

## Render environment variables

Required:
- `TELEGRAM_BOT_TOKEN`
- `ALLOWED_TELEGRAM_USER_ID`
- `GEMINI_API_KEY`

Recommended:
- `GROQ_API_KEY` (text fallback)
- `DATABASE_URL` (persistent strategies)

Defaults are in `.env.example`. No Delta API key is required for these public read-only endpoints.

## Render start command

`uvicorn app:app --host 0.0.0.0 --port $PORT`

## Try after deploy

1. `Gold price`
2. `Gold 4200 CE and PE rate`
3. Tap **➕ Create Strategy** and send: `BTC 5m LONG: EMA20 > EMA50, RSI14 > 55, close > VWAP, volume > 1.5x average volume 20`
4. Check the preview and tap **Save Strategy**
5. Open **Saved Strategies** and tap **Start**
6. Tap **Scan Active Now**

## Safety

This repository intentionally has no `place_order`, `modify_order`, `cancel_order`, position exit or square-off functions.


## V6 recovery + Telegram photo upload
- Telegram strategy input accepts plain text, **photos/screenshots**, TXT, MD, JSON and PDF.
- Send a screenshot after tapping **Create Strategy** (or send it directly); Gemini extracts the rules and the bot shows a preview. Nothing is saved until you tap **Save Strategy**.
- `/health` exposes Delta WebSocket age/reconnect count, scanner heartbeat, active-strategy count and database mode.
- Delta WebSocket already reconnects automatically; V6 adds a periodic heartbeat log for visibility.
- Strategies marked `active=1` in PostgreSQL are automatically resumed after a Render restart/wake because the scanner reads active rows from the database on startup.
- An internal heartbeat does **not** prevent Render Free from sleeping. If Render sleeps, the bot resumes when the service wakes.

Optional env: `HEARTBEAT_SECONDS=60`.

## V7 general photo intelligence
Telegram photos outside Create/Edit Strategy are classified by Gemini Vision as strategy, option chain, position, chart, P&L/order, or other. BTC/ETH/Gold screenshots are enriched with Delta public live data when the symbol/strike is reliably extracted. Screenshot values are treated as potentially stale and missing values are never invented. Strategy screenshots still go through Preview -> explicit Save before persistence. No order execution is present.


## V9 indicator + risk engine
Added deterministic indicator support: Fibonacci Pivot P/R1-R3/S1-S3, MACD, ADX/+DI/-DI, Williams %R, Supertrend, Williams Alligator, TRIX, Stochastic RSI, Bollinger Bands, OBV, Donchian Channel, ROC, plus existing EMA/SMA/RSI/VWAP/Volume/ATR/breakout rules.
Indicator questions such as `Gold 5min Fib R1 ethra?`, `BTC Alligator 5m`, or `ETH TRIX 15m` now fetch Delta candles and calculate the requested values in Python before Gemini answers.


## Fixed risk/reward policy

- Minimum eligible R:R: **1:1.85**
- T1: **1:1.85**
- T2 default: **1:2.30**
- T3 default: **1:3.00**
- If a proposed T1 is below 1:1.85, the deterministic target helper rejects it.
- Signal-only: no place/modify/cancel/square-off order code exists.

## Gold mapping

The bot's canonical Gold live/candle symbol is **XAUTUSD**. User text aliases `gold`, `xau`, and `xaut` map to XAUTUSD. For Gold options the connector attempts **XAUT**, then **PAXG**, so it does not assume one Gold option family is always present.
