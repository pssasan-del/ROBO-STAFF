import asyncio
import datetime
import json
import re
from typing import Any, Dict, Optional, Tuple

from ai_router import ai_router
from config import logger
from errors import MarketDataUnavailable
from fyers_service import fyers_service
from indicators import TechnicalIndicators
from storage import storage
from symbol_universe import SymbolUniverse


class MarketAgent:
    """Gemini-first conversational layer backed by read-only FYERS data.

    Every conversational answer is written by Gemini (Groq only on Gemini failure).
    Deterministic Python only resolves obvious market entities and fetches facts so the
    model never invents current/historical prices.
    """

    STOCK_ALIASES = {
        "reliance": "RELIANCE", "ril": "RELIANCE", "tcs": "TCS", "itc": "ITC",
        "hdfc bank": "HDFCBANK", "hdfcbank": "HDFCBANK", "icici bank": "ICICIBANK",
        "icicibank": "ICICIBANK", "infosys": "INFY", "infy": "INFY", "sbin": "SBIN",
        "sbi": "SBIN", "tata motors": "TATAMOTORS", "tatamotors": "TATAMOTORS",
        "airtel": "BHARTIARTL", "bharti airtel": "BHARTIARTL", "titan": "TITAN",
        "maruti": "MARUTI", "l&t": "LT", "lt": "LT", "wipro": "WIPRO",
        "axis bank": "AXISBANK", "kotak bank": "KOTAKBANK", "sun pharma": "SUNPHARMA",
        "zomato": "ETERNAL", "eternal": "ETERNAL",
    }

    INDEX_ALIASES = {
        "bank nifty": "NSE:NIFTYBANK-INDEX",
        "banknifty": "NSE:NIFTYBANK-INDEX",
        "nifty 50": "NSE:NIFTY50-INDEX",
        "nifty": "NSE:NIFTY50-INDEX",
        "sensex": "BSE:SENSEX-INDEX",
        "finnifty": "NSE:FINNIFTY-INDEX",
        "midcap nifty": "NSE:MIDCPNIFTY-INDEX",
    }

    MONTHS = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
        "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    }

    @classmethod
    def _extract_date(cls, text: str) -> Optional[str]:
        t = text.lower()
        m = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", t)
        if m:
            y, mo, d = map(int, m.groups())
            try:
                return datetime.date(y, mo, d).isoformat()
            except ValueError:
                return None
        m = re.search(r"\b(20\d{2})\s+([a-z]+)\s+(\d{1,2})\b", t)
        if m:
            y, mon_name, d = m.groups()
            mon = cls.MONTHS.get(mon_name)
            if mon:
                try:
                    return datetime.date(int(y), mon, int(d)).isoformat()
                except ValueError:
                    return None
        m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)[,\s]+(20\d{2})\b", t)
        if m:
            d, mon_name, y = m.groups()
            mon = cls.MONTHS.get(mon_name)
            if mon:
                try:
                    return datetime.date(int(y), mon, int(d)).isoformat()
                except ValueError:
                    return None
        return None

    @classmethod
    def _extract_expiry_hint(cls, text: str) -> Optional[str]:
        t = text.lower()
        # e.g. September 2026 / Sep expiry / 2026-09
        m = re.search(r"\b(20\d{2})[-/](\d{1,2})\b", t)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
        for name, month in cls.MONTHS.items():
            if re.search(rf"\b{name}\b", t):
                y = re.search(r"\b(20\d{2})\b", t)
                year = int(y.group(1)) if y else datetime.date.today().year
                return f"{year:04d}-{month:02d}"
        return None

    @classmethod
    def _resolve_symbol(cls, text: str, last_symbol: Optional[str] = None) -> Optional[str]:
        t = text.lower()
        # Specific indices first because 'nifty' is contained in 'bank nifty'.
        for alias in sorted(cls.INDEX_ALIASES, key=len, reverse=True):
            if alias in t:
                return cls.INDEX_ALIASES[alias]
        for alias in sorted(cls.STOCK_ALIASES, key=len, reverse=True):
            if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", t):
                return SymbolUniverse.format_symbol(cls.STOCK_ALIASES[alias])
        # Explicit NSE/BSE symbol-like token.
        m = re.search(r"\b(?:nse:|bse:)?([a-z][a-z0-9&-]{1,20})(?:-eq)?\b", t)
        market_words = {"current","price","share","stock","status","buy","buying","sell","hold","live","today","what","entha","ethra","ippo","analyse","analysis","support","resistance","option","expiry","call","put","nifty","sensex","bank","market","hello","hi"}
        if m and m.group(1) not in market_words and any(w in t for w in ["share", "stock", "price", "analyse", "analysis"]):
            return SymbolUniverse.format_symbol(m.group(1))
        # Context follow-up.
        if last_symbol and any(w in t for w in ["price","current","buy","buying","sell","hold","status","rsi","support","resistance","target","sl","athinte","its","that"]):
            return last_symbol
        return None

    @staticmethod
    def _is_strategy_request(text: str) -> bool:
        t = text.lower()
        return any(w in t for w in ["strategy", "scan cheyy", "scanner create", "continuous scan", "always scan", "alert thar", "search cheyy"]) and any(
            w in t for w in ["rsi", "ema", "sma", "vwap", "macd", "breakout", "breakdown", "open high", "open low", "volume", "candle"]
        )

    @staticmethod
    def _needs_live_market_data(text: str) -> bool:
        t = text.lower()
        return any(w in t for w in [
            "current", "live", "ippo", "today", "price", "ltp", "status", "analyse", "analysis",
            "buy", "buying", "sell", "hold", "support", "resistance", "rsi", "vwap", "trend",
            "option", "ce", "pe", "call", "put", "oi", "open interest"
        ])

    @staticmethod
    def _option_request(text: str) -> Optional[Tuple[int, str]]:
        t = text.lower()
        m = re.search(r"\b(\d{4,6})\s*(ce|pe)\b", t)
        if m:
            return int(m.group(1)), m.group(2).upper()
        m = re.search(r"\b(\d{4,6})\s*(call|put)\b", t)
        if m:
            return int(m.group(1)), "CE" if m.group(2) == "call" else "PE"
        return None

    async def _ai_resolve_symbol(self, text: str) -> Optional[str]:
        """Use Gemini/Groq only when deterministic aliases cannot identify a market entity."""
        prompt = (
            "Extract the Indian market instrument from this user message. Return JSON only with keys "
            "symbol and asset_type. symbol must be a likely NSE equity ticker without exchange suffix, or one of "
            "NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY. If no market instrument is mentioned, use null.\n"
            f"Message: {text}"
        )
        try:
            raw = await ai_router.generate_response_async(
                prompt=prompt,
                system_instruction="You are an entity resolver. Output strict JSON only.",
                json_mode=True,
                gemini_timeout=7.0,
                groq_timeout=5.0,
            )
            obj = json.loads(raw)
            sym = obj.get("symbol")
            if not sym:
                return None
            return SymbolUniverse.format_symbol(str(sym))
        except Exception as e:
            logger.warning(f"[MARKET_AGENT] AI symbol resolver failed: {e}")
            return None

    @classmethod
    def _inherit_option_from_context(cls, text: str, recent_messages) -> Optional[Tuple[int, str, str]]:
        """Resolve follow-ups like 'current price ethra?' after 'NIFTY 24000 PE September expiry'."""
        t = text.lower()
        if not any(w in t for w in ["current", "price", "ltp", "ippo", "ethra", "status", "oi", "iv"]):
            return None
        for item in reversed(recent_messages or []):
            if item.get("role") != "user":
                continue
            prev = str(item.get("content", ""))
            req = cls._option_request(prev)
            if req:
                underlying = cls._resolve_symbol(prev) or "NSE:NIFTY50-INDEX"
                return req[0], req[1], underlying
        return None

    @staticmethod
    def _conversation_context(user_id: str) -> str:
        ctx = storage.get_user_context(user_id)
        recent = ctx.get("recent_messages", [])[-6:]
        if not recent:
            return ""
        lines = []
        for item in recent:
            role = item.get("role", "user")
            content = str(item.get("content", ""))[:500]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    async def _final_ai(self, user_id: str, text: str, data_context: str = "") -> str:
        recent = self._conversation_context(user_id)
        system = (
            "You are STAFF BOT, a respectful personal Indian-market AI assistant. The user may speak Malayalam, Manglish, or English; "
            "reply naturally in the same style. Never call the user 'bro'. You are connected to FYERS through the application in READ-ONLY mode. "
            "When FYERS DATA is supplied, treat it as the only source of truth for live/historical prices and market facts. Never invent a live price. "
            "If FYERS DATA says unavailable, say that briefly. For buy/sell questions, give conditional analysis and risk notes, not guaranteed-profit claims. "
            "There is no auto-trading or order placement. Keep normal chat concise and friendly."
        )
        prompt = f"RECENT CONTEXT:\n{recent or '(none)'}\n\nUSER:\n{text}\n\nFYERS DATA:\n{data_context or '(no market data required/supplied)'}\n\nAnswer the user directly."
        return await ai_router.generate_response_async(prompt=prompt, system_instruction=system, gemini_timeout=12.0, groq_timeout=8.0)

    async def answer(self, user_id: str, text: str) -> str:
        """Answer a non-control Telegram message. Guarantees a text response."""
        ctx = storage.get_user_context(user_id)
        last_symbol = ctx.get("last_symbol")
        recent_messages = ctx.get("recent_messages", [])
        symbol = self._resolve_symbol(text, last_symbol)
        requested_date = self._extract_date(text)
        option_req = self._option_request(text)
        inherited_option = None if option_req else self._inherit_option_from_context(text, recent_messages)

        # If a market-data question names an instrument outside the built-in aliases, let Gemini resolve it.
        if not symbol and (requested_date or self._needs_live_market_data(text)):
            symbol = await self._ai_resolve_symbol(text)

        data_context = ""
        try:
            if option_req or inherited_option:
                if inherited_option and not option_req:
                    strike, side, underlying = inherited_option
                else:
                    strike, side = option_req
                    underlying = symbol or "NSE:NIFTY50-INDEX"
                expiry_hint = self._extract_expiry_hint(text)
                if inherited_option and not expiry_hint:
                    for item in reversed(recent_messages):
                        if item.get("role") == "user" and self._option_request(str(item.get("content", ""))):
                            expiry_hint = self._extract_expiry_hint(str(item.get("content", "")))
                            if expiry_hint:
                                break
                row, meta = await asyncio.to_thread(
                    fyers_service.get_option_contract_snapshot,
                    underlying, strike, side, expiry_hint
                )
                data_context = (
                    f"Source: FYERS option chain\nUnderlying: {underlying}\nRequested strike: {strike} {side}\n"
                    f"Requested expiry hint: {expiry_hint or 'nearest/current'}\nResolved expiry: {meta.get('resolved_expiry')}\n"
                    f"Option symbol: {row.get('symbol')}\nLTP: {row.get('ltp')}\nOI: {row.get('oi')}\nOI change: {row.get('oich')}\n"
                    f"Volume: {row.get('volume')}\nIV: {row.get('iv')}\nBid: {row.get('bid')}\nAsk: {row.get('ask')}\n"
                    f"Delta: {row.get('delta')} Gamma: {row.get('gamma')} Theta: {row.get('theta')} Vega: {row.get('vega')}"
                )
                storage.update_user_context(user_id, last_symbol=underlying, new_message={"role": "user", "content": text})
            elif symbol and requested_date:
                hist = await asyncio.to_thread(fyers_service.get_historical_daily_price, symbol, requested_date, True)
                data_context = (
                    f"Source: FYERS historical daily candles\nSymbol: {hist['symbol']}\nRequested date: {hist['requested_date']}\n"
                    f"Trading date used: {hist['trading_date']}\nPrevious trading day substituted: {hist['used_previous_trading_day']}\n"
                    f"Open: {hist['open']} High: {hist['high']} Low: {hist['low']} Close: {hist['close']} Volume: {hist['volume']}"
                )
                storage.update_user_context(user_id, last_symbol=symbol, new_message={"role": "user", "content": text})
            elif symbol and self._needs_live_market_data(text):
                quote = await asyncio.to_thread(fyers_service.get_quote, symbol)
                data_context = (
                    f"Source: FYERS live quote\nSymbol: {quote.symbol}\nLTP: {quote.ltp}\nOpen: {quote.open}\nHigh: {quote.high}\n"
                    f"Low: {quote.low}\nPrevious close: {quote.prev_close}\nChange: {quote.change}\nChange %: {quote.change_pct}\nVolume: {quote.volume}\nTimestamp: {quote.timestamp}"
                )
                # Add indicator context for analysis/advice style questions.
                if any(w in text.lower() for w in ["analyse", "analysis", "buy", "buying", "sell", "hold", "rsi", "support", "resistance", "trend"]):
                    try:
                        candles = await asyncio.to_thread(fyers_service.get_history, symbol, "5", 5)
                        if len(candles) >= 30:
                            rsi = float(TechnicalIndicators.rsi(candles["close"], 14).iloc[-1])
                            ema20 = float(TechnicalIndicators.ema(candles["close"], 20).iloc[-1])
                            ema50 = float(TechnicalIndicators.ema(candles["close"], 50).iloc[-1]) if len(candles) >= 50 else None
                            recent_high = float(candles["high"].tail(20).max())
                            recent_low = float(candles["low"].tail(20).min())
                            data_context += f"\n5M RSI14: {rsi:.2f}\n5M EMA20: {ema20:.2f}\n5M EMA50: {ema50 if ema50 is not None else 'insufficient history'}\n20-candle high: {recent_high}\n20-candle low: {recent_low}"
                    except Exception as e:
                        logger.warning(f"[MARKET_AGENT] Indicator enrichment skipped: {e}")
                storage.update_user_context(user_id, last_symbol=symbol, new_message={"role": "user", "content": text})
            elif any(w in text.lower() for w in ["market status", "market engane", "market today"]):
                overview = await asyncio.to_thread(fyers_service.get_market_overview)
                data_context = (
                    f"Source: FYERS\nNIFTY: {overview.nifty_spot} ({overview.nifty_change_pct:+.2f}%)\n"
                    f"BANKNIFTY: {overview.banknifty_spot} ({overview.banknifty_change_pct:+.2f}%)\n"
                    f"Breadth sample: {overview.advances} advances / {overview.declines} declines"
                )
                storage.update_user_context(user_id, new_message={"role": "user", "content": text})
            else:
                storage.update_user_context(user_id, new_message={"role": "user", "content": text})
        except MarketDataUnavailable as e:
            data_context = f"FYERS DATA UNAVAILABLE: {e}"
        except Exception as e:
            logger.exception(f"[MARKET_AGENT] FYERS enrichment failed: {e}")
            data_context = "FYERS DATA UNAVAILABLE: the requested market lookup failed unexpectedly."

        answer = await self._final_ai(user_id, text, data_context)
        storage.update_user_context(user_id, new_message={"role": "assistant", "content": answer})
        return answer


market_agent = MarketAgent()
