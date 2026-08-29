import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from config import logger, settings

IST = timezone(timedelta(hours=5, minutes=30))


class DeltaOptionsService:
    """Delta Exchange India PUBLIC options market-data only. No API key; no order methods."""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=8.0),
            headers={"Accept": "application/json", "User-Agent": "DeltaCryptoAIBot/5.0"},
        )

    @staticmethod
    def _num(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def parse_symbol(symbol: str):
        """Parse C-BTC-77500-290826 / P-ETH-2500-290826."""
        m = re.fullmatch(r"([CP])-([A-Z0-9]+)-([0-9]+(?:\.[0-9]+)?)-(\d{6})", str(symbol or '').upper())
        if not m:
            return None
        side, underlying, strike_s, expiry_s = m.groups()
        try:
            expiry = datetime.strptime(expiry_s, "%d%m%y").date()
            strike = float(strike_s)
        except ValueError:
            return None
        return {
            "side": "CE" if side == "C" else "PE",
            "underlying": underlying,
            "strike": strike,
            "expiry": expiry,
        }

    @staticmethod
    def _normalize_expiry(expiry: Optional[str]) -> Optional[str]:
        if not expiry:
            return None
        raw = expiry.strip()
        for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d %b %Y", "%d %B %Y"):
            try:
                d = datetime.strptime(raw, fmt).date()
                return d.strftime("%d-%m-%Y")
            except ValueError:
                pass
        return None

    async def get_chain(self, underlying: str, expiry: Optional[str] = None):
        underlying = underlying.upper()
        if underlying not in {"BTC", "ETH"}:
            raise ValueError("Delta India options connector currently supports BTC and ETH")
        params = {
            "contract_types": "call_options,put_options",
            "underlying_asset_symbols": underlying,
        }
        exp = self._normalize_expiry(expiry)
        if exp:
            params["expiry_date"] = exp
        url = f"{settings.DELTA_REST_BASE}/v2/tickers"
        logger.info("[DELTA_OPTIONS] GET chain underlying=%s expiry=%s", underlying, exp or "AUTO")
        try:
            r = await self.client.get(url, params=params)
        except Exception as exc:
            logger.warning("[DELTA_OPTIONS] connection failed: %s", exc)
            raise RuntimeError(f"Delta connection error: {type(exc).__name__}") from exc
        if r.status_code != 200:
            body = r.text[:1000].replace("\n", " ")
            logger.warning("[DELTA_OPTIONS] HTTP %s body=%s", r.status_code, body)
            raise RuntimeError(f"Delta HTTP {r.status_code}: {body[:300]}")
        try:
            obj = r.json()
        except Exception as exc:
            raise RuntimeError("Delta returned invalid JSON") from exc
        if not obj.get("success"):
            raise RuntimeError(f"Delta API error: {obj.get('error') or obj.get('result') or obj}")
        rows = obj.get("result") or []
        if not isinstance(rows, list):
            raise RuntimeError("Delta option-chain response was not a list")
        logger.info("[DELTA_OPTIONS] chain rows=%s underlying=%s", len(rows), underlying)
        return rows

    def _snapshot(self, row: dict):
        meta = self.parse_symbol(row.get("symbol")) or {}
        quotes = row.get("quotes") if isinstance(row.get("quotes"), dict) else {}
        greeks = row.get("greeks") if isinstance(row.get("greeks"), dict) else {}
        close = self._num(row.get("close"))
        mark = self._num(row.get("mark_price"))
        bid = self._num(quotes.get("best_bid"))
        ask = self._num(quotes.get("best_ask"))
        # For "premium/rate", prefer actual last-trade close, then mark, then midpoint.
        premium = close if close is not None else mark
        if premium is None and bid is not None and ask is not None:
            premium = (bid + ask) / 2
        return {
            "symbol": row.get("symbol"),
            "side": meta.get("side"),
            "underlying": meta.get("underlying"),
            "strike": self._num(row.get("strike_price")) or meta.get("strike"),
            "expiry": meta.get("expiry").isoformat() if meta.get("expiry") else None,
            "premium": premium,
            "last_price": close,
            "mark_price": mark,
            "spot_price": self._num(row.get("spot_price")),
            "best_bid": bid,
            "best_ask": ask,
            "bid_iv": self._num(quotes.get("bid_iv")),
            "ask_iv": self._num(quotes.get("ask_iv")),
            "oi": self._num(row.get("oi")),
            "volume": self._num(row.get("volume")),
            "delta": self._num(greeks.get("delta")),
            "gamma": self._num(greeks.get("gamma")),
            "theta": self._num(greeks.get("theta")),
            "vega": self._num(greeks.get("vega")),
            "rho": self._num(greeks.get("rho")),
            "timestamp": row.get("timestamp"),
        }

    async def get_strike_snapshot(self, underlying: str, strike: float, expiry: Optional[str] = None):
        rows = await self.get_chain(underlying, expiry)
        today = datetime.now(IST).date()
        parsed = []
        for row in rows:
            meta = self.parse_symbol(row.get("symbol"))
            if not meta or meta["underlying"] != underlying.upper() or meta["expiry"] < today:
                continue
            parsed.append((row, meta))
        if not parsed:
            raise RuntimeError(f"No live {underlying.upper()} option contracts returned by Delta")

        # If expiry wasn't requested, select the nearest expiry that contains option contracts.
        if not expiry:
            nearest_expiry = min(meta["expiry"] for _, meta in parsed)
            parsed = [(r, m) for r, m in parsed if m["expiry"] == nearest_expiry]
        else:
            # Delta already filtered where supported, but protect against mixed responses.
            normalized = self._normalize_expiry(expiry)
            if normalized:
                wanted = datetime.strptime(normalized, "%d-%m-%Y").date()
                exact_exp = [(r, m) for r, m in parsed if m["expiry"] == wanted]
                if exact_exp:
                    parsed = exact_exp

        strikes = sorted({m["strike"] for _, m in parsed})
        if not strikes:
            raise RuntimeError("Delta returned no strikes for selected expiry")
        exact = [x for x in strikes if abs(x - float(strike)) < 1e-9]
        selected_strike = exact[0] if exact else min(strikes, key=lambda x: abs(x - float(strike)))
        strike_exact = bool(exact)

        chosen = [(r, m) for r, m in parsed if abs(m["strike"] - selected_strike) < 1e-9]
        ce = next((self._snapshot(r) for r, m in chosen if m["side"] == "CE"), None)
        pe = next((self._snapshot(r) for r, m in chosen if m["side"] == "PE"), None)
        expiry_date = chosen[0][1]["expiry"].isoformat() if chosen else None
        spot = next((x.get("spot_price") for x in (ce, pe) if x and x.get("spot_price") is not None), None)

        logger.info(
            "[DELTA_OPTIONS] snapshot %s requested_strike=%s selected=%s exact=%s expiry=%s CE=%s PE=%s",
            underlying.upper(), strike, selected_strike, strike_exact, expiry_date,
            ce.get("premium") if ce else None, pe.get("premium") if pe else None,
        )
        return {
            "underlying": underlying.upper(),
            "requested_strike": float(strike),
            "selected_strike": selected_strike,
            "strike_exact": strike_exact,
            "expiry": expiry_date,
            "spot_price": spot,
            "ce": ce,
            "pe": pe,
            "source": "Delta Exchange India public options ticker API",
        }


delta_options_service = DeltaOptionsService()
