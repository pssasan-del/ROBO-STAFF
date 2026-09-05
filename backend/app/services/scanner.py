from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, asdict
from typing import Any

from app.services.broker import broker
from app.services.options import flatten_records
from app.services.journal import journal
from app.services.market_pipeline import candles

# Two manually-selected groups. Only one group is signal-scanned at a time.
GROUP_A = [
    "RELIANCE","HDFCBANK","ICICIBANK","SBIN","AXISBANK","KOTAKBANK","INDUSINDBK","BAJFINANCE","BAJAJFINSV",
    "HDFCLIFE","SBILIFE","INFY","TCS","HCLTECH","WIPRO","TECHM","LTIM","BHARTIARTL","ITC","HINDUNILVR",
    "NESTLEIND","BRITANNIA","TATACONSUM","ASIANPAINT","TITAN","MARUTI","M&M","TATAMOTORS","EICHERMOT",
    "BAJAJ-AUTO","HEROMOTOCO","TVSMOTOR","LT","ULTRACEMCO","GRASIM","ADANIENT","ADANIPORTS","NTPC",
    "POWERGRID","ONGC","COALINDIA","BPCL","IOC","TATASTEEL","JSWSTEEL",
]

GROUP_B = [
    "HINDALCO","SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","APOLLOHOSP","BEL","HAL","TRENT","DLF","JIOFIN",
    "SHRIRAMFIN","PFC","RECLTD","VEDL","ETERNAL","DMART","IRCTC","IRFC","ABB","SIEMENS","CUMMINSIND",
    "BOSCHLTD","PIDILITIND","HAVELLS","DABUR","MARICO","GODREJCP","COLPAL","UNITDSPR","INDIGO","NAUKRI",
    "LODHA","AMBUJACEM","ACC","SHREECEM","SRF","PIIND","UPL","BANKBARODA","CANBK","PNB","FEDERALBNK",
    "IDFCFIRSTB","AUBANK",
]

assert len(GROUP_A) == 45 and len(GROUP_B) == 45


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _token(row: dict[str, Any]) -> str | None:
    value = (row.get("instrument_token") or row.get("instrumentToken") or row.get("token")
             or row.get("pSymbol") or row.get("p_symbol"))
    return None if value in (None, "") else str(value)


def _segment(row: dict[str, Any], default: str = "nse_cm") -> str:
    return str(row.get("exchange_segment") or row.get("exchangeSegment") or row.get("segment") or default)


def _row_score(row: dict[str, Any], symbol: str) -> int:
    want = _norm(symbol)
    score = 0
    for key in ("trading_symbol", "tradingSymbol", "pTrdSymbol", "symbol", "name", "display_name"):
        value = _norm(row.get(key))
        if not value:
            continue
        if value == want or value == want + "EQ":
            score = max(score, 100)
        elif value.startswith(want):
            score = max(score, 80)
        elif want in value:
            score = max(score, 50)
    instrument_type = _norm(row.get("instrument_type") or row.get("instrumentType") or row.get("type"))
    if instrument_type in {"EQ", "EQUITY", "STOCK"}:
        score += 5
    return score


@dataclass(slots=True)
class ScannerInstrument:
    symbol: str
    exchange_segment: str
    instrument_token: str
    symbol_key: str


