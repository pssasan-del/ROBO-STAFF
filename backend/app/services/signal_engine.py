from __future__ import annotations

from dataclasses import dataclass, asdict
from statistics import fmean
from typing import Any


@dataclass(slots=True)
class Signal:
    symbol_key: str
    side: str
    entry: float
    stop: float
    target1: float
    target2: float
    rr: float
    score: int
    reason: str
    timeframe_sec: int
    source: str = "neo_strict_momentum_v2"
    target3: float | None = None
    rsi14: float | None = None
    williams_r14: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None

    result = fmean(values[:period])
    k = 2.0 / (period + 1.0)

    for value in values[period:]:
        result = ((value - result) * k) + result

    return result


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ][-period:]

    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]

    avg_gain = fmean(gains)
    avg_loss = fmean(losses)

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _williams_r(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float | None:

    if len(highs) < period:
        return None

    hh = max(highs[-period:])
    ll = min(lows[-period:])

    if hh <= ll:
        return None

    return -100.0 * ((hh - closes[-1]) / (hh - ll))


class StrictSignalEngine:
    def __init__(
        self,
        min_rr: float = 1.85,
        lookback: int = 20,
        min_score: int = 75,
    ) -> None:
        self.min_rr = min_rr
        self.lookback = lookback
        self.min_score = min_score

    def evaluate(
        self,
        symbol_key: str,
        rows: list[dict[str, Any]],
        timeframe_sec: int = 300,
    ) -> dict[str, Any]:

        need = max(self.lookback + 2, 24)

        if len(rows) < need:
            return {
                "status": "REJECTED",
                "reason": "INSUFFICIENT_HISTORY",
                "need": need,
                "have": len(rows),
            }

        clean = []

        for row in rows:
            try:
                clean.append({
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or 0.0),
                })
            except Exception:
                continue

        if len(clean) < need:
            return {
                "status": "REJECTED",
                "reason": "INVALID_CANDLE_HISTORY",
            }

        history = clean[:-1]
        last = clean[-1]

        closes = [x["close"] for x in clean]
        highs = [x["high"] for x in clean]
        lows = [x["low"] for x in clean]

        previous = history[-self.lookback:]

        resistance = max(x["high"] for x in previous)
        support = min(x["low"] for x in previous)

        entry = last["close"]

        if entry <= 0:
            return {"status": "REJECTED", "reason": "INVALID_PRICE"}

        ema9 = _ema(closes, 9)
        ema21 = _ema(closes, 21)
        rsi14 = _rsi(closes, 14)
        williams = _williams_r(highs, lows, closes, 14)

        ranges = [
            max(0.0, x["high"] - x["low"])
            for x in history[-14:]
        ]

        atr = fmean(ranges) if ranges else 0.0

        if atr <= 0:
            return {"status": "REJECTED", "reason": "NO_VOLATILITY"}

        if ema9 is None or ema21 is None:
            return {"status": "REJECTED", "reason": "EMA_NOT_READY"}

        side = None

        if entry > resistance and ema9 > ema21:
            side = "BUY"
        elif entry < support and ema9 < ema21:
            side = "SELL"
        else:
            return {
                "status": "REJECTED",
                "reason": "NO_CONFIRMED_BREAKOUT",
            }

        score = 60
        reasons = []

        score += 10
        reasons.append("EMA_TREND")

        if rsi14 is not None:
            if side == "BUY" and 55 <= rsi14 <= 78:
                score += 10
                reasons.append("RSI")
            elif side == "SELL" and 22 <= rsi14 <= 45:
                score += 10
                reasons.append("RSI")
            else:
                return {
                    "status": "REJECTED",
                    "reason": "RSI_NOT_CONFIRMED",
                }

        if williams is not None:
            if side == "BUY" and -50 <= williams <= -5:
                score += 10
                reasons.append("WILLIAMS")
            elif side == "SELL" and -95 <= williams <= -50:
                score += 10
                reasons.append("WILLIAMS")
            else:
                return {
                    "status": "REJECTED",
                    "reason": "WILLIAMS_NOT_CONFIRMED",
                }

        breakout_distance = (
            entry - resistance
            if side == "BUY"
            else support - entry
        )

        breakout_atr = breakout_distance / atr

        if breakout_atr <= 0:
            return {
                "status": "REJECTED",
                "reason": "BREAKOUT_NOT_CONFIRMED",
            }

        if breakout_atr > 1.5:
            return {
                "status": "REJECTED",
                "reason": "OVEREXTENDED",
            }

        score += 10
        reasons.append("BREAKOUT")

        previous_volumes = [
            x["volume"]
            for x in history[-20:]
            if x["volume"] > 0
        ]

        if previous_volumes and last["volume"] > 0:
            avg_volume = fmean(previous_volumes)

            if avg_volume > 0:
                ratio = last["volume"] / avg_volume

                if ratio >= 1.05:
                    score += 10
                    reasons.append("VOLUME")
                elif ratio < 0.70:
                    return {
                        "status": "REJECTED",
                        "reason": "WEAK_VOLUME",
                    }

        if side == "BUY":
            stop = max(last["low"], entry - 1.20 * atr)
            risk = entry - stop
        else:
            stop = min(last["high"], entry + 1.20 * atr)
            risk = stop - entry

        if risk <= 0:
            return {"status": "REJECTED", "reason": "INVALID_RISK"}

        if risk / entry > 0.08:
            return {
                "status": "REJECTED",
                "reason": "RISK_OUT_OF_RANGE",
            }

        if side == "BUY":
            target1 = entry + self.min_rr * risk
            target2 = entry + 2.30 * risk
            target3 = entry + 3.00 * risk
        else:
            target1 = entry - self.min_rr * risk
            target2 = entry - 2.30 * risk
            target3 = entry - 3.00 * risk

        score = min(score, 100)

        if score < self.min_score:
            return {
                "status": "REJECTED",
                "reason": "SCORE_TOO_LOW",
                "score": score,
            }

        sig = Signal(
            symbol_key=symbol_key,
            side=side,
            entry=round(entry, 4),
            stop=round(stop, 4),
            target1=round(target1, 4),
            target2=round(target2, 4),
            target3=round(target3, 4),
            rr=self.min_rr,
            score=score,
            reason=" + ".join(reasons),
            timeframe_sec=timeframe_sec,
            rsi14=round(rsi14, 2) if rsi14 is not None else None,
            williams_r14=round(williams, 2) if williams is not None else None,
        )

        return {
            "status": "SIGNAL",
            "signal": sig.to_dict(),
        }


