# FYERS AI MARKET BOT 🚀

A production-ready personal Telegram AI assistant and Indian stock market strategy scanner powered by **Python 3.11**, **FYERS API**, **Google Gemini** (Primary AI), and **Groq** (Automatic Fallback AI).

---

## 🔒 ZERO AUTO-TRADING SAFETY GUARANTEE

This application is strictly designed for:
* Market data retrieval (quotes, candle history, market breadth)
* Natural language strategy parsing
* Deterministic mathematical scanning on historical/intraday candles
* Telegram alerts & conversational educational explanations

**IMPORTANT:** The application **NEVER** places, modifies, cancels, or squares-off any broker order. There is **ZERO** trade execution code in this entire repository.

---

## 🏗 ARCHITECTURE OVERVIEW

```
USER MESSAGE (Malayalam / Manglish / English)
   │
   ▼
AI STRATEGY PARSER (Gemini 2.5 Flash / Groq Fallback)
   │
   ▼
VALIDATED PYDANTIC MODEL (Strict Deterministic Schema)
   │
   ▼
PYTHON STRATEGY ENGINE (pandas / numpy Technical Indicators)
   │
   ▼
FYERS MARKET DATA (or EXPLICIT MOCK mode only)
   │
   ▼
MATCH DEDUPLICATION & COOLDOWN (SQLite Storage)
   │
   ▼
TELEGRAM ALERT / CONVERSATIONAL RESPONSE
```

---

## 📂 PROJECT STRUCTURE

```
.
├── config.py             # Settings, environment configuration, and authorization checks
├── models.py             # Pydantic schemas for strategies, conditions, quotes, alerts
├── indicators.py         # Deterministic calculations (EMA, SMA, RSI, MACD, ATR, VWAP, Bollinger)
├── symbol_universe.py    # NIFTY 50, BANK NIFTY, NIFTY 100, custom symbol resolvers
├── mock_market.py        # High-fidelity deterministic mock data engine for offline testing
├── strategy_engine.py    # Pure Python evaluation engine (AND/OR logic, condition comparisons)
├── strategy_parser.py    # AI + regex fast-path strategy parser (Malayalam/Manglish/English)
├── ai_router.py          # Dual AI provider: Google Gemini (Primary) → Groq (Automatic Fallback)
├── fyers_service.py      # FYERS REST market data client (Read-Only; never silently mocks live failures)
├── alerts.py             # Alert formatter, cooldown tracking, and deduplication
├── scanner.py            # Continuous background multi-scanner engine (6-hour auto shutoff)
├── storage.py            # SQLite persistent store for saved strategies, scanners, and alerts
├── bot.py                # Telegram bot controller & conversational assistant
├── app.py                # Minimal FastAPI health server (Render compatible) & unified runner
├── requirements.txt      # Python dependencies
├── .env.example          # Template for environment variables
├── .gitignore            # Git ignore rules (protects .env and database)
├── README.md             # Complete step-by-step setup and deployment guide
└── tests/                # 22 Pytest unit tests
    ├── test_indicators.py
    ├── test_strategy_engine.py
    ├── test_strategy_parser.py
    ├── test_scanner.py
    ├── test_alerts.py
    └── test_safety.py
```

---

## V2 SAFETY BEHAVIOR

- **No silent strategy fallback:** if AI parsing/validation fails, the scanner does not invent an EMA strategy. The bot asks the user to rephrase the rule.
- **No silent mock substitution in live mode:** if FYERS is offline or its token expires, live scans/analysis fail closed and the bot reports that market data is unavailable. Mock candles are used only when `MOCK_MARKET_DATA=true`.
- **No partial NIFTY200/NIFTY500 masquerading as full indices:** those universes are disabled until a verified constituent source is added. NIFTY50, NIFTY100, BANKNIFTY, WATCHLIST, and explicit symbols are available.
- **Reduced FYERS load:** continuous candle strategies evaluate at most once per timeframe candle bucket rather than refetching the whole universe every 30 seconds.
- **Telegram-only UI:** there is no user-facing website/dashboard. `/` and `/health` exist only so Render/other cloud hosts can keep/check the service.

