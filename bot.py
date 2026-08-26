import asyncio
import time
import json
import re
from typing import Optional, Dict, Any, List
import httpx
from config import settings, logger
from models import StrategyDefinition, ScanMatch
from symbol_universe import SymbolUniverse
from fyers_service import fyers_service
from strategy_parser import StrategyParser
from strategy_engine import StrategyEngine
from scanner import scanner
from storage import storage
from ai_router import ai_router
from alerts import AlertManager
from indicators import TechnicalIndicators
from errors import StrategyParseError, MarketDataUnavailable, UnsupportedUniverseError
from nifty_option_engine import nifty_option_scanner
import datetime

TELEGRAM_API_BASE = "https://api.telegram.org/bot"

class TelegramBot:
    """
    Production Telegram Bot for FYERS AI Market Assistant.
    Supports English, Malayalam, and Manglish natural conversation + Interactive Keyboards.
    """

    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.client = httpx.AsyncClient(timeout=30.0)
        self._is_running = False
        self._last_update_id = 0

    def is_authorized(self, user_id: int) -> bool:
        return settings.is_user_authorized(user_id)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "Markdown"
    ) -> bool:
        if not self.token:
            logger.warning("[TELEGRAM] No bot token configured, printing message locally:\n" + text)
            return False

        url = f"{TELEGRAM_API_BASE}{self.token}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            resp = await self.client.post(url, json=payload)
            if resp.status_code != 200:
                # Fallback to plain text if Markdown parsing failed
                payload.pop("parse_mode", None)
                await self.client.post(url, json=payload)
            return True
        except Exception as e:
            logger.error(f"[TELEGRAM] Error sending message to {chat_id}: {e}")
            return False

    def get_main_keyboard(self) -> Dict[str, Any]:
        return {
            "keyboard": [
                [{"text": "📊 Market Status"}, {"text": "💾 Saved Strategies"}],
                [{"text": "📋 Active Scanners"}, {"text": "⛔ Stop All"}]
            ],
            "resize_keyboard": True,
            "is_persistent": True
        }

    def get_saved_strategy_keyboard(self) -> Dict[str, Any]:
        return {
            "keyboard": [
                [{"text": "▶ NIFTY Momentum"}, {"text": "⛔ Momentum"}],
                [{"text": "▶ NIFTY Fib Reversal"}, {"text": "⛔ Fib Reversal"}],
                [{"text": "📋 Active Scanners"}, {"text": "⬅ Main"}]
            ],
            "resize_keyboard": True,
            "is_persistent": True
        }

    @staticmethod
    def _extract_date(text: str) -> Optional[str]:
        t = text.lower()
        m = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", t)
        if m:
            y, mo, d = map(int, m.groups())
            try:
                return datetime.date(y, mo, d).isoformat()
            except ValueError:
                return None
        months = {
            'jan':1,'january':1,'feb':2,'february':2,'mar':3,'march':3,'apr':4,'april':4,'may':5,'jun':6,'june':6,
            'jul':7,'july':7,'aug':8,'august':8,'sep':9,'sept':9,'september':9,'oct':10,'october':10,'nov':11,'november':11,'dec':12,'december':12
        }
        m = re.search(r"\b(20\d{2})\s+([a-z]+)\s+(\d{1,2})\b", t) or re.search(r"\b(\d{1,2})\s+([a-z]+)\s+(20\d{2})\b", t)
        if not m:
            return None
        a,b,c = m.groups()
        if len(a)==4:
            y, mon, d = int(a), months.get(b), int(c)
        else:
            d, mon, y = int(a), months.get(b), int(c)
        if not mon:
            return None
        try:
            return datetime.date(y, mon, d).isoformat()
        except ValueError:
            return None

    async def handle_update(self, update: Dict[str, Any]):
        message = update.get("message")
        if not message:
            return

        user = message.get("from", {})
        user_id = user.get("id")
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()

        if not text or not user_id or not chat_id:
            return

        # 1. Authorization Check
        if not self.is_authorized(user_id):
            logger.warning(f"[TELEGRAM] Unauthorized access attempt from user_id: {user_id}")
            await self.send_message(
                chat_id=chat_id,
                text="⛔ *Access Denied*\nThis is a private personal assistant bot. You are not authorized."
            )
            return

        logger.info(f"[TELEGRAM] User {user_id} sent: {text}")

        # 2. Process Commands / Natural Language
        try:
            response_text, keyboard = await self.process_user_message(str(user_id), text)
        except StrategyParseError as e:
            response_text, keyboard = f"⚠️ *Strategy not started*\n\n{e}", self.get_main_keyboard()
        except UnsupportedUniverseError as e:
            response_text, keyboard = f"⚠️ *Universe unavailable*\n\n{e}", self.get_main_keyboard()
        except MarketDataUnavailable as e:
            response_text, keyboard = f"📡 *FYERS data unavailable*\n\n{e}\n\nNo mock data was substituted.", self.get_main_keyboard()
        except Exception as e:
            logger.exception(f"[TELEGRAM] Request failed safely: {e}")
            response_text, keyboard = "⚠️ Request could not be completed. Please check the service logs and try again.", self.get_main_keyboard()
        await self.send_message(chat_id=chat_id, text=response_text, reply_markup=keyboard)

    async def process_user_message(self, user_id: str, text: str) -> (str, Optional[Dict[str, Any]]):
        lower_t = text.lower().strip()
        user_ctx = storage.get_user_context(user_id)
        last_symbol = user_ctx.get("last_symbol")

        # Command: /start or Help
        if lower_t in ("/start", "help"):
            msg = (
                "👋 *Namaskaram! Welcome to FYERS AI Market Bot*\n\n"
                "I am your personal AI market assistant & strategy scanner for Indian markets (NSE/BSE).\n\n"
                "🗣 *You can speak in Malayalam, Manglish, or English:*\n"
                "• _\"Nifty ippo engane?\"_\n"
                "• _\"RELIANCE analyse cheyyu\"_\n"
                "• _\"Open high stocks search cheyyu\"_\n"
                "• _\"5 minute EMA20 above EMA50 and RSI > 55 scan cheyyu\"_\n"
                "• _\"Ee strategy continuous scan cheyyu\"_\n"
                "• _\"Stop all scanners\"_\n\n"
                "🔒 *Safety Guarantee:* Zero trade execution. Read-only market intelligence."
            )
            return msg, self.get_main_keyboard()

        # 1. Market Status Overview
        if lower_t in ("📊 market status", "market status", "nifty ippo engane", "nifty engane", "market engane", "status nifty"):
            overview = fyers_service.get_market_overview()
            msg = (
                f"📊 *INDIAN MARKET OVERVIEW*\n"
                f"📡 *Mode:* `{overview.market_status}`\n\n"
                f"📈 *NIFTY 50:* ₹{overview.nifty_spot:,.2f} ({overview.nifty_change_pct:+.2f}%)\n"
                f"🏦 *BANK NIFTY:* ₹{overview.banknifty_spot:,.2f} ({overview.banknifty_change_pct:+.2f}%)\n\n"
                f"⚖️ *Market Breadth:* {overview.advances} Advances | {overview.declines} Declines\n\n"
                f"🟢 *Top Gainers:*\n"
            )
            for g in overview.top_gainers:
                msg += f"• {g['symbol']}: ₹{g['price']:,.2f} ({g['change_pct']:+.2f}%)\n"
            msg += "\n🔴 *Top Losers:*\n"
            for l in overview.top_losers:
                msg += f"• {l['symbol']}: ₹{l['price']:,.2f} ({l['change_pct']:+.2f}%)\n"
            return msg, self.get_main_keyboard()

        # 2. Scanner Control Commands (STOP, PAUSE, RESUME, STATUS)
        if lower_t in ("⛔ stop", "stop", "stop all", "stop scanner", "all scanner stop", "scanner stop cheyyu"):
            stopped_count = scanner.stop_all()
            nifty_count = len(nifty_option_scanner.status())
            nifty_option_scanner.stop()
            return f"⛔ *All Scanners Stopped*\nStopped {stopped_count} stock scanner(s) + {nifty_count} NIFTY option scanner(s).", self.get_main_keyboard()

        if lower_t in ("⏸ pause", "pause", "pause scanner"):
            active = scanner.get_active_scanners()
            if not active:
                return "ℹ️ No active scanners currently running to pause.", self.get_main_keyboard()
            for s in active:
                scanner.pause_scanner(s.strategy_id)
            return "⏸ *Active Scanners Paused*", self.get_main_keyboard()

        if lower_t in ("▶ resume", "resume", "resume scanner"):
            all_scanners = storage.get_all_scanners()
            resumed = 0
            for s in all_scanners:
                if s["status"] == "PAUSED":
                    strat = storage.get_strategy(s["strategy_id"])
                    if strat:
                        scanner.add_scanner(strat)
                        resumed += 1
            return f"▶ *Resumed {resumed} Scanner(s)*", self.get_main_keyboard()

        if lower_t in ("📋 active scanners", "active scanners", "scanner status", "scanner status parayu"):
            active = scanner.get_active_scanners()
            option_active = nifty_option_scanner.status()
            if not active and not option_active:
                return "📋 *No scanners currently active.*\nOpen Saved Strategies or describe a custom strategy in chat.", self.get_main_keyboard()
            
            msg = f"📋 *ACTIVE SCANNERS ({len(active) + len(option_active)}):*\n\n"
            for idx, s in enumerate(active, 1):
                uptime_mins = int((time.time() - (s.started_at or time.time())) / 60)
                msg += (
                    f"*{idx}. {s.strategy_name}*\n"
                    f"• Status: `{s.status}` | TF: {s.timeframe}M | Pool: {s.universe}\n"
                    f"• Scans: {s.total_scans} | Alerts: {s.alert_count} | Uptime: {uptime_mins}m\n\n"
                )
            for sid in option_active:
                name = "NIFTY Momentum Pro" if sid == "nifty_momentum_v1" else "NIFTY Fib Reversal Pro"
                msg += f"*{name}*\n• Status: `RUNNING` | FYERS option-chain OI enabled\n\n"
            return msg, self.get_main_keyboard()

        if lower_t in ("💾 saved strategies", "saved strategies", "strategies", "saved strategies kaanikk"):
            msg = (
                "💾 *SAVED / BUILT-IN STRATEGIES*\n\n"
                "*NIFTY Momentum Pro* — 5M trend setup using Fibonacci Pivot + EMA20/50 + VWAP + Williams %R + ADX + FYERS option-chain OI profile.\n\n"
                "*NIFTY Fib Reversal Pro* — Fib S1/S2 or R1/R2 reversal using Williams %R trigger + EMA9 + ADX + OI confirmation.\n\n"
                "These are signal-only scanners. No order is placed. Use the START/STOP buttons below.\n\n"
                "You can also type a completely new strategy in chat; Gemini parses it once and the normal Python scanner then runs it without repeated AI calls."
            )
            return msg, self.get_saved_strategy_keyboard()

        if lower_t in ("⬅ main", "main"):
            return "🏠 Main controls", self.get_main_keyboard()

        if lower_t in ("▶ nifty momentum", "start nifty momentum", "nifty momentum start"):
            nifty_option_scanner.start("nifty_momentum_v1")
            return "▶️ *NIFTY Momentum Pro started.*\nFYERS + option-chain OI scanner is ON. Alerts only; no trade execution.", self.get_saved_strategy_keyboard()
        if lower_t in ("⛔ momentum", "stop nifty momentum", "nifty momentum stop"):
            nifty_option_scanner.stop("nifty_momentum_v1")
            return "⛔ *NIFTY Momentum Pro stopped.*", self.get_saved_strategy_keyboard()
        if lower_t in ("▶ nifty fib reversal", "start nifty fib reversal", "nifty fib reversal start"):
            nifty_option_scanner.start("nifty_fib_reversal_v1")
            return "▶️ *NIFTY Fib Reversal Pro started.*\nFYERS + option-chain OI scanner is ON. Alerts only; no trade execution.", self.get_saved_strategy_keyboard()
        if lower_t in ("⛔ fib reversal", "stop nifty fib reversal", "nifty fib reversal stop"):
            nifty_option_scanner.stop("nifty_fib_reversal_v1")
            return "⛔ *NIFTY Fib Reversal Pro stopped.*", self.get_saved_strategy_keyboard()

        # 3. Handle Anaphoric / Contextual references (e.g. "athinte RSI ethra?")
        if any(w in lower_t for w in ["athinte", "athil", "its", "that stock", "athinte rsi", "athinte price"]) and last_symbol:
            target_symbol = last_symbol
        else:
            # Check if text contains a specific stock symbol
            target_symbol = None
            for candidate in ["RELIANCE", "TCS", "HDFCBANK", "INFY", "TATAMOTORS", "SBIN", "ICICIBANK", "BHARTIARTL", "TITAN", "ZOMATO", "MARUTI", "LT", "ITC", "SUNPHARMA", "AXISBANK", "KOTAKBANK", "HINDUNILVR", "WIPRO", "ADANIENT", "ADANIPORTS"]:
                if candidate.lower() in lower_t:
                    target_symbol = candidate
                    break
            # Follow-up such as "current price and buying pattumo" should retain the last stock.
            if not target_symbol and last_symbol and any(w in lower_t for w in ["price", "current", "buy", "buying", "vang", "status", "target", "sl", "hold", "sell", "rsi", "support", "resistance"]):
                target_symbol = last_symbol

        # Historical date lookup: FYERS history first, Gemini final wording.
        requested_date = self._extract_date(text)
        if target_symbol and requested_date:
            hist = await asyncio.to_thread(fyers_service.get_historical_daily_price, target_symbol, requested_date, True)
            context = (
                f"Requested date: {hist['requested_date']}\nTrading candle date: {hist['trading_date']}\nSymbol: {hist['symbol']}\n"
                f"Open: {hist['open']:.2f} High: {hist['high']:.2f} Low: {hist['low']:.2f} Close: {hist['close']:.2f} Volume: {hist['volume']}\n"
                f"Used previous trading day: {hist['used_previous_trading_day']}"
            )
            ans = await ai_router.generate_response_async(
                prompt=f"User asked: {text}\n\nFYERS HISTORICAL DATA:\n{context}\nAnswer directly. If requested date was a weekend/holiday, clearly say FYERS used the previous available trading day.",
                system_instruction="You are STAFF BOT connected to FYERS read-only data. Historical price facts must come only from supplied FYERS data. Reply in the user's Malayalam/Manglish/English style."
            )
            return ans, self.get_main_keyboard()

        # 4. Index live-data questions: FYERS first, AI final answer.
        index_symbol = None
        index_name = None
        if "bank nifty" in lower_t or "banknifty" in lower_t:
            index_symbol, index_name = "NSE:NIFTYBANK-INDEX", "BANK NIFTY"
        elif "nifty" in lower_t:
            index_symbol, index_name = "NSE:NIFTY50-INDEX", "NIFTY 50"

        if index_symbol and any(w in lower_t for w in ["ethra", "price", "current", "ippo", "status", "engane", "analyse", "analysis", "high", "low"]):
            quote = await asyncio.to_thread(fyers_service.get_quote, index_symbol)
            live_context = (
                f"Instrument: {index_name}\n"
                f"FYERS LTP: {quote.ltp:.2f}\n"
                f"Change: {quote.change:+.2f} ({quote.change_pct:+.2f}%)\n"
                f"Day Open: {quote.open:.2f}\nDay High: {quote.high:.2f}\nDay Low: {quote.low:.2f}\nPrevious Close: {quote.prev_close:.2f}\n"
                f"Timestamp(epoch): {quote.timestamp}"
            )
            answer = await ai_router.generate_response_async(
                prompt=f"User asked: {text}\n\nREAL FYERS DATA:\n{live_context}\n\nAnswer directly using these values.",
                system_instruction=(
                    "You are STAFF BOT inside a FYERS-connected read-only market assistant. Use only the supplied live FYERS values for current prices. "
                    "Never deny the FYERS connection. Reply in the user's Malayalam/Manglish/English style and keep it concise."
                ),
            )
            return answer, self.get_main_keyboard()

        # 5. Stock Analysis Request (e.g. "RELIANCE analyse cheyyu", "Tata Motors 5 minute chart analyse cheyyu")
        if target_symbol and any(w in lower_t for w in ["analyse", "analysis", "chart", "enganeya", "engane", "rsi", "ethra", "check", "price", "status", "buy", "buying", "vang", "hold", "sell", "target", "support", "resistance", "current"]):
            storage.update_user_context(user_id, last_symbol=target_symbol)
            quote, candles = await asyncio.gather(
                asyncio.to_thread(fyers_service.get_quote, target_symbol),
                asyncio.to_thread(fyers_service.get_history, target_symbol, "5", 5),
            )
            
            # Compute technical summary
            rsi_val = TechnicalIndicators.rsi(candles['close'], 14).iloc[-1]
            ema20 = TechnicalIndicators.ema(candles['close'], 20).iloc[-1]
            ema50 = TechnicalIndicators.ema(candles['close'], 50).iloc[-1]
            vwap_val = TechnicalIndicators.vwap(candles).iloc[-1]

            analysis_context = (
                f"Stock: {target_symbol}\n"
                f"Current LTP: ₹{quote.ltp:,.2f} ({quote.change_pct:+.2f}%)\n"
                f"Day Range: Low ₹{quote.low:,.2f} - High ₹{quote.high:,.2f}\n"
                f"5-min RSI(14): {rsi_val:.1f}\n"
                f"EMA 20: ₹{ema20:.2f} | EMA 50: ₹{ema50:.2f}\n"
                f"VWAP: ₹{vwap_val:.2f}\n"
                f"Trend: {'BULLISH (EMA20 > EMA50)' if ema20 > ema50 else 'BEARISH (EMA20 < EMA50)'}\n"
            )

            # Let AI explain it conversationally in Manglish/Malayalam/English matching user tone
            explanation = await ai_router.generate_response_async(
                prompt=f"The user asked: '{text}'\n\nHere is REAL FYERS market data computed by this bot:\n{analysis_context}\n\n"
                       f"Answer the user's actual question directly. If they ask whether buying/holding is reasonable, discuss setup, risk and what would invalidate it without promising profit. Use the user's Malayalam/Manglish/English style. Include the real values provided.",
                system_instruction=(
                    "You are the AI inside a deployed personal FYERS market assistant. The application IS connected to FYERS in read-only mode. "
                    "Never claim that this bot has no FYERS connection when real FYERS context is supplied. Ground market claims only in the supplied data; never invent live prices."
                )
            )

            response = (
                f"📈 *{target_symbol} TECHNICAL ANALYSIS*\n"
                f"💰 *LTP:* ₹{quote.ltp:,.2f} ({quote.change_pct:+.2f}%)\n"
                f"📊 *5M RSI:* `{rsi_val:.1f}` | *VWAP:* `₹{vwap_val:.2f}`\n\n"
                f"{explanation}"
            )
            return response, self.get_main_keyboard()

        # 6. Continuous Scanning Request (e.g. "Ee strategy continuous scan cheyyu", "start scanning")
        if any(w in lower_t for w in ["continuous scan", "continuously scan", "start scanner", "start scan", "scan continuously"]):
            if not settings.MOCK_MARKET_DATA and not fyers_service.is_healthy():
                raise MarketDataUnavailable("FYERS live session is not connected. Scanner was not started.")
            if lower_t in ("▶ start scanner", "start scanner") or lower_t.startswith("ee strategy"):
                last_id = user_ctx.get("last_strategy_id")
                strat = storage.get_strategy(last_id) if last_id else None
                if not strat:
                    return "ℹ️ ആദ്യം ഒരു strategy പറയൂ. Example: `5 minute RSI above 60 scan cheyyu`. അതിന് ശേഷം Start Scanner അമർത്താം.", self.get_main_keyboard()
            else:
                strat = StrategyParser.parse_strategy(text)
                storage.save_strategy(strat)
                storage.update_user_context(user_id, last_strategy_id=strat.id)
            state = scanner.add_scanner(strat)
            storage.update_user_context(user_id, last_strategy_id=strat.id)
            msg = (
                f"🚀 *Continuous Scanner Started!*\n\n"
                f"🎯 *Strategy:* {strat.name}\n"
                f"⏱ *Timeframe:* {strat.timeframe}M | *Universe:* {strat.universe}\n"
                f"📋 *Rules:* {len(strat.conditions)} condition(s) verified\n\n"
                f"🔔 The bot will monitor in the background and send instant Telegram alerts on matches!\n"
                f"⏱ *Session Auto-Stop:* {settings.MAX_SCANNER_SESSION_HOURS} hours."
            )
            return msg, self.get_main_keyboard()

        # 7. One-Time Scan Request (e.g. "Open high stocks search cheyyu", "Scan now", "RSI 30 below scan")
        if any(w in lower_t for w in ["scan", "search", "find", "kaanikk", "screen", "search cheyyu", "scan cheyyu"]):
            if not settings.MOCK_MARKET_DATA and not fyers_service.is_healthy():
                raise MarketDataUnavailable("FYERS live session is not connected. Scan was not run.")
            if lower_t in ("🔍 scan now", "scan now"):
                last_id = user_ctx.get("last_strategy_id")
                strat = storage.get_strategy(last_id) if last_id else None
                if not strat:
                    return "ℹ️ Scan Now ഉപയോഗിക്കാൻ ആദ്യം strategy പറയൂ. Example: `Open high stocks scan cheyyu`.", self.get_main_keyboard()
            else:
                strat = StrategyParser.parse_strategy(text)
                storage.save_strategy(strat)
                storage.update_user_context(user_id, last_strategy_id=strat.id)
            matches = await asyncio.to_thread(scanner.scan_single_strategy, strat)
            storage.update_user_context(user_id, last_strategy_id=strat.id)
            
            if not matches:
                return f"🔍 *Scan Results for '{strat.name}':*\n\nNo stocks in {strat.universe} currently meet all conditions.", self.get_main_keyboard()
            
            msg = f"🔍 *Scan Results for '{strat.name}' ({len(matches)} matches in {strat.universe}):*\n\n"
            for m in matches[:8]:
                msg += f"• *{m.company_name}*: ₹{m.ltp:,.2f}\n"
            
            if len(matches) > 8:
                msg += f"\n_...and {len(matches)-8} more stocks._"
            
            msg += "\n\n💡 Say _\"Ee strategy continuous scan cheyyu\"_ to keep scanning in the background."
            return msg, self.get_main_keyboard()

        # 8. General AI / conversational question (e.g. "PE ratio entha?", "VWAP explain cheyyu")
        # General conversation goes to AI. The system prompt tells the model the real app capabilities
        # so it does not incorrectly deny the FYERS connection.
        crude_note = ""
        if any(w in lower_t for w in ["crude", "crude oil", "mcx"]):
            crude_note = (
                "\nImportant live-data context: this bot is connected to FYERS, but the current router has not resolved a specific live MCX crude futures contract symbol for this request. "
                "Do not invent a crude live price. Explain that FYERS is connected and that the contract resolver must identify the active MCX contract before a live quote can be supplied."
            )
        ai_answer = await ai_router.generate_response_async(
            prompt=f"User question: {text}{crude_note}",
            system_instruction=(
                "You are STAFF BOT, the AI inside a deployed personal Indian-market assistant. The application IS connected to FYERS read-only market data and has a deterministic scanner. "
                "Never say the bot has no FYERS/broker connection. If the router has not supplied live market data for a specific question, say that live data was not supplied for that request rather than inventing it. "
                "Answer conversationally. Match Malayalam/Manglish/English. Be concise and useful."
            )
        )
        return ai_answer, self.get_main_keyboard()

    async def start_polling(self):
        """
        Long-polling loop for Telegram updates.
        """
        if not self.token:
            logger.warning("[TELEGRAM] TELEGRAM_BOT_TOKEN not provided. Telegram bot polling disabled.")
            return

        self._is_running = True
        logger.info("[TELEGRAM] Connected & polling for updates...")

        while self._is_running:
            try:
                url = f"{TELEGRAM_API_BASE}{self.token}/getUpdates?offset={self._last_update_id + 1}&timeout=15"
                resp = await self.client.get(url, timeout=20.0)
                
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok"):
                        for update in data.get("result", []):
                            self._last_update_id = update["update_id"]
                            await self.handle_update(update)
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TELEGRAM] Polling error: {e}")
                await asyncio.sleep(3.0)

    async def broadcast_alert(self, message_text: str):
        """
        Sends an alert to all allowed user IDs.
        """
        for uid in settings.allowed_user_ids():
            await self.send_message(chat_id=uid, text=message_text)

telegram_bot = TelegramBot()
