import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Any, Optional, Callable, Set
import pandas as pd

from config import logger, settings
from fyers_service import fyers_service
from indicators import TechnicalIndicators


@dataclass
class OptionSignal:
    strategy_id: str
    strategy_name: str
    action: str  # CE_BUY, PE_BUY, CE_EXIT, PE_EXIT, NO_SIGNAL
    spot: float
    option_symbol: Optional[str]
    option_ltp: Optional[float]
    reason: str
    details: Dict[str, Any]
    timestamp: float


class NiftyOptionSignalEngine:
    """Read-only NIFTY option signal engine. Never places orders."""

    UNDERLYING = "NSE:NIFTY50-INDEX"

    @staticmethod
    def _fib_pivots(prev_high: float, prev_low: float, prev_close: float) -> Dict[str, float]:
        p = (prev_high + prev_low + prev_close) / 3.0
        r = prev_high - prev_low
        return {
            "P": p,
            "R1": p + 0.382 * r,
            "R2": p + 0.618 * r,
            "R3": p + 1.000 * r,
            "S1": p - 0.382 * r,
            "S2": p - 0.618 * r,
            "S3": p - 1.000 * r,
        }

    @staticmethod
    def _near(value: float, level: float, pct: float = 0.25) -> bool:
        if level == 0:
            return False
        return abs(value - level) / abs(level) * 100 <= pct

    @staticmethod
    def _cross_above(series: pd.Series, level: float) -> bool:
        return len(series) >= 2 and float(series.iloc[-2]) <= level < float(series.iloc[-1])

    @staticmethod
    def _cross_below(series: pd.Series, level: float) -> bool:
        return len(series) >= 2 and float(series.iloc[-2]) >= level > float(series.iloc[-1])

    def _context(self) -> Dict[str, Any]:
        intraday = fyers_service.get_history(self.UNDERLYING, timeframe="5", days_back=5)
        daily = fyers_service.get_history(self.UNDERLYING, timeframe="D", days_back=10)
        if len(intraday) < 60 or len(daily) < 2:
            raise RuntimeError("Insufficient FYERS candle history for NIFTY option signal engine")

        close = intraday["close"].astype(float)
        ema9 = TechnicalIndicators.ema(close, 9)
        ema20 = TechnicalIndicators.ema(close, 20)
        ema50 = TechnicalIndicators.ema(close, 50)
        vwap = TechnicalIndicators.vwap(intraday)
        wr = TechnicalIndicators.williams_r(intraday, 14)
        adx = TechnicalIndicators.adx(intraday, 14)

        prev = daily.iloc[-2]
        piv = self._fib_pivots(float(prev.high), float(prev.low), float(prev.close))
        chain = fyers_service.get_option_chain(self.UNDERLYING, strikecount=8, greeks=True)
        oi = fyers_service.summarize_nifty_oi(chain)

        spot = float(close.iloc[-1])
        atm_ce = oi.get("atm_ce") or {}
        atm_pe = oi.get("atm_pe") or {}

        return {
            "intraday": intraday,
            "spot": spot,
            "ema9": float(ema9.iloc[-1]),
            "ema20": float(ema20.iloc[-1]),
            "ema50": float(ema50.iloc[-1]),
            "vwap": float(vwap.iloc[-1]),
            "wr": wr,
            "wr_now": float(wr.iloc[-1]),
            "adx": float(adx.iloc[-1]),
            "piv": piv,
            "oi": oi,
            "atm_ce": atm_ce,
            "atm_pe": atm_pe,
        }

    def evaluate_momentum(self) -> OptionSignal:
        c = self._context()
        spot, p = c["spot"], c["piv"]
        wr = c["wr"]
        bullish_oi = c["oi"].get("bias") == "BULLISH"
        bearish_oi = c["oi"].get("bias") == "BEARISH"

        ce = (
            spot > p["P"] and c["ema20"] > c["ema50"] and spot > c["vwap"]
            and c["wr_now"] > -50 and (self._cross_above(wr, -50) or float(wr.iloc[-1]) > float(wr.iloc[-2]))
            and c["adx"] >= 20 and bullish_oi
        )
        pe = (
            spot < p["P"] and c["ema20"] < c["ema50"] and spot < c["vwap"]
            and c["wr_now"] < -50 and (self._cross_below(wr, -50) or float(wr.iloc[-1]) < float(wr.iloc[-2]))
            and c["adx"] >= 20 and bearish_oi
        )

        action = "CE_BUY" if ce else "PE_BUY" if pe else "NO_SIGNAL"
        opt = c["atm_ce"] if ce else c["atm_pe"] if pe else {}
        reason = (
            "Trend + Fib pivot + EMA + VWAP + Williams %R + ADX + OI profile aligned"
            if action != "NO_SIGNAL" else "Momentum filters not fully aligned"
        )
        return OptionSignal(
            strategy_id="nifty_momentum_v1", strategy_name="NIFTY Momentum Pro",
            action=action, spot=spot, option_symbol=opt.get("symbol"), option_ltp=opt.get("ltp"),
            reason=reason,
            details={"P": p["P"], "R1": p["R1"], "S1": p["S1"], "EMA20": c["ema20"], "EMA50": c["ema50"],
                     "VWAP": c["vwap"], "WilliamsR": c["wr_now"], "ADX": c["adx"], "OI_Bias": c["oi"].get("bias"),
                     "PCR": c["oi"].get("pcr"), "ATM": c["oi"].get("atm_strike")},
            timestamp=time.time(),
        )

    def evaluate_fib_reversal(self) -> OptionSignal:
        c = self._context()
        spot, p, wr = c["spot"], c["piv"], c["wr"]
        bullish_oi = c["oi"].get("bias") in ("BULLISH", "NEUTRAL")
        bearish_oi = c["oi"].get("bias") in ("BEARISH", "NEUTRAL")

        at_support = self._near(spot, p["S1"], 0.30) or self._near(spot, p["S2"], 0.30)
        at_resistance = self._near(spot, p["R1"], 0.30) or self._near(spot, p["R2"], 0.30)

        ce = at_support and self._cross_above(wr, -80) and spot > c["ema9"] and c["adx"] >= 15 and bullish_oi
        pe = at_resistance and self._cross_below(wr, -20) and spot < c["ema9"] and c["adx"] >= 15 and bearish_oi

        action = "CE_BUY" if ce else "PE_BUY" if pe else "NO_SIGNAL"
        opt = c["atm_ce"] if ce else c["atm_pe"] if pe else {}
        reason = (
            "Fib support/resistance reversal + Williams %R trigger + EMA9 + ADX + OI confirmation"
            if action != "NO_SIGNAL" else "Reversal filters not fully aligned"
        )
        return OptionSignal(
            strategy_id="nifty_fib_reversal_v1", strategy_name="NIFTY Fib Reversal Pro",
            action=action, spot=spot, option_symbol=opt.get("symbol"), option_ltp=opt.get("ltp"),
            reason=reason,
            details={"R1": p["R1"], "R2": p["R2"], "S1": p["S1"], "S2": p["S2"], "EMA9": c["ema9"],
                     "WilliamsR": c["wr_now"], "ADX": c["adx"], "OI_Bias": c["oi"].get("bias"),
                     "PCR": c["oi"].get("pcr"), "ATM": c["oi"].get("atm_strike")},
            timestamp=time.time(),
        )

    @staticmethod
    def format_alert(sig: OptionSignal) -> str:
        icon = "🟢" if sig.action == "CE_BUY" else "🔴" if sig.action == "PE_BUY" else "⚪"
        lines = [
            f"{icon} *NIFTY OPTION SIGNAL*",
            f"*Strategy:* {sig.strategy_name}",
            f"*Action:* `{sig.action}`",
            f"*NIFTY Spot:* ₹{sig.spot:,.2f}",
        ]
        if sig.option_symbol:
            lines.append(f"*ATM Contract:* `{sig.option_symbol}`")
        if sig.option_ltp is not None:
            lines.append(f"*Option LTP:* ₹{float(sig.option_ltp):,.2f}")
        lines.append(f"*Why:* {sig.reason}")
        d = sig.details
        lines.append(
            f"Fib P/R1/S1: {d.get('P','-') if 'P' in d else '-'} / {d.get('R1','-')} / {d.get('S1','-')}\n"
            f"Williams %R: {d.get('WilliamsR',0):.1f} | ADX: {d.get('ADX',0):.1f} | OI: {d.get('OI_Bias')} | PCR: {d.get('PCR')}"
        )
        lines.append("_Signal/alert only. No order is placed._")
        return "\n".join(lines)