## 🚀 STEP-BY-STEP SETUP GUIDE

### STEP 1: Python Installation
Ensure you have Python 3.10+ or 3.11 installed:
```bash
python3 --version
```

### STEP 2: Telegram BotFather Setup
1. Open Telegram and search for `@BotFather`.
2. Send `/newbot`.
3. Follow the prompts to choose a name and username (e.g. `MyMarketScannerBot`).
4. Copy the **API Token** provided (e.g., `7123456789:ABCdefGHIjklMNOpqrsTUVwxyz`).

### STEP 3: How to Obtain Telegram User ID
1. Search for `@userinfobot` or `@raw_data_bot` on Telegram.
2. Send `/start` to get your numeric **User ID** (e.g., `123456789`).
3. Set this as `ALLOWED_TELEGRAM_USER_ID` in your `.env`.

### STEP 4: Google Gemini API Configuration (Primary AI)
1. Go to [Google AI Studio](https://aistudio.google.com/).
2. Click **Get API key** and create a new key.
3. Set `GEMINI_API_KEY` in your `.env`.

### STEP 5: Groq API Configuration (Automatic Fallback AI)
1. Go to [Groq Console](https://console.groq.com/).
2. Create an API key under **API Keys**.
3. Set `GROQ_API_KEY` in your `.env`.

### STEP 6: FYERS Developer App Configuration
1. Login to [FYERS API Dashboard](https://myapi.fyers.in/).
2. Create a new app:
   * **App Name:** `FYERS Market Bot`
   * **Redirect URI:** `https://trade.fyers.in/api-login/redirect-uri/index.html`
3. Copy your `App ID` (Client ID) and `Secret Key`.
4. Generate your daily `FYERS_ACCESS_TOKEN` using the FYERS auth flow.

### STEP 7: Environment Setup
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in your credentials in `.env`:
```env
FYERS_CLIENT_ID=YOUR_APP_ID-100
FYERS_SECRET_KEY=YOUR_SECRET_KEY
FYERS_REDIRECT_URI=https://trade.fyers.in/api-login/redirect-uri/index.html
FYERS_ACCESS_TOKEN=YOUR_GENERATED_ACCESS_TOKEN

TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ALLOWED_TELEGRAM_USER_ID=YOUR_NUMERIC_USER_ID

GEMINI_API_KEY=YOUR_GEMINI_KEY
GEMINI_MODEL=gemini-2.5-flash

GROQ_API_KEY=YOUR_GROQ_KEY
GROQ_MODEL=llama-3.3-70b-versatile

MAX_SCANNER_SESSION_HOURS=6
ALERT_COOLDOWN_MINUTES=15
MOCK_MARKET_DATA=false
PORT=3000
```

### STEP 8: Install Dependencies
Create a virtual environment and install all packages:
```bash
python3 -m venv venv
source venv/bin/activate    # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### STEP 9: Local MOCK Mode Test (Offline / Holidays)
Run in mock mode without needing a live FYERS account:
```bash
MOCK_MARKET_DATA=true python3 app.py
```
Check health endpoint in browser:
```
http://localhost:3000/health
```

### STEP 10: FYERS Live-Data Test
With valid FYERS credentials in `.env`:
```bash
MOCK_MARKET_DATA=false python3 app.py
```

### STEP 11: Telegram Test
Send messages in Telegram to your bot:
* `"Nifty ippo engane?"`
* `"RELIANCE analyse cheyyu"`
* `"Open high stocks search cheyyu"`
* `"5 minute EMA20 above EMA50 and RSI > 55 scan cheyyu"`

### STEP 12: Scanner START/STOP Test
* `"Ee strategy continuous scan cheyyu"` (Starts 6-hour continuous scanning loop)
* `"Scanner status parayu"` (Reports active scan status)
* `"Stop all scanners"` (Stops background scanner)

### STEP 13: Run Pytest Test Suite
Execute the automated unit tests:
```bash
pytest -v
```

### STEP 14: Render Deployment
1. Push your repository to GitHub (ensure `.env` is NOT pushed).
2. Create a new **Web Service** on [Render](https://render.com/).
3. Connect your GitHub repository.
4. Set:
   * **Runtime:** `Python 3`
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`

### STEP 15: Render Environment Variables
Add the required variables under Render Dashboard -> Environment:
* `TELEGRAM_BOT_TOKEN`
* `ALLOWED_TELEGRAM_USER_ID`
* `GEMINI_API_KEY`
* `GROQ_API_KEY`
* `FYERS_CLIENT_ID`
* `FYERS_SECRET_KEY`
* `FYERS_ACCESS_TOKEN`
* `MOCK_MARKET_DATA` (`false` or `true`)
* `MAX_SCANNER_SESSION_HOURS` (`6`)
* `ALERT_COOLDOWN_MINUTES` (`15`)

### STEP 16: FYERS Token Renewal Procedure
FYERS access tokens expire daily. When the token expires:
1. Generate a new token in the FYERS portal / auth script.
2. Update `FYERS_ACCESS_TOKEN` in `.env` (locally) or in the Render Environment Variables tab.
3. Restart the service.

---

## 🧪 AUTOMATED TEST SUMMARY

The test suite includes 22 unit tests covering:
* **Indicators:** EMA, SMA, RSI (Wilder's method), MACD, VWAP, Bollinger Bands, Crossover/Crossunder, Open=High, Open=Low
* **Strategy Engine:** Deterministic rule evaluation, AND/OR logic combinations
* **AI Parser:** Natural language regex fast-paths, Pydantic schema validation
* **Scanner Lifecycle:** Add, Pause, Resume, Stop, 6-Hour Session auto-stop guard
* **Alert Deduplication:** Cooldown suppression and signature generation
* **Security & Safety:** Complete audit checking zero forbidden order methods (`place_order`, `modify_order`, `square_off`)

---

## ⚠️ KNOWN LIMITATIONS
1. **FYERS Daily Token Expiration:** FYERS requires generating a new access token every morning before market hours.
2. **Tick Precision Tolerance:** For Open=High and Open=Low strategies, a default tolerance of `0.05%` is applied to account for opening auction tick variations.
3. **Personal Single User Security:** Only Telegram messages from `ALLOWED_TELEGRAM_USER_ID` are processed to prevent unauthorized access.

## V4: NIFTY option signal engines
Two read-only NIFTY option alert engines are included under Telegram -> Saved Strategies:
- NIFTY Momentum Pro: Fibonacci pivot + EMA20/50 + VWAP + Williams %R + ADX + FYERS option-chain OI profile.
- NIFTY Fib Reversal Pro: Fib S1/S2 or R1/R2 reversal + Williams %R trigger + EMA9 + ADX + OI profile.

They generate CE_BUY / PE_BUY signal alerts only. They never place an order. FYERS option-chain data is requested from the v3 data endpoint using the existing FYERS app ID and access token.

Historical questions such as `2024 Oct 5 ITC price ethra?` use FYERS daily history first. If the requested date is a weekend/market holiday, the bot states that the previous available trading-day candle was used.

## v5 edit notes
- Gemini remains the primary conversational AI; Groq is fallback.
- FYERS is the source of live/historical market facts. Historical date questions use FYERS daily candles before AI wording.
- NIFTY strike queries such as `NIFTY 24000 PE current price` query the FYERS option chain first.
- Saved Strategies keyboard includes NIFTY Momentum, NIFTY Fib Reversal, 200% CALL, 200% PUT, ORB CALL, ORB PUT, and MIXED 44.
- MIXED 44 uses a dedicated 22 midcap + 22 smallcap pool and can be started/stopped independently.
- Saved scanners are deterministic and continue without an AI call on every scan; AI is used to parse new natural-language strategies.
- No order placement / auto trading is implemented.