class ScannerController:
    def __init__(self) -> None:
        self.active_group: str | None = None
        self.resolved: list[ScannerInstrument] = []
        self.failed: list[dict[str, str]] = []
        self._scanner_subscription_ids: set[str] = set()
        self._lock = asyncio.Lock()

    @staticmethod
    def universe(group: str) -> list[str]:
        group = group.upper()
        if group == "A": return list(GROUP_A)
        if group == "B": return list(GROUP_B)
        raise ValueError("group must be A or B")

    async def _resolve_one(self, symbol: str) -> ScannerInstrument | None:
        raw = await broker.search("nse_cm", symbol)
        rows = [x for x in flatten_records(raw) if isinstance(x, dict) and _token(x)]
        if not rows:
            return None
        rows.sort(key=lambda row: _row_score(row, symbol), reverse=True)
        row = rows[0]
        token = _token(row)
        if not token:
            return None
        segment = _segment(row)
        # Stable readable key used for candles/signals independent of session token changes.
        symbol_key = f"{segment}|{symbol}"
        return ScannerInstrument(symbol, segment, token, symbol_key)

    async def _resolve_group(self, names: list[str]) -> tuple[list[ScannerInstrument], list[dict[str,str]]]:
        sem = asyncio.Semaphore(6)
        async def one(name: str):
            async with sem:
                try:
                    return name, await self._resolve_one(name), None
                except Exception as exc:
                    return name, None, str(exc)
        results = await asyncio.gather(*(one(name) for name in names))
        good: list[ScannerInstrument] = []
        failed: list[dict[str,str]] = []
        for name, item, err in results:
            if item is not None:
                good.append(item)
            else:
                failed.append({"symbol": name, "reason": err or "NOT_FOUND"})
        return good, failed

    async def _clear_previous(self) -> None:
        for subscription_id in list(self._scanner_subscription_ids):
            broker.subscriptions.pop(subscription_id, None)
        self._scanner_subscription_ids.clear()
        for item in self.resolved:
            broker.symbol_aliases.pop(f"{item.exchange_segment}|{item.instrument_token}", None)
        broker.signal_scan_keys.clear()
        self.resolved = []
        self.failed = []

    async def start(self, group: str) -> dict[str, Any]:
        if not broker.authenticated:
            raise RuntimeError("LOGIN_REQUIRED")
        group = group.upper()
        names = self.universe(group)
        async with self._lock:
            await self._clear_previous()
            good, failed = await self._resolve_group(names)
            for item in good:
                raw_key = f"{item.exchange_segment}|{item.instrument_token}"
                broker.symbol_aliases[raw_key] = item.symbol_key
                broker.signal_scan_keys.add(item.symbol_key)
                sub_id = f"{item.exchange_segment}|{item.instrument_token}|scrip"
                broker.subscriptions[sub_id] = (item.exchange_segment, item.instrument_token, "scrip")
                self._scanner_subscription_ids.add(sub_id)
            self.active_group = group
            self.resolved = good
            self.failed = failed
            await broker.recycle_market_stream()
            result = self.status()
            journal.add("scanner", "start", result)
            return result

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            await self._clear_previous()
            self.active_group = None
            if broker.authenticated:
                await broker.recycle_market_stream()
            result = self.status()
            journal.add("scanner", "stop", result)
            return result

    def status(self) -> dict[str, Any]:
        names = self.universe(self.active_group) if self.active_group else []
        minimum_history = 24
        history = []
        for item in self.resolved:
            rows = candles.get_history(item.symbol_key, 300, 100)
            closed_count = max(0, len(rows) - (1 if (item.symbol_key, 300) in candles.current else 0))
            history.append({"symbol": item.symbol, "symbol_key": item.symbol_key, "closed_5m": closed_count, "ready": closed_count >= minimum_history})
        ready_count = sum(1 for row in history if row["ready"])
        return {
            "active": self.active_group is not None,
            "group": self.active_group,
            "configured_count": len(names),
            "resolved_count": len(self.resolved),
            "failed_count": len(self.failed),
            "operational_count": len(self.resolved),
            "coverage_ok": len(self.resolved) >= 44,
            "ready_count": ready_count,
            "warming_count": max(0, len(history) - ready_count),
            "minimum_history": minimum_history,
            "history": history,
            "resolved": [asdict(x) for x in self.resolved],
            "failed": list(self.failed),
            "signal_scan_keys": sorted(broker.signal_scan_keys),
        }

    def groups(self) -> dict[str, Any]:
        return {"A": GROUP_A, "B": GROUP_B, "count_each": 45, "total": 90}

scanner_controller = ScannerController()
