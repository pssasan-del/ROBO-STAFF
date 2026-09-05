from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Awaitable, Callable

from app.services.risk import risk_engine


class ExecutionState(str, Enum):
    CONFIRMATION_PENDING = "CONFIRMATION_PENDING"
    SUBMITTING = "SUBMITTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


@dataclass(slots=True)
class ExecutionIntent:
    intent_id: str
    confirmation_token: str
    created_at: float
    expires_at: float
    order: dict[str, Any]
    symbol: str
    side: str
    quantity: int
    reference_price: float
    live_price: float | None
    signal_id: str | None = None
    state: ExecutionState = ExecutionState.CONFIRMATION_PENDING
    broker_order_id: str | None = None
    broker_status: str | None = None
    average_price: float | None = None
    filled_quantity: int = 0
    error: str | None = None
    submitted_at: float | None = None
    updated_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        # Never expose the reusable secret after creation/status lookup.
        d.pop("confirmation_token", None)
        return d


class ExecutionEngine:
    def __init__(self, confirmation_ttl_sec: int = 20) -> None:
        self.armed = False
        self.confirmation_ttl_sec = confirmation_ttl_sec
        self.intents: dict[str, ExecutionIntent] = {}
        self._token_to_intent: dict[str, str] = {}
        self._broker_to_intent: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def snapshot(self) -> dict[str, Any]:
        return {
            "armed": self.armed,
            "confirmation_ttl_sec": self.confirmation_ttl_sec,
            "pending_confirmations": sum(1 for x in self.intents.values() if x.state == ExecutionState.CONFIRMATION_PENDING),
            "tracked_executions": len(self.intents),
        }

    def arm(self, enabled: bool) -> dict[str, Any]:
        self.armed = enabled
        if not enabled:
            self.invalidate_all_confirmations()
        return self.snapshot()

    def invalidate_all_confirmations(self) -> None:
        for intent in self.intents.values():
            if intent.state == ExecutionState.CONFIRMATION_PENDING:
                intent.state = ExecutionState.CANCELLED
                intent.error = "EXECUTION_DISARMED"
                intent.updated_at = time.time()
        self._token_to_intent.clear()

    def create_intent(
        self,
        *,
        order: dict[str, Any],
        symbol: str,
        side: str,
        quantity: int,
        reference_price: float,
        live_price: float | None,
        open_positions: int = 0,
        day_pnl: float = 0.0,
        signal_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.armed:
            return {"ok": False, "reasons": ["EXECUTION_NOT_ARMED"]}
        check = risk_engine.preflight(
            symbol=symbol,
            side=side,
            quantity=quantity,
            reference_price=reference_price,
            live_price=live_price,
            open_positions=open_positions,
            day_pnl=day_pnl,
            reserve_duplicate=False,
        )
        if not check["ok"]:
            return {"ok": False, "reasons": check["reasons"], "risk": check}
        now = time.time()
        iid = secrets.token_hex(8)
        token = secrets.token_urlsafe(24)
        intent = ExecutionIntent(
            intent_id=iid,
            confirmation_token=token,
            created_at=now,
            expires_at=now + self.confirmation_ttl_sec,
            order=order,
            symbol=symbol,
            side=side.upper(),
            quantity=quantity,
            reference_price=reference_price,
            live_price=live_price,
            signal_id=signal_id,
        )
        self.intents[iid] = intent
        self._token_to_intent[token] = iid
        return {
            "ok": True,
            "intent_id": iid,
            "confirmation_token": token,
            "expires_at": intent.expires_at,
            "summary": {
                "symbol": symbol,
                "side": side.upper(),
                "quantity": quantity,
                "reference_price": reference_price,
                "live_price": live_price,
                "order_type": order.get("order_type"),
                "product": order.get("product"),
            },
        }

    async def confirm(
        self,
        *,
        intent_id: str,
        confirmation_token: str,
        live_price: float | None,
        open_positions: int,
        day_pnl: float,
        submitter: Callable[..., Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        async with self._lock:
            intent = self.intents.get(intent_id)
            if intent is None:
                return {"ok": False, "reasons": ["INTENT_NOT_FOUND"]}
            if not self.armed:
                return {"ok": False, "reasons": ["EXECUTION_NOT_ARMED"]}
            if intent.state != ExecutionState.CONFIRMATION_PENDING:
                return {"ok": False, "reasons": ["INTENT_ALREADY_USED"], "execution": intent.to_dict()}
            if time.time() > intent.expires_at:
                intent.state = ExecutionState.CANCELLED
                intent.error = "CONFIRMATION_EXPIRED"
                self._token_to_intent.pop(intent.confirmation_token, None)
                return {"ok": False, "reasons": ["CONFIRMATION_EXPIRED"], "execution": intent.to_dict()}
            if not secrets.compare_digest(intent.confirmation_token, confirmation_token):
                return {"ok": False, "reasons": ["INVALID_CONFIRMATION_TOKEN"]}

            check = risk_engine.preflight(
                symbol=intent.symbol,
                side=intent.side,
                quantity=intent.quantity,
                reference_price=intent.reference_price,
                live_price=live_price,
                open_positions=open_positions,
                day_pnl=day_pnl,
                reserve_duplicate=True,
            )
            if not check["ok"]:
                return {"ok": False, "reasons": check["reasons"], "risk": check}

            # Token becomes unusable before the external broker call.
            self._token_to_intent.pop(intent.confirmation_token, None)
            intent.state = ExecutionState.SUBMITTING
            intent.submitted_at = time.time()
            intent.updated_at = intent.submitted_at

        try:
            response = await submitter(**intent.order)
            order_id = self._extract_order_id(response)
            if self._looks_like_error(response):
                intent.state = ExecutionState.ERROR
                intent.error = self._error_text(response)
            else:
                intent.state = ExecutionState.ACKNOWLEDGED
                intent.broker_order_id = order_id
                if order_id:
                    self._broker_to_intent[order_id] = intent.intent_id
            intent.updated_at = time.time()
            return {"ok": intent.state != ExecutionState.ERROR, "execution": intent.to_dict(), "broker_response": response}
        except Exception as exc:
            intent.state = ExecutionState.ERROR
            intent.error = str(exc)
            intent.updated_at = time.time()
            return {"ok": False, "reasons": ["BROKER_SUBMIT_ERROR"], "execution": intent.to_dict()}

    def on_order_update(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        order_id = self._first(data, "order_id", "nOrdNo")
        if not order_id:
            return None
        intent_id = self._broker_to_intent.get(str(order_id))
        if not intent_id:
            return None
        intent = self.intents[intent_id]
        status = str(self._first(data, "order_status", "ordSt") or "").lower().strip()
        intent.broker_status = status or intent.broker_status
        intent.average_price = self._to_float(self._first(data, "average_price", "avgPrc")) or intent.average_price
        intent.filled_quantity = self._to_int(self._first(data, "filled_quantity", "fldQty"), intent.filled_quantity)
        intent.updated_at = time.time()
        if status == "complete":
            intent.state = ExecutionState.FILLED
        elif status == "rejected":
            intent.state = ExecutionState.REJECTED
        elif status == "cancelled":
            intent.state = ExecutionState.CANCELLED
        elif intent.filled_quantity and intent.filled_quantity < intent.quantity:
            intent.state = ExecutionState.PARTIAL
        elif status in {"open", "open pending", "validation pending", "put order req received", "modified"}:
            intent.state = ExecutionState.OPEN
        return intent.to_dict()

    def get(self, intent_id: str) -> dict[str, Any] | None:
        x = self.intents.get(intent_id)
        return x.to_dict() if x else None

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        vals = sorted(self.intents.values(), key=lambda x: x.created_at, reverse=True)
        return [x.to_dict() for x in vals[:max(1, min(limit, 500))]]

    @staticmethod
    def _extract_order_id(payload: Any) -> str | None:
        if isinstance(payload, dict):
            for k in ("nOrdNo", "order_id", "orderId", "nestOrderNumber"):
                v = payload.get(k)
                if v not in (None, ""):
                    return str(v)
            for v in payload.values():
                found = ExecutionEngine._extract_order_id(v)
                if found:
                    return found
        elif isinstance(payload, list):
            for v in payload:
                found = ExecutionEngine._extract_order_id(v)
                if found:
                    return found
        return None

    @staticmethod
    def _looks_like_error(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        return any(k in payload for k in ("Error", "error", "Error Message"))

    @staticmethod
    def _error_text(payload: dict[str, Any]) -> str:
        for k in ("Error", "error", "Error Message", "message"):
            if k in payload:
                return str(payload[k])
        return "UNKNOWN_BROKER_ERROR"

    @staticmethod
    def _first(d: dict[str, Any], *keys: str) -> Any:
        for k in keys:
            if k in d and d[k] is not None:
                return d[k]
        return None

    @staticmethod
    def _to_float(v: Any) -> float | None:
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(v: Any, default: int = 0) -> int:
        try:
            return int(float(v)) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default


execution_engine = ExecutionEngine()
