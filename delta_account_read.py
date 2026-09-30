"""Read-only authenticated Delta India account helpers.

This module intentionally exposes wallet/balance reads only. It contains no order,
leverage, modify, cancel, or position-management methods.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import httpx

from config import settings, logger


class DeltaAccountReadService:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=8.0))

    @property
    def configured(self) -> bool:
        return bool(settings.DELTA_API_KEY and settings.DELTA_API_SECRET)

    def _headers(self, method: str, path: str, query_string: str = "", payload: str = "") -> dict[str, str]:
        if not self.configured:
            raise RuntimeError("Delta private API credentials are not configured")
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
            "User-Agent": "ROBO-STAFF-readonly/1.0",
            "api-key": settings.DELTA_API_KEY,
            "signature": signature,
            "timestamp": timestamp,
        }

    async def get_balances(self) -> list[dict[str, Any]]:
        path = "/v2/wallet/balances"
        r = await self.client.get(
            f"{settings.DELTA_REST_BASE}{path}",
            headers=self._headers("GET", path),
        )
        if r.status_code != 200:
            logger.warning("[DELTA_ACCOUNT] balance HTTP %s %s", r.status_code, r.text[:300])
            raise RuntimeError(f"Delta balance HTTP {r.status_code}")
        obj = r.json()
        if not obj.get("success"):
            raise RuntimeError(f"Delta balance API error: {obj.get('error') or 'unknown error'}")
        rows = obj.get("result") or []
        if not isinstance(rows, list):
            raise RuntimeError("Delta balance response malformed")
        return rows

    @staticmethod
    def _num(v):
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    async def balance_text(self) -> str:
        rows = await self.get_balances()
        useful = []
        for row in rows:
            asset = str(row.get("asset_symbol") or row.get("symbol") or row.get("asset") or "").upper()
            available = self._num(row.get("available_balance"))
            balance = self._num(row.get("balance"))
            if not asset:
                continue
            if abs(available) < 1e-12 and abs(balance) < 1e-12:
                continue
            useful.append((asset, available, balance))
        if not useful:
            return "💰 *DELTA BALANCE*\nNo non-zero wallet balances returned."
        lines = ["💰 *DELTA BALANCE*"]
        for asset, available, balance in useful[:12]:
            lines.append(f"{asset}: Available *{available:,.4f}* | Balance `{balance:,.4f}`")
        lines.append("\n🔒 Read-only account fetch. No order is placed.")
        return "\n".join(lines)


delta_account_read_service = DeltaAccountReadService()
