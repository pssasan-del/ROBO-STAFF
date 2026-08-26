import re
import json
from typing import Optional, Dict, Any, Tuple
from config import logger
from models import StrategyDefinition, StrategyCondition
from ai_router import ai_router
from errors import StrategyParseError

SYSTEM_PROMPT = """
You are the AI Strategy Parser for the Indian Stock Market (NSE/BSE).
Your job is to convert natural language strategy descriptions (which may be in English, Malayalam, or Manglish)
into a structured JSON specification for a deterministic Python strategy scanner.

Supported Condition Types:
- "ema_compare" (fast: int, slow: int, operator: ">"|"<")
- "sma_compare" (fast: int, slow: int, operator: ">"|"<")
- "rsi" (period: int, operator: ">"|"<"|">="|"<=", value: float)
- "macd" (fast: 12, slow: 26, signal: 9, operator: "crosses_above"|"crosses_below"|">"|"<")
- "vwap" (operator: ">"|"<")
- "atr" (period: 14, operator: ">"|"<", value: float)
- "bollinger" (period: 20, std_dev: 2.0, operator: ">"|"<")
- "volume_average" (period: int, operator: ">"|"<", value: float e.g. 1.5 or 1.0)
- "open_high" (tolerance_pct: 0.05)
- "open_low" (tolerance_pct: 0.05)
- "percentage_change" (operator: ">"|"<", value: float)
- "breakout" (lookback: int e.g. 20)
- "breakdown" (lookback: int e.g. 20)
- "candle_bullish"
- "candle_bearish"

Output format MUST be strictly JSON matching this structure:
{
  "name": "Strategy Name",
  "timeframe": "5" (e.g. "1", "3", "5", "15", "30", "60", "D"),
  "universe": "NIFTY50" (or "BANKNIFTY", "NIFTY100", "WATCHLIST"),
  "logic": "AND" (or "OR"),
  "description": "Brief Malayalam/English description",
  "conditions": [
    {
      "type": "condition_type",
      ...
    }
  ]
}

DO NOT output markdown code fences (```json), just pure valid JSON.
"""

