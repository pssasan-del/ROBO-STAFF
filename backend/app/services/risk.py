from __future__ import annotations
from dataclasses import dataclass, asdict
from hashlib import sha256
import time
from typing import Any


@dataclass(slots=True)
class RiskConfig:
    trading_enabled: bool = False
    max_quantity: int = 5000
    max_order_value: float = 250000.0
    max_open_positions: int = 8
    max_daily_loss: float = 5000.0
    max_slippage_pct: float = 1.0
    duplicate_window_sec: int = 8


class RiskEngine:
    def __init__(self) -> None:
        self.config = RiskConfig()
        self._recent: dict[str, float] = {}

    def snapshot(self) -> dict[str, Any]:
        return asdict(self.config)

    def set_enabled(self, enabled: bool) -> None:
        self.config.trading_enabled = enabled

    def preflight(self, *, symbol: str, side: str, quantity: int, reference_price: float,
                  live_price: float | None, open_positions: int = 0, day_pnl: float = 0.0, reserve_duplicate: bool = True) -> dict[str, Any]:
        reasons: list[str] = []
        if not self.config.trading_enabled: reasons.append("TRADING_DISABLED")
        if quantity <= 0 or quantity > self.config.max_quantity: reasons.append("QUANTITY_LIMIT")
        if reference_price <= 0: reasons.append("INVALID_REFERENCE_PRICE")
        if reference_price > 0 and quantity * reference_price > self.config.max_order_value: reasons.append("ORDER_VALUE_LIMIT")
        if open_positions >= self.config.max_open_positions: reasons.append("OPEN_POSITION_LIMIT")
        if day_pnl <= -abs(self.config.max_daily_loss): reasons.append("DAILY_LOSS_LIMIT")
        if live_price and reference_price > 0:
            slip = abs(live_price - reference_price) / reference_price * 100
            if slip > self.config.max_slippage_pct: reasons.append("STALE_OR_MOVED_PRICE")
        fingerprint = sha256(f"{symbol}|{side}|{quantity}|{round(reference_price,2)}".encode()).hexdigest()[:20]
        now = time.time()
        prev = self._recent.get(fingerprint)
        if prev and now - prev < self.config.duplicate_window_sec: reasons.append("DUPLICATE_ORDER")
        if not reasons and reserve_duplicate:
            self._recent[fingerprint] = now
        return {"ok": not reasons, "reasons": reasons, "fingerprint": fingerprint}


risk_engine = RiskEngine()
