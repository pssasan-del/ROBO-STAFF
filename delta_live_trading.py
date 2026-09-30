"""Delta India LIVE trading module — gated, confirm-required, risk-limited.

Default state: DISABLED.
Requires ALL of:
  LIVE_TRADING_ENABLED=true
  DELTA_API_KEY + DELTA_API_SECRET (trading-scoped key)
  Explicit Telegram CONFIRM on each order

Never auto-fires on signal alone. Signal engine remains research path;
this module only places after human confirmation + risk preflight.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import httpx

from config import logger, settings


@dataclass
class LiveRiskConfig:
    trading_enabled: bool = False
    max_contracts_per_order: int = 5
    max_order_value_usd: float = 500.0
    max_open_positions: int = 2
    max_daily_loss_usd: float = 150.0
    max_slippage_pct: float = 2.5
    allocation_pct: float = 0.08  # 8% of available balance model
    duplicate_window_sec: int = 12
    min_score_for_live: int = 66  # STRONG+


@dataclass
class LiveOrderRequest:
    product_id: int
    symbol: str
    side: str  # buy | sell
    size: int
    order_type: str  # limit_order | market_order
    limit_price: Optional[float] = None
    client_order_id: Optional[str] = None
    reduce_only: bool = False
    time_in_force: str = "gtc"
    # signal context
    underlying: str = ""
    direction: str = ""
    setup_id: str = ""
    score: int = 0
    entry_ref: float = 0.0
    sl: float = 0.0
    t1: float = 0.0
    t2: float = 0.0
    t3: float = 0.0


@dataclass
class LiveRiskState:
    day_key: str = ""
    day_realized_pnl: float = 0.0
    open_count: int = 0
    recent_fps: dict = field(default_factory=dict)
    last_order_at: float = 0.0
    last_order_id: Optional[str] = None
    last_error: str = ""


class DeltaLiveTradingService:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0))
        self.config = LiveRiskConfig(
            trading_enabled=bool(getattr(settings, "LIVE_TRADING_ENABLED", False)),
            max_contracts_per_order=int(getattr(settings, "LIVE_MAX_CONTRACTS", 5)),
            max_order_value_usd=float(getattr(settings, "LIVE_MAX_ORDER_USD", 500.0)),
            max_open_positions=int(getattr(settings, "LIVE_MAX_OPEN", 2)),
            max_daily_loss_usd=float(getattr(settings, "LIVE_MAX_DAILY_LOSS_USD", 150.0)),
            max_slippage_pct=float(getattr(settings, "LIVE_MAX_SLIPPAGE_PCT", 2.5)),
            allocation_pct=float(getattr(settings, "LIVE_ALLOCATION_PCT", 0.08)),
            min_score_for_live=int(getattr(settings, "LIVE_MIN_SCORE", 66)),
        )
        self.state = LiveRiskState()
        self._pending_confirm: dict[str, dict[str, Any]] = {}

    # ── auth ──────────────────────────────────────────────────────────
    @property
    def credentials_ok(self) -> bool:
        return bool(settings.DELTA_API_KEY and settings.DELTA_API_SECRET)

    def _headers(self, method: str, path: str, query_string: str = "", payload: str = "") -> dict[str, str]:
        if not self.credentials_ok:
            raise RuntimeError("Delta trading credentials not configured")
        timestamp = str(int(time.time()))
        signature_data = f"{method}{timestamp}{path}{query_string}{payload}"
        signature = hmac.new(
            settings.DELTA_API_SECRET.encode("utf-8"),
            signature_data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "ROBO-STAFF-live/4.2",
            "api-key": settings.DELTA_API_KEY,
            "signature": signature,
            "timestamp": timestamp,
        }

    async def _request(self, method: str, path: str, payload: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        body = ""
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":"))
        query = ""
        if params:
            query = "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        url = f"{settings.DELTA_REST_BASE}{path}{query}"
        headers = self._headers(method, path, query if params else "", body)
        r = await self.client.request(method, url, headers=headers, content=body if body else None)
        try:
            obj = r.json()
        except Exception:
            obj = {"success": False, "error": r.text[:400]}
        if r.status_code >= 400 or not obj.get("success", r.status_code < 400):
            err = obj.get("error") or obj
            self.state.last_error = str(err)[:240]
            logger.warning("[LIVE] %s %s failed %s %s", method, path, r.status_code, err)
            raise RuntimeError(f"Delta {method} {path} HTTP {r.status_code}: {err}")
        return obj

    # ── risk ──────────────────────────────────────────────────────────
    def set_enabled(self, enabled: bool) -> None:
        self.config.trading_enabled = bool(enabled)
        logger.info("[LIVE] trading_enabled=%s", self.config.trading_enabled)

    def snapshot(self) -> dict[str, Any]:
        return {
            "trading_enabled": self.config.trading_enabled,
            "credentials": self.credentials_ok,
            "min_score": self.config.min_score_for_live,
            "max_contracts": self.config.max_contracts_per_order,
            "max_order_usd": self.config.max_order_value_usd,
            "max_open": self.config.max_open_positions,
            "max_daily_loss_usd": self.config.max_daily_loss_usd,
            "allocation_pct": self.config.allocation_pct,
            "day_pnl": self.state.day_realized_pnl,
            "open_count": self.state.open_count,
            "last_order_id": self.state.last_order_id,
            "last_error": self.state.last_error,
        }

    def _roll_day(self) -> None:
        key = time.strftime("%Y-%m-%d", time.gmtime())
        if self.state.day_key != key:
            self.state.day_key = key
            self.state.day_realized_pnl = 0.0

    def preflight(self, req: LiveOrderRequest, *, live_price: Optional[float] = None, available_usd: float = 0.0) -> dict[str, Any]:
        self._roll_day()
        reasons: list[str] = []
        if not self.config.trading_enabled:
            reasons.append("TRADING_DISABLED")
        if not self.credentials_ok:
            reasons.append("NO_CREDENTIALS")
        if req.score < self.config.min_score_for_live:
            reasons.append(f"SCORE_BELOW_{self.config.min_score_for_live}")
        if req.size <= 0 or req.size > self.config.max_contracts_per_order:
            reasons.append("SIZE_LIMIT")
        notional = req.size * float(req.limit_price or req.entry_ref or 0)
        if notional > self.config.max_order_value_usd:
            reasons.append("ORDER_VALUE_LIMIT")
        if self.state.open_count >= self.config.max_open_positions:
            reasons.append("OPEN_POSITION_LIMIT")
        if self.state.day_realized_pnl <= -abs(self.config.max_daily_loss_usd):
            reasons.append("DAILY_LOSS_LIMIT")
        if live_price and req.entry_ref > 0:
            slip = abs(live_price - req.entry_ref) / req.entry_ref * 100.0
            if slip > self.config.max_slippage_pct:
                reasons.append("SLIPPAGE")
        fp = hashlib.sha256(
            f"{req.symbol}|{req.side}|{req.size}|{round(req.entry_ref, 4)}".encode()
        ).hexdigest()[:16]
        now = time.time()
        prev = self.state.recent_fps.get(fp)
        if prev and now - prev < self.config.duplicate_window_sec:
            reasons.append("DUPLICATE")
        return {"ok": not reasons, "reasons": reasons, "fingerprint": fp, "notional": notional}

    def size_from_balance(self, available_usd: float, premium: float) -> int:
        if premium <= 0 or available_usd <= 0:
            return 1
        budget = available_usd * self.config.allocation_pct
        n = int(math.floor(budget / premium))
        return max(1, min(n, self.config.max_contracts_per_order))

    # ── product lookup ────────────────────────────────────────────────
    async def resolve_product_id(self, symbol: str) -> int:
        """Resolve product_id from public tickers by symbol."""
        path = "/v2/tickers"
        r = await self.client.get(
            f"{settings.DELTA_REST_BASE}{path}",
            params={"contract_types": "call_options,put_options"},
            timeout=12.0,
        )
        if r.status_code != 200:
            raise RuntimeError(f"ticker lookup HTTP {r.status_code}")
        obj = r.json()
        rows = obj.get("result") or []
        sym = str(symbol or "").upper()
        for row in rows:
            if str(row.get("symbol") or "").upper() == sym:
                pid = row.get("product_id") or row.get("id")
                if pid is not None:
                    return int(pid)
        raise RuntimeError(f"product_id not found for {symbol}")

    # ── order APIs ────────────────────────────────────────────────────
    async def place_order(self, req: LiveOrderRequest, *, fingerprint: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "product_id": int(req.product_id),
            "size": int(req.size),
            "side": req.side.lower(),
            "order_type": req.order_type,
            "time_in_force": req.time_in_force,
            "reduce_only": "true" if req.reduce_only else "false",
        }
        if req.order_type == "limit_order":
            if req.limit_price is None or req.limit_price <= 0:
                raise RuntimeError("limit_price required for limit_order")
            payload["limit_price"] = str(round(float(req.limit_price), 8))
        if req.client_order_id:
            payload["client_order_id"] = str(req.client_order_id)[:36]

        obj = await self._request("POST", "/v2/orders", payload=payload)
        result = obj.get("result") or {}
        oid = str(result.get("id") or result.get("order_id") or "")
        self.state.last_order_id = oid
        self.state.last_order_at = time.time()
        self.state.open_count = min(self.state.open_count + 1, self.config.max_open_positions)
        if fingerprint:
            self.state.recent_fps[fingerprint] = time.time()
        logger.info(
            "[LIVE] ORDER PLACED id=%s symbol=%s side=%s size=%s type=%s",
            oid, req.symbol, req.side, req.size, req.order_type,
        )
        return {"ok": True, "order": result, "order_id": oid}

    async def cancel_order(self, order_id: int | str) -> dict[str, Any]:
        path = f"/v2/orders/{order_id}"
        obj = await self._request("DELETE", path)
        return {"ok": True, "result": obj.get("result")}

    async def get_open_orders(self, product_id: Optional[int] = None) -> list:
        params = {"state": "open"}
        if product_id:
            params["product_id"] = str(product_id)
        obj = await self._request("GET", "/v2/orders", params=params)
        rows = obj.get("result") or []
        return rows if isinstance(rows, list) else []

    async def get_positions(self) -> list:
        obj = await self._request("GET", "/v2/positions")
        rows = obj.get("result") or []
        return rows if isinstance(rows, list) else []

    # ── confirm queue ─────────────────────────────────────────────────
    def queue_confirm(self, key: str, payload: dict[str, Any], ttl_sec: int = 90) -> None:
        self._pending_confirm[key] = {"payload": payload, "expires": time.time() + ttl_sec}

    def pop_confirm(self, key: str) -> Optional[dict[str, Any]]:
        item = self._pending_confirm.pop(key, None)
        if not item:
            return None
        if time.time() > float(item.get("expires", 0)):
            return None
        return item.get("payload")

    def build_ticket_from_candidate(self, candidate, *, product_id: int, size: int, use_limit: bool = True) -> LiveOrderRequest:
        action = str(getattr(candidate, "action", "") or "").upper()
        side = "buy" if "BUY" in action else "sell"
        entry = float(getattr(candidate, "premium", 0) or 0)
        market = getattr(candidate, "market", None) or {}
        ask = float(market.get("ask") or entry)
        bid = float(market.get("bid") or entry)
        limit_px = ask if side == "buy" else bid
        return LiveOrderRequest(
            product_id=int(product_id),
            symbol=str(getattr(candidate, "option_symbol", "")),
            side=side,
            size=int(size),
            order_type="limit_order" if use_limit else "market_order",
            limit_price=limit_px if use_limit else None,
            client_order_id=f"rs{int(time.time()) % 10_000_000}",
            underlying=str(getattr(candidate, "underlying", "")),
            direction=str(getattr(candidate, "direction", "")),
            setup_id=str(getattr(candidate, "setup_id", "")),
            score=int(getattr(candidate, "adjusted_score", getattr(candidate, "score", 0)) or 0),
            entry_ref=entry,
            sl=float(getattr(candidate, "sl", 0) or 0),
            t1=float(getattr(candidate, "t1", 0) or 0),
            t2=float(getattr(candidate, "t2", 0) or 0),
            t3=float(getattr(candidate, "t3", 0) or 0),
        )

    def format_confirm_card(self, req: LiveOrderRequest, preflight: dict) -> str:
        status = "✅ PREFLIGHT OK" if preflight.get("ok") else "⛔ BLOCKED: " + ", ".join(preflight.get("reasons") or [])
        return (
            f"🤖 *LIVE ORDER CONFIRM*\n"
            f"Status: {status}\n"
            f"Contract: `{req.symbol}`\n"
            f"Side: *{req.side.upper()}* | Size: *{req.size}*\n"
            f"Type: `{req.order_type}` @ `{req.limit_price or 'MKT'}`\n"
            f"Score: {req.score} | {req.underlying} {req.direction}\n"
            f"SL `{req.sl}` · T1 `{req.t1}` · T2 `{req.t2}` · T3 `{req.t3}`\n"
            f"Notional ~ `${preflight.get('notional', 0):.2f}`\n"
            f"Setup: `{req.setup_id}`\n"
            f"⏱ Confirm within 90s or expires.\n"
            f"🔒 Only fires after you press CONFIRM."
        )


delta_live = DeltaLiveTradingService()