class StrategyParser:
    """
    Parses natural language strategy descriptions into validated Pydantic models.
    Supports English, Malayalam, and Manglish with deterministic fast-path fallbacks.
    """

    @classmethod
    def parse_quick_rule(cls, text: str) -> Optional[StrategyDefinition]:
        """
        Fast deterministic parser for common phrases without consuming AI tokens.
        """
        t = text.lower().strip()
        
        # 1. Open = High
        if any(p in t for p in ["open high", "open=high", "open equal high", "open equals high", "open high stocks"]):
            return StrategyDefinition(
                name="Open High Bearish Scanner",
                timeframe="5",
                universe="NIFTY50" if "bank" not in t else "BANKNIFTY",
                logic="AND",
                description="Stocks where Day Open is equal to Day High (Bearish momentum)",
                conditions=[StrategyCondition(type="open_high", tolerance_pct=0.05)]
            )

        # 2. Open = Low
        if any(p in t for p in ["open low", "open=low", "open equal low", "open equals low", "open low stocks"]):
            return StrategyDefinition(
                name="Open Low Bullish Scanner",
                timeframe="5",
                universe="NIFTY50" if "bank" not in t else "BANKNIFTY",
                logic="AND",
                description="Stocks where Day Open is equal to Day Low (Bullish momentum)",
                conditions=[StrategyCondition(type="open_low", tolerance_pct=0.05)]
            )

        # 3. RSI Oversold (e.g. RSI 30 below / RSI below 30)
        rsi_match_below = re.search(r"rsi\s*(?:is\s*)?(?:below|<|under|താഴെ)\s*(\d+)", t) or re.search(r"rsi\s*(\d+)\s*below", t)
        if rsi_match_below:
            val = float(rsi_match_below.group(1))
            return StrategyDefinition(
                name=f"RSI Below {int(val)} Oversold",
                timeframe="5" if "15" not in t and "daily" not in t else ("15" if "15" in t else "D"),
                universe="NIFTY50",
                logic="AND",
                description=f"Stocks with RSI(14) < {val}",
                conditions=[StrategyCondition(type="rsi", period=14, operator="<", value=val)]
            )

        # 4. RSI Overbought (e.g. RSI above 60 / 70)
        rsi_match_above = re.search(r"rsi\s*(?:is\s*)?(?:above|>|over|മുകളിൽ)\s*(\d+)", t) or re.search(r"rsi\s*(\d+)\s*above", t)
        if rsi_match_above:
            val = float(rsi_match_above.group(1))
            return StrategyDefinition(
                name=f"RSI Above {int(val)} Momentum",
                timeframe="5" if "15" not in t and "daily" not in t else ("15" if "15" in t else "D"),
                universe="NIFTY50",
                logic="AND",
                description=f"Stocks with RSI(14) > {val}",
                conditions=[StrategyCondition(type="rsi", period=14, operator=">", value=val)]
            )

        # 5. EMA Crossover (e.g. EMA 20 EMA 50 cross / EMA20 above EMA50)
        ema_match = re.search(r"ema\s*(\d+)\s*(?:and|above|>|cross(?:es)?|over)?\s*ema\s*(\d+)", t)
        if ema_match:
            f = int(ema_match.group(1))
            s = int(ema_match.group(2))
            return StrategyDefinition(
                name=f"EMA {f}/{s} Trend Scanner",
                timeframe="5" if "15" not in t and "daily" not in t else ("15" if "15" in t else "D"),
                universe="NIFTY50",
                logic="AND",
                description=f"EMA {f} above EMA {s}",
                conditions=[StrategyCondition(type="ema_compare", fast=f, slow=s, operator=">")]
            )

        # 6. Breakout
        if "breakout" in t or "20 high" in t or "high cross" in t:
            return StrategyDefinition(
                name="20-Candle High Breakout",
                timeframe="5",
                universe="NIFTY50",
                logic="AND",
                description="Price breaking above 20-candle high",
                conditions=[StrategyCondition(type="breakout", lookback=20)]
            )

        return None

    @classmethod
    def parse_strategy(cls, user_text: str) -> StrategyDefinition:
        """
        Parses user strategy input using deterministic regex first, then AI router.
        Strictly validates through Pydantic.
        """
        # Step 1: Check fast deterministic matches
        quick_strat = cls.parse_quick_rule(user_text)
        if quick_strat:
            logger.info(f"[STRATEGY] Fast-path parsed: {quick_strat.name}")
            return quick_strat

        # Step 2: Use AI to parse custom/complex Manglish/Malayalam/English statements
        logger.info(f"[STRATEGY] Parsing via AI Router: '{user_text}'")
        raw_ai_json = ai_router.generate_response(
            prompt=f"Parse this stock strategy request into JSON:\n\n{user_text}",
            system_instruction=SYSTEM_PROMPT,
            json_mode=True
        )

        try:
            # Clean up potential markdown markers if any
            clean_json = raw_ai_json.strip()
            if clean_json.startswith("```json"):
                clean_json = clean_json[7:]
            if clean_json.startswith("```"):
                clean_json = clean_json[3:]
            if clean_json.endswith("```"):
                clean_json = clean_json[:-3]
            clean_json = clean_json.strip()

            parsed_dict = json.loads(clean_json)
            strat = StrategyDefinition(**parsed_dict)
            
            if not strat.conditions:
                raise StrategyParseError("No supported scan conditions were found in that strategy.")

            supported_universes = {"NIFTY50", "NIFTY100", "BANKNIFTY", "WATCHLIST"}
            normalized_universe = strat.universe.upper().replace(" ", "").replace("_", "").replace("-", "")
            if normalized_universe not in supported_universes and "," not in strat.universe:
                # Single stock symbols are allowed; broad unsupported universes are not.
                if normalized_universe in {"NIFTY200", "NIFTY500"}:
                    raise StrategyParseError(
                        f"{strat.universe} universe is not enabled yet because the project does not contain a verified full constituent list. "
                        "Use NIFTY50, NIFTY100, BANKNIFTY, WATCHLIST, or explicit stock symbols."
                    )

            logger.info(f"[STRATEGY] Parsed successfully: {strat.name} ({len(strat.conditions)} conditions)")
            return strat

        except StrategyParseError:
            raise
        except Exception as e:
            logger.warning(f"[STRATEGY] AI strategy parse/validation failed: {e}")
            raise StrategyParseError(
                "I couldn't safely convert that strategy into supported scan rules. Please rephrase it with timeframe, universe, and exact conditions."
            ) from e
