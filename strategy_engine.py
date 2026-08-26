import pandas as pd
import numpy as np
from typing import Tuple, List, Optional
from models import StrategyDefinition, StrategyCondition, ConditionMatchDetail, ScanMatch
from indicators import TechnicalIndicators
from symbol_universe import SymbolUniverse

class StrategyEngine:
    """
    Deterministic Python Strategy Evaluation Engine.
    Executes validated rules on historical OHLCV data without AI calls.
    """

    @staticmethod
    def evaluate_condition(condition: StrategyCondition, df: pd.DataFrame) -> Tuple[bool, str, str]:
        """
        Evaluates a single condition on a DataFrame.
        Returns: (passed: bool, description: str, actual_value_str: str)
        """
        if df.empty or len(df) < 5:
            return False, condition.description or "Insufficient candles", "N/A"

        c_type = condition.type
        op = condition.operator or ">"
        target_val = condition.value if condition.value is not None else 0.0

        close = df['close']
        latest_close = float(close.iloc[-1])
        latest_open = float(df['open'].iloc[-1])
        latest_high = float(df['high'].iloc[-1])
        latest_low = float(df['low'].iloc[-1])
        latest_volume = float(df['volume'].iloc[-1])

        # 1. EMA Comparison (e.g., EMA 20 > EMA 50 or Close > EMA 20)
        if c_type == "ema_compare":
            fast_p = condition.fast or 20
            slow_p = condition.slow or 50
            ema_fast = TechnicalIndicators.ema(close, fast_p)
            ema_slow = TechnicalIndicators.ema(close, slow_p)
            
            if ema_fast.empty or ema_slow.empty or pd.isna(ema_fast.iloc[-1]) or pd.isna(ema_slow.iloc[-1]):
                return False, f"EMA({fast_p}) vs EMA({slow_p})", "Calculating..."
                
            val_fast = float(ema_fast.iloc[-1])
            val_slow = float(ema_slow.iloc[-1])
            
            passed = StrategyEngine._compare(val_fast, op, val_slow)
            desc = f"EMA({fast_p}) {op} EMA({slow_p})"
            val_str = f"EMA{fast_p}={val_fast:.2f}, EMA{slow_p}={val_slow:.2f}"
            return passed, desc, val_str

        # 2. SMA Comparison
        elif c_type == "sma_compare":
            fast_p = condition.fast or 20
            slow_p = condition.slow or 50
            sma_fast = TechnicalIndicators.sma(close, fast_p)
            sma_slow = TechnicalIndicators.sma(close, slow_p)
            
            if sma_fast.empty or sma_slow.empty or pd.isna(sma_fast.iloc[-1]) or pd.isna(sma_slow.iloc[-1]):
                return False, f"SMA({fast_p}) vs SMA({slow_p})", "Calculating..."
                
            val_fast = float(sma_fast.iloc[-1])
            val_slow = float(sma_slow.iloc[-1])
            
            passed = StrategyEngine._compare(val_fast, op, val_slow)
            desc = f"SMA({fast_p}) {op} SMA({slow_p})"
            val_str = f"SMA{fast_p}={val_fast:.2f}, SMA{slow_p}={val_slow:.2f}"
            return passed, desc, val_str

        # 3. RSI
        elif c_type == "rsi":
            period = condition.period or 14
            rsi_series = TechnicalIndicators.rsi(close, period)
            if rsi_series.empty or pd.isna(rsi_series.iloc[-1]):
                return False, f"RSI({period}) {op} {target_val}", "N/A"
                
            curr_rsi = float(rsi_series.iloc[-1])
            passed = StrategyEngine._compare(curr_rsi, op, target_val, condition.min_value, condition.max_value)
            desc = f"RSI({period}) {op} {target_val}"
            val_str = f"{curr_rsi:.2f}"
            return passed, desc, val_str

        # 4. MACD
        elif c_type == "macd":
            fast = condition.fast or 12
            slow = condition.slow or 26
            signal = condition.signal or 9
            macd_line, sig_line, hist = TechnicalIndicators.macd(close, fast, slow, signal)
            
            if macd_line.empty or pd.isna(macd_line.iloc[-1]):
                return False, f"MACD({fast},{slow},{signal})", "N/A"
                
            curr_macd = float(macd_line.iloc[-1])
            curr_sig = float(sig_line.iloc[-1])
            
            if op in ("crosses_above", "crossover"):
                passed = TechnicalIndicators.crossover(macd_line, sig_line)
                desc = f"MACD crosses above Signal"
            elif op in ("crosses_below", "crossunder"):
                passed = TechnicalIndicators.crossunder(macd_line, sig_line)
                desc = f"MACD crosses below Signal"
            else:
                passed = StrategyEngine._compare(curr_macd, op, curr_sig)
                desc = f"MACD {op} Signal"
                
            val_str = f"MACD={curr_macd:.2f}, Signal={curr_sig:.2f}"
            return passed, desc, val_str

        # 5. VWAP
        elif c_type == "vwap":
            vwap_series = TechnicalIndicators.vwap(df)
            if vwap_series.empty or pd.isna(vwap_series.iloc[-1]):
                return False, f"Price {op} VWAP", "N/A"
                
            curr_vwap = float(vwap_series.iloc[-1])
            passed = StrategyEngine._compare(latest_close, op, curr_vwap)
            desc = f"Price ({latest_close:.2f}) {op} VWAP ({curr_vwap:.2f})"
            val_str = f"VWAP={curr_vwap:.2f}"
            return passed, desc, val_str

        # 6. Volume Average
        elif c_type == "volume_average":
            period = condition.period or 20
            vol_avg = TechnicalIndicators.volume_average(df['volume'], period)
            if vol_avg.empty or pd.isna(vol_avg.iloc[-1]):
                return False, f"Volume > {period} Avg", "N/A"
                
            avg_v = float(vol_avg.iloc[-1])
            mult = condition.value if condition.value and condition.value > 0 else 1.0
            threshold_v = avg_v * mult
            passed = StrategyEngine._compare(latest_volume, op, threshold_v)
            desc = f"Volume {op} {mult:.1f}x {period}-period Avg"
            val_str = f"{latest_volume:.0f} (Avg: {avg_v:.0f})"
            return passed, desc, val_str

        # 7. Open = High
        elif c_type == "open_high":
            tol = condition.tolerance_pct or 0.05
            passed = TechnicalIndicators.is_open_high(latest_open, latest_high, tol)
            desc = f"Open == High (tol: {tol}%)"
            val_str = f"Open={latest_open:.2f}, High={latest_high:.2f}"
            return passed, desc, val_str

        # 8. Open = Low
        elif c_type == "open_low":
            tol = condition.tolerance_pct or 0.05
            passed = TechnicalIndicators.is_open_low(latest_open, latest_low, tol)
            desc = f"Open == Low (tol: {tol}%)"
            val_str = f"Open={latest_open:.2f}, Low={latest_low:.2f}"
            return passed, desc, val_str

        # 9. Breakout / Breakdown
        elif c_type == "breakout":
            lookback = condition.lookback or 20
            passed = TechnicalIndicators.is_breakout(df, lookback)
            prev_high = float(df['high'].iloc[-(lookback+1):-1].max()) if len(df) > lookback else 0.0
            desc = f"{lookback}-candle High Breakout"
            val_str = f"Close {latest_close:.2f} > PrevHigh {prev_high:.2f}"
            return passed, desc, val_str

        elif c_type == "breakdown":
            lookback = condition.lookback or 20
            passed = TechnicalIndicators.is_breakdown(df, lookback)
            prev_low = float(df['low'].iloc[-(lookback+1):-1].min()) if len(df) > lookback else 0.0
            desc = f"{lookback}-candle Low Breakdown"
            val_str = f"Close {latest_close:.2f} < PrevLow {prev_low:.2f}"
            return passed, desc, val_str

        # 10. Percentage Change
        elif c_type == "percentage_change":
            prev_close = float(df['close'].iloc[-2]) if len(df) >= 2 else latest_open
            pct_change = ((latest_close - prev_close) / prev_close) * 100.0 if prev_close > 0 else 0.0
            passed = StrategyEngine._compare(pct_change, op, target_val)
            desc = f"% Change {op} {target_val}%"
            val_str = f"{pct_change:+.2f}%"
            return passed, desc, val_str

        # 11. Bollinger Bands
        elif c_type == "bollinger":
            period = condition.period or 20
            std_dev = condition.std_dev or 2.0
            upper, middle, lower = TechnicalIndicators.bollinger_bands(close, period, std_dev)
            if upper.empty or pd.isna(upper.iloc[-1]):
                return False, "Bollinger Bands", "N/A"
            u_val = float(upper.iloc[-1])
            l_val = float(lower.iloc[-1])
            if op in (">", ">=", "crosses_above"):
                passed = latest_close >= u_val
                desc = f"Price >= Upper Bollinger Band"
            else:
                passed = latest_close <= l_val
                desc = f"Price <= Lower Bollinger Band"
            val_str = f"Price={latest_close:.2f}, Upper={u_val:.2f}, Lower={l_val:.2f}"
            return passed, desc, val_str

        # 12. Candle Pattern
        elif c_type == "candle_bullish":
            passed = latest_close > latest_open
            desc = "Bullish Candle (Close > Open)"
            val_str = f"O={latest_open:.2f}, C={latest_close:.2f}"
            return passed, desc, val_str

        elif c_type == "candle_bearish":
            passed = latest_close < latest_open
            desc = "Bearish Candle (Close < Open)"
            val_str = f"O={latest_open:.2f}, C={latest_close:.2f}"
            return passed, desc, val_str

        # Fallback for generic conditions
        return True, condition.description or "Generic condition", "Passed"

    @staticmethod
    def _compare(
        val: float,
        op: str,
        target: float,
        min_v: Optional[float] = None,
        max_v: Optional[float] = None
    ) -> bool:
        if op == ">":
            return val > target
        elif op in (">=", "=>"):
            return val >= target
        elif op == "<":
            return val < target
        elif op in ("<=", "=<"):
            return val <= target
        elif op in ("=", "=="):
            return abs(val - target) < 1e-4
        elif op in ("!=", "<>"):
            return abs(val - target) >= 1e-4
        elif op == "between":
            low = min_v if min_v is not None else target
            high = max_v if max_v is not None else target
            return low <= val <= high
        elif op == "near":
            tolerance = abs(target * 0.005)  # 0.5% near
            return abs(val - target) <= tolerance
        return val > target

    @classmethod
    def evaluate_strategy(
        cls,
        strategy: StrategyDefinition,
        symbol: str,
        df: pd.DataFrame,
        is_mock: bool = False
    ) -> Optional[ScanMatch]:
        """
        Evaluates full strategy against stock candle DataFrame.
        Returns ScanMatch if matched, None otherwise.
        """
        if df.empty or len(df) < 5:
            return None

        details: List[ConditionMatchDetail] = []
        condition_results: List[bool] = []

        for idx, cond in enumerate(strategy.conditions):
            passed, desc, val_str = cls.evaluate_condition(cond, df)
            details.append(ConditionMatchDetail(
                condition_index=idx,
                condition_desc=desc,
                actual_value=val_str,
                passed=passed
            ))
            condition_results.append(passed)

        if not condition_results:
            return None

        # Logic combination
        if strategy.logic == "AND":
            overall_match = all(condition_results)
        else:
            overall_match = any(condition_results)

        if not overall_match:
            return None

        latest_close = float(df['close'].iloc[-1])
        latest_ts = float(df['timestamp'].iloc[-1]) if 'timestamp' in df.columns else df.index[-1]
        
        # Build deduplication signature
        cond_sig = "_".join([f"{d.condition_desc}:{d.passed}" for d in details])
        signature = f"{strategy.id or strategy.name}_{symbol}_{cond_sig}"

        return ScanMatch(
            strategy_id=strategy.id or strategy.name,
            strategy_name=strategy.name,
            symbol=symbol,
            company_name=SymbolUniverse.clean_symbol_name(symbol),
            ltp=latest_close,
            timeframe=strategy.timeframe,
            timestamp=latest_ts if isinstance(latest_ts, (int, float)) else time.time(),
            matched_conditions=details,
            signature=signature,
            is_mock=is_mock
        )