signal_engine = StrictSignalEngine()


class BaselineSignalEngine:
    """Compatibility baseline retained only for legacy tests/imports.

    Production auto-scanning uses ``signal_engine`` above, which is StrictSignalEngine.
    """
    def __init__(self, min_rr: float = 1.85, lookback: int = 20) -> None:
        self.min_rr = min_rr
        self.lookback = lookback

    def evaluate(self, symbol_key: str, rows: list[dict[str, Any]], timeframe_sec: int = 300) -> dict[str, Any]:
        if len(rows) < self.lookback + 2:
            return {"status": "REJECTED", "reason": "INSUFFICIENT_HISTORY", "need": self.lookback + 2, "have": len(rows)}
        clean=[]
        for row in rows:
            try:
                clean.append({"open":float(row["open"]),"high":float(row["high"]),"low":float(row["low"]),"close":float(row["close"])})
            except Exception:
                pass
        if len(clean) < self.lookback + 2:
            return {"status":"REJECTED","reason":"INVALID_CANDLE_HISTORY"}
        last=clean[-1]
        previous=clean[-(self.lookback+1):-1]
        resistance=max(x["high"] for x in previous)
        support=min(x["low"] for x in previous)
        entry=last["close"]
        if entry > resistance:
            side="BUY"; stop=last["low"]; risk=entry-stop
        elif entry < support:
            side="SELL"; stop=last["high"]; risk=stop-entry
        else:
            return {"status":"REJECTED","reason":"NO_CONFIRMED_BREAKOUT"}
        if risk <= 0:
            return {"status":"REJECTED","reason":"INVALID_RISK"}
        t1=entry+self.min_rr*risk if side=="BUY" else entry-self.min_rr*risk
        t2=entry+2.3*risk if side=="BUY" else entry-2.3*risk
        sig=Signal(symbol_key,side,round(entry,4),round(stop,4),round(t1,4),round(t2,4),self.min_rr,80,"baseline breakout",timeframe_sec)
        return {"status":"SIGNAL","signal":sig.to_dict()}
