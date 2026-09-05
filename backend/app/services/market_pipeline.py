from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from collections import defaultdict, deque
from typing import Any
import sqlite3
from pathlib import Path


@dataclass(slots=True)
class Candle:
    symbol_key: str
    timeframe_sec: int
    start_ts: int
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    ticks: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["start_iso"] = datetime.fromtimestamp(self.start_ts, tz=timezone.utc).isoformat()
        return d


class CandleBuilder:
    """Builds deterministic OHLC candles from broker-delivered LTP updates.

    Volume uses positive deltas from the feed's cumulative day-volume when present.
    The builder does not invent missing ticks/candles.
    """

    def __init__(self, timeframes: tuple[int, ...] = (60, 180, 300, 900)) -> None:
        self.timeframes = timeframes
        self.current: dict[tuple[str, int], Candle] = {}
        self.history: dict[tuple[str, int], deque[Candle]] = defaultdict(lambda: deque(maxlen=500))
        self.last_day_volume: dict[str, int] = {}

        self.db_path = Path(__file__).resolve().parents[2] / "candle_history.db"
        self._init_db()
        self._load_history()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS candles (
                    symbol_key TEXT NOT NULL,
                    timeframe_sec INTEGER NOT NULL,
                    start_ts INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    ticks INTEGER NOT NULL,
                    PRIMARY KEY (symbol_key, timeframe_sec, start_ts)
                )
            """)
            con.commit()

    def _save_candle(self, candle: Candle) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                INSERT OR REPLACE INTO candles
                (symbol_key, timeframe_sec, start_ts, open, high, low, close, volume, ticks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                candle.symbol_key,
                candle.timeframe_sec,
                candle.start_ts,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                candle.ticks,
            ))
            con.commit()

    def _load_history(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("""
                SELECT symbol_key, timeframe_sec, start_ts,
                       open, high, low, close, volume, ticks
                FROM candles
                ORDER BY start_ts ASC
            """).fetchall()

        for row in rows:
            candle = Candle(*row)
            self.history[(candle.symbol_key, candle.timeframe_sec)].append(candle)

    def ingest(self, symbol_key: str, ltp: float, event_ts: int, day_volume: int | None = None) -> list[Candle]:
        if ltp <= 0 or event_ts <= 0:
            return []
        vol_delta = 0
        if day_volume is not None and day_volume >= 0:
            prev = self.last_day_volume.get(symbol_key)
            if prev is not None and day_volume >= prev:
                vol_delta = day_volume - prev
            self.last_day_volume[symbol_key] = day_volume

        closed: list[Candle] = []
        for tf in self.timeframes:
            bucket = event_ts - (event_ts % tf)
            key = (symbol_key, tf)
            c = self.current.get(key)
            if c is None or c.start_ts != bucket:
                if c is not None:
                    self.history[key].append(c)
                    self._save_candle(c)
                    closed.append(c)
                self.current[key] = Candle(symbol_key, tf, bucket, ltp, ltp, ltp, ltp, vol_delta, 1)
            else:
                c.high = max(c.high, ltp)
                c.low = min(c.low, ltp)
                c.close = ltp
                c.volume += vol_delta
                c.ticks += 1
        return closed

    def get_history(self, symbol_key: str, timeframe_sec: int, limit: int = 100) -> list[dict[str, Any]]:
        vals = list(self.history.get((symbol_key, timeframe_sec), ()))
        if (c := self.current.get((symbol_key, timeframe_sec))) is not None:
            vals.append(c)
        return [x.to_dict() for x in vals[-max(1, min(limit, 500)):]]


candles = CandleBuilder()