class NiftyOptionScannerManager:
    def __init__(self):
        self.engine = NiftyOptionSignalEngine()
        self.enabled: Set[str] = set()
        self._running = False
        self._alert_callback: Optional[Callable] = None
        self._last_sent: Dict[str, tuple] = {}

    def set_alert_callback(self, cb: Callable):
        self._alert_callback = cb

    def start(self, strategy_id: str):
        if strategy_id not in {"nifty_momentum_v1", "nifty_fib_reversal_v1"}:
            raise ValueError("Unknown NIFTY option strategy")
        self.enabled.add(strategy_id)
        logger.info(f"[NIFTY_OPTIONS] Started {strategy_id}")

    def stop(self, strategy_id: Optional[str] = None):
        if strategy_id:
            self.enabled.discard(strategy_id)
        else:
            self.enabled.clear()
        logger.info(f"[NIFTY_OPTIONS] Stopped {strategy_id or 'all'}")

    def status(self):
        return sorted(self.enabled)

    def _allow_alert(self, sig: OptionSignal) -> bool:
        if sig.action == "NO_SIGNAL":
            return False
        key = sig.strategy_id
        prev = self._last_sent.get(key)
        now = time.time()
        if prev and prev[0] == sig.action and now - prev[1] < settings.ALERT_COOLDOWN_MINUTES * 60:
            return False
        self._last_sent[key] = (sig.action, now)
        return True

    async def run_loop(self):
        self._running = True
        while self._running:
            for sid in list(self.enabled):
                try:
                    sig = await asyncio.to_thread(
                        self.engine.evaluate_momentum if sid == "nifty_momentum_v1" else self.engine.evaluate_fib_reversal
                    )
                    logger.info(f"[NIFTY_OPTIONS] {sid} => {sig.action}")
                    if self._allow_alert(sig) and self._alert_callback:
                        msg = self.engine.format_alert(sig)
                        if asyncio.iscoroutinefunction(self._alert_callback):
                            await self._alert_callback(msg)
                        else:
                            self._alert_callback(msg)
                except Exception as e:
                    logger.error(f"[NIFTY_OPTIONS] {sid} scan failed: {e}")
            await asyncio.sleep(max(30, settings.SCAN_INTERVAL_SECONDS))


nifty_option_scanner = NiftyOptionScannerManager()
