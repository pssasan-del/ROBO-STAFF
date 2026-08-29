import asyncio
import time
from typing import Optional, Dict, Any

import httpx

from ai_router import ai_router
from builtin_strategies import stock_strategy
from config import settings, logger
from errors import MarketDataUnavailable, StrategyParseError, UnsupportedUniverseError
from market_agent import market_agent
from nifty_option_engine import nifty_option_scanner
from scanner import scanner
from storage import storage
from strategy_parser import StrategyParser

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


class TelegramBot:
    """Telegram-only FYERS AI assistant. All free-text conversation is answered by Gemini/Groq."""

    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.client = httpx.AsyncClient(timeout=25.0)
        self._is_running = False
        self._last_update_id = 0

    def is_authorized(self, user_id: int) -> bool:
        return settings.is_user_authorized(user_id)

    def get_main_keyboard(self) -> Dict[str, Any]:
        return {
            "keyboard": [
                [{"text": "📊 Market Status"}, {"text": "💾 Saved Strategies"}],
                [{"text": "🎯 NIFTY Options"}, {"text": "📋 Active Scanners"}],
                [{"text": "⛔ Stop All"}],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def get_saved_strategy_keyboard(self) -> Dict[str, Any]:
        # Exactly the 4 supplied stock strategies + 1 mixed 44 scanner.
        return {
            "keyboard": [
                [{"text": "▶ 200% CALL"}, {"text": "▶ 200% PUT"}],
                [{"text": "▶ ORB CALL"}, {"text": "▶ ORB PUT"}],
                [{"text": "▶ MIXED 44"}, {"text": "⛔ Stock Strategies"}],
                [{"text": "📋 Active Scanners"}, {"text": "⬅ Main"}],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def get_nifty_option_keyboard(self) -> Dict[str, Any]:
        return {
            "keyboard": [
                [{"text": "▶ NIFTY Momentum"}, {"text": "⛔ Momentum"}],
                [{"text": "▶ NIFTY Fib Reversal"}, {"text": "⛔ Fib Reversal"}],
                [{"text": "📋 Active Scanners"}, {"text": "⬅ Main"}],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
        }

    async def send_message(self, chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None, parse_mode: str = "Markdown") -> bool:
        if not self.token:
            logger.warning("[TELEGRAM] No bot token configured")
            return False
        url = f"{TELEGRAM_API_BASE}{self.token}/sendMessage"
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            resp = await self.client.post(url, json=payload)
            if resp.status_code != 200:
                payload.pop("parse_mode", None)
                await self.client.post(url, json=payload)
            return True
        except Exception as e:
            logger.error(f"[TELEGRAM] send failed: {e}")
            return False

    async def send_typing(self, chat_id: int):
        if not self.token:
            return
        try:
            await self.client.post(f"{TELEGRAM_API_BASE}{self.token}/sendChatAction", json={"chat_id": chat_id, "action": "typing"})
        except Exception:
            pass

    async def handle_update(self, update: Dict[str, Any]):
        message = update.get("message")
        if not message:
            return
        user_id = (message.get("from") or {}).get("id")
        chat_id = (message.get("chat") or {}).get("id")
        text = (message.get("text") or "").strip()
        if not text or not user_id or not chat_id:
            return
        if not self.is_authorized(user_id):
            await self.send_message(chat_id, "⛔ Access denied. This is a private personal bot.")
            return

        logger.info(f"[TELEGRAM] User {user_id} sent: {text}")
        await self.send_typing(chat_id)
        try:
            response_text, keyboard = await asyncio.wait_for(
                self.process_user_message(str(user_id), text), timeout=28.0
            )
        except asyncio.TimeoutError:
            logger.error("[TELEGRAM] Request hard-timeout after 28s")
            response_text, keyboard = "⚠️ The request took too long. Please try once more; the scanner remains unaffected.", self.get_main_keyboard()
        except (StrategyParseError, UnsupportedUniverseError, MarketDataUnavailable) as e:
            response_text, keyboard = f"⚠️ {e}", self.get_main_keyboard()
        except Exception as e:
            logger.exception(f"[TELEGRAM] Request failed safely: {e}")
            response_text, keyboard = "⚠️ Request could not be completed right now. Please try again.", self.get_main_keyboard()
        await self.send_message(chat_id, response_text, keyboard)

    async def process_user_message(self, user_id: str, text: str):
        t = text.lower().strip()

        if t in ("/start", "help"):
            return (
                "👋 *FYERS AI Market Bot*\n\n"
                "Ask anything normally in Malayalam, Manglish or English. Gemini answers the conversation; when market facts are needed the app supplies read-only FYERS data.\n\n"
                "Saved scanners run independently without AI on every scan. No auto-trading or order placement.",
                self.get_main_keyboard(),
            )

        if t in ("⬅ main", "main"):
            return "🏠 Main controls", self.get_main_keyboard()

        if t in ("💾 saved strategies", "saved strategies", "strategies"):
            return (
                "💾 *STOCK STRATEGIES*\n\n"
                "1. 200% CALL\n2. 200% PUT\n3. ORB CALL\n4. ORB PUT\n5. MIXED 44 — 22 Midcap + 22 Smallcap\n\n"
                "START makes the deterministic Python/FYERS scanner run. AI is not called for each scan; Telegram alerts are automatic on a match.",
                self.get_saved_strategy_keyboard(),
            )

        if t in ("🎯 nifty options", "nifty options"):
            return (
                "🎯 *NIFTY OPTION SIGNAL ENGINES*\n\n"
                "Momentum: Fibonacci Pivot + EMA20/50 + VWAP + Williams %R + ADX + OI profile.\n"
                "Fib Reversal: Fib S/R + Williams %R + EMA9 + ADX + OI confirmation.\n\n"
                "Signals/alerts only — no order execution.",
                self.get_nifty_option_keyboard(),
            )

        if t in ("⛔ stop all", "stop all", "stop", "all scanner stop"):
            n = scanner.stop_all()
            opt_n = len(nifty_option_scanner.status())
            nifty_option_scanner.stop()
            return f"⛔ All scanners stopped. Stock: {n}, NIFTY option: {opt_n}.", self.get_main_keyboard()

        if t in ("📋 active scanners", "active scanners", "scanner status"):
            active = scanner.get_active_scanners()
            option_active = nifty_option_scanner.status()
            if not active and not option_active:
                return "📋 No scanners are active.", self.get_main_keyboard()
            lines = [f"📋 *ACTIVE SCANNERS ({len(active)+len(option_active)})*"]
            for s in active:
                lines.append(f"• {s.strategy_name} — {s.status} | {s.universe} | {s.timeframe}M | Alerts {s.alert_count}")
            for sid in option_active:
                name = "NIFTY Momentum Pro" if sid == "nifty_momentum_v1" else "NIFTY Fib Reversal Pro"
                lines.append(f"• {name} — RUNNING")
            return "\n".join(lines), self.get_main_keyboard()

        builtin = {
            "▶ 200% call": "sure_call", "▶ 200% put": "put",
            "▶ orb call": "orb_call", "▶ orb put": "orb_put", "▶ mixed 44": "mixed44",
        }
        if t in builtin:
            strat = stock_strategy(builtin[t])
            scanner.add_scanner(strat)
            return f"▶️ *{strat.name} started*\n{strat.universe} | {strat.timeframe}M | alert mode ON.", self.get_saved_strategy_keyboard()

        if t == "⛔ stock strategies":
            stopped = 0
            for sid in ["builtin_sure_call", "builtin_200_put", "builtin_orb_call", "builtin_orb_put", "builtin_mixed44"]:
                stopped += 1 if scanner.stop_scanner(sid) else 0
            return f"⛔ Stock strategy scanners stopped: {stopped}", self.get_saved_strategy_keyboard()

        if t in ("▶ nifty momentum", "start nifty momentum", "nifty momentum start"):
            nifty_option_scanner.start("nifty_momentum_v1")
            return "▶️ NIFTY Momentum Pro started. FYERS/OI scanning is ON.", self.get_nifty_option_keyboard()
        if t in ("⛔ momentum", "stop nifty momentum"):
            nifty_option_scanner.stop("nifty_momentum_v1")
            return "⛔ NIFTY Momentum Pro stopped.", self.get_nifty_option_keyboard()
        if t in ("▶ nifty fib reversal", "start nifty fib reversal"):
            nifty_option_scanner.start("nifty_fib_reversal_v1")
            return "▶️ NIFTY Fib Reversal Pro started. FYERS/OI scanning is ON.", self.get_nifty_option_keyboard()
        if t in ("⛔ fib reversal", "stop nifty fib reversal"):
            nifty_option_scanner.stop("nifty_fib_reversal_v1")
            return "⛔ NIFTY Fib Reversal Pro stopped.", self.get_nifty_option_keyboard()

        # Custom strategy: Gemini parses once, Python/FYERS scans thereafter.
        if market_agent._is_strategy_request(text):
            strategy = await asyncio.to_thread(StrategyParser.parse_strategy, text)
            strategy_id = storage.save_strategy(strategy)
            strategy.id = strategy_id
            storage.update_user_context(user_id, last_strategy_id=strategy_id, new_message={"role": "user", "content": text})
            scanner.add_scanner(strategy)
            explain = await ai_router.generate_response_async(
                prompt=f"User strategy: {text}\nParsed deterministic strategy: {strategy.model_dump_json()}\nTell the user briefly that it is validated and now scanning until stopped. Do not claim a match yet.",
                system_instruction="Reply respectfully in the user's Malayalam/Manglish/English style. This is read-only signal scanning; no auto-trading."
            )
            return explain, self.get_main_keyboard()

        # Everything else: Gemini final answer, enriched by FYERS when the question needs market data.
        answer = await market_agent.answer(user_id, text)
        return answer, self.get_main_keyboard()

    async def _alert_to_allowed_users(self, text: str):
        for uid in settings.allowed_user_ids():
            await self.send_message(uid, text, self.get_main_keyboard())

    async def poll_updates(self):
        if not self.token:
            logger.warning("[TELEGRAM] Bot token missing; polling disabled")
            return
        self._is_running = True
        logger.info("[TELEGRAM] Connected & polling for updates...")
        while self._is_running:
            try:
                url = f"{TELEGRAM_API_BASE}{self.token}/getUpdates"
                resp = await self.client.get(url, params={"offset": self._last_update_id + 1, "timeout": 15}, timeout=20.0)
                if resp.status_code == 409:
                    logger.warning("[TELEGRAM] 409 polling conflict during deploy overlap; retrying")
                    await asyncio.sleep(3)
                    continue
                payload = resp.json()
                if payload.get("ok"):
                    for update in payload.get("result", []):
                        self._last_update_id = max(self._last_update_id, update.get("update_id", 0))
                        # Do not block polling while AI/FYERS handles one message.
                        asyncio.create_task(self.handle_update(update))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TELEGRAM] Polling error: {e}")
                await asyncio.sleep(2)

    async def close(self):
        self._is_running = False
        await self.client.aclose()


telegram_bot = TelegramBot()
scanner.set_alert_callback(telegram_bot._alert_to_allowed_users)
nifty_option_scanner.set_alert_callback(telegram_bot._alert_to_allowed_users)
