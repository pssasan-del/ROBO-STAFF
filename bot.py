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
                [{"text": "📊 Market Status"}, {"text": "🔍 Scan Now"}],
                [{"text": "▶ Start Scanner"}, {"text": "⏸ Pause"}, {"text": "⛔ Stop"}],
                [{"text": "📋 Active Scanners"}, {"text": "💾 Saved Strategies"}]
            ],
            "resize_keyboard": True,
            "is_persistent": True
        }

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
        if lower_t in ("/start", "help", "hi", "hello", "namaskaram"):
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
            return f"⛔ *All Scanners Stopped*\nSuccessfully stopped {stopped_count} active scanner(s).", self.get_main_keyboard()

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
            if not active:
                return "📋 *No scanners currently active.*\nUse *▶ Start Scanner* or describe a strategy to start scanning!", self.get_main_keyboard()
            
            msg = f"📋 *ACTIVE SCANNERS ({len(active)}):*\n\n"
            for idx, s in enumerate(active, 1):
                uptime_mins = int((time.time() - (s.started_at or time.time())) / 60)
                msg += (
                    f"*{idx}. {s.strategy_name}*\n"
                    f"• Status: `{s.status}` | TF: {s.timeframe}M | Pool: {s.universe}\n"
                    f"• Scans: {s.total_scans} | Alerts: {s.alert_count} | Uptime: {uptime_mins}m\n\n"
                )
            return msg, self.get_main_keyboard()

        if lower_t in ("💾 saved strategies", "saved strategies", "strategies", "saved strategies kaanikk"):
            strategies = storage.list_strategies()
            if not strategies:
                return "💾 *No strategies saved yet.*\nTry saying: _\"EMA 20 EMA 50 cross strategy save cheyyu\"_", self.get_main_keyboard()
            
            msg = f"💾 *SAVED STRATEGIES ({len(strategies)}):*\n\n"
            for idx, st in enumerate(strategies, 1):
                msg += f"*{idx}. {st.name}* ({st.timeframe}M - {st.universe})\n_{st.description or 'No description'}_\n\n"
            return msg, self.get_main_keyboard()

        # 3. Handle Anaphoric / Contextual references (e.g. "athinte RSI ethra?")
        if any(w in lower_t for w in ["athinte", "athil", "its", "that stock", "athinte rsi", "athinte price"]) and last_symbol:
            target_symbol = last_symbol
        else:
            # Check if text contains a specific stock symbol
            target_symbol = None
            for candidate in ["RELIANCE", "TCS", "HDFCBANK", "INFY", "TATAMOTORS", "SBIN", "ICICIBANK", "BHARTIARTL", "TITAN", "ZOMATO", "MARUTI", "LT", "ITC", "SUNPHARMA"]:
                if candidate.lower() in lower_t:
                    target_symbol = candidate
                    break

        # 4. Stock Analysis Request (e.g. "RELIANCE analyse cheyyu", "Tata Motors 5 minute chart analyse cheyyu")
        if target_symbol and any(w in lower_t for w in ["analyse", "analysis", "chart", "enganeya", "rsi", "ethra", "check", "price"]):
            storage.update_user_context(user_id, last_symbol=target_symbol)
            quote = fyers_service.get_quote(target_symbol)
            candles = fyers_service.get_history(target_symbol, timeframe="5", days_back=5)
            
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
            explanation = ai_router.generate_response(
                prompt=f"The user asked: '{text}'\n\nHere is the real computed market data:\n{analysis_context}\n\n"
                       f"Explain this stock's current technical structure clearly and concisely to the user in a helpful, conversational tone (supporting Malayalam/Manglish if requested). Include specific indicator values.",
                system_instruction="You are a professional Indian stock market AI assistant. Always ground your answers strictly in the provided mathematical metrics. Never invent prices."
            )

            response = (
                f"📈 *{target_symbol} TECHNICAL ANALYSIS*\n"
                f"💰 *LTP:* ₹{quote.ltp:,.2f} ({quote.change_pct:+.2f}%)\n"
                f"📊 *5M RSI:* `{rsi_val:.1f}` | *VWAP:* `₹{vwap_val:.2f}`\n\n"
                f"{explanation}"
            )
            return response, self.get_main_keyboard()

        # 5. Continuous Scanning Request (e.g. "Ee strategy continuous scan cheyyu", "start scanning")
        if any(w in lower_t for w in ["continuous scan", "continuously scan", "start scanner", "start scan", "scan continuously"]):
            if not settings.MOCK_MARKET_DATA and not fyers_service.is_healthy():
                raise MarketDataUnavailable("FYERS live session is not connected. Scanner was not started.")
            strat = StrategyParser.parse_strategy(text)
            state = scanner.add_scanner(strat)
            msg = (
                f"🚀 *Continuous Scanner Started!*\n\n"
                f"🎯 *Strategy:* {strat.name}\n"
                f"⏱ *Timeframe:* {strat.timeframe}M | *Universe:* {strat.universe}\n"
                f"📋 *Rules:* {len(strat.conditions)} condition(s) verified\n\n"
                f"🔔 The bot will monitor in the background and send instant Telegram alerts on matches!\n"
                f"⏱ *Session Auto-Stop:* Set to 6 hours for safety."
            )
            return msg, self.get_main_keyboard()

        # 6. One-Time Scan Request (e.g. "Open high stocks search cheyyu", "Scan now", "RSI 30 below scan")
        if any(w in lower_t for w in ["scan", "search", "find", "kaanikk", "screen", "search cheyyu", "scan cheyyu"]):
            if not settings.MOCK_MARKET_DATA and not fyers_service.is_healthy():
                raise MarketDataUnavailable("FYERS live session is not connected. Scan was not run.")
            strat = StrategyParser.parse_strategy(text)
            matches = scanner.scan_single_strategy(strat)
            
            if not matches:
                return f"🔍 *Scan Results for '{strat.name}':*\n\nNo stocks in {strat.universe} currently meet all conditions.", self.get_main_keyboard()
            
            msg = f"🔍 *Scan Results for '{strat.name}' ({len(matches)} matches in {strat.universe}):*\n\n"
            for m in matches[:8]:
                msg += f"• *{m.company_name}*: ₹{m.ltp:,.2f}\n"
            
            if len(matches) > 8:
                msg += f"\n_...and {len(matches)-8} more stocks._"
            
            msg += "\n\n💡 Say _\"Ee strategy continuous scan cheyyu\"_ to keep scanning in the background."
            return msg, self.get_main_keyboard()

        # 7. General AI Market Educational Question (e.g. "PE ratio entha?", "VWAP explain cheyyu")
        ai_answer = ai_router.generate_response(
            prompt=f"User question: {text}",
            system_instruction="You are an expert Indian stock market educator. Answer conversationally in clear, simple terms. If the user asks in Malayalam or Manglish, reply in friendly Manglish/Malayalam."
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
