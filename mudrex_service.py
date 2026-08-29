import asyncio
import json
import time
from typing import Dict, List, Optional
from urllib.parse import urlencode

import httpx

from config import settings, logger


class MudrexService:
    """Mudrex PUBLIC read-only market data only. No API secret and no order methods."""

    # Mudrex REST uses unusual minute enum names: 5t/10t/15t/30t.
    # Keep the rest of our engine readable by accepting familiar aliases.
    AGGREGATION_MAP = {
        "1m": "1m",
        "3m": "3t",
        "3t": "3t",
        "5m": "5t",
        "5t": "5t",
        "10m": "10t",
        "10t": "10t",
        "15m": "15t",
        "15t": "15t",
        "30m": "30t",
        "30t": "30t",
        "1h": "1h",
        "4h": "4h",
        "6h": "6h",
        "12h": "12h",
        "1d": "1d",
        "1w": "1w",
        "1mo": "1mth",
        "1mth": "1mth",
    }

    AGGREGATION_SECONDS = {
        "1m": 60,
        "3t": 180,
        "5t": 300,
        "10t": 600,
        "15t": 900,
        "30t": 1800,
        "1h": 3600,
        "4h": 14400,
        "6h": 21600,
        "12h": 43200,
        "1d": 86400,
        "1w": 604800,
        # Approximation used only to size the requested lookback window.
        "1mth": 2678400,
    }

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=8.0),
            headers={"User-Agent": "MudrexCryptoSignalBot/2.0", "Accept": "application/json"},
        )
        self.live: Dict[str, dict] = {}
        self.ws_connected = False
        self.ws_last_message_at: Optional[float] = None
        self.last_rest_ok_at: Optional[float] = None
        self.last_error: Optional[str] = None

    @staticmethod
    def rest_symbol(symbol: str) -> str:
        s = symbol.upper().replace("/", "")
        if s.endswith("USDT"):
            return s[:-4] + "/USDT"
        return s

    @classmethod
    def api_aggregation(cls, aggregation: str) -> str:
        key = str(aggregation).strip().lower()
        if key not in cls.AGGREGATION_MAP:
            raise ValueError(f"Unsupported Mudrex aggregation alias: {aggregation}")
        return cls.AGGREGATION_MAP[key]

    @staticmethod
    def _normalize_candle(candle):
        if not isinstance(candle, (list, tuple)) or len(candle) < 6:
            return None
        try:
            return [
                int(float(candle[0])),
                float(candle[1]),
                float(candle[2]),
                float(candle[3]),
                float(candle[4]),
                float(candle[5]),
            ]
        except (TypeError, ValueError):
            return None

    @classmethod
    def _parse_kline_response(cls, obj: dict, limit: int) -> Dict[str, List[list]]:
        if not isinstance(obj, dict):
            raise RuntimeError("Mudrex returned a non-object response")
        if obj.get("success") is False:
            raise RuntimeError(f"Mudrex API error: {obj.get('errors') or obj}")

        data = obj.get("data") if isinstance(obj.get("data"), dict) else obj
        ticks = data.get("asset_ticks") if isinstance(data, dict) else None
        if not isinstance(ticks, dict):
            raise RuntimeError("Mudrex response missing data.asset_ticks")

        out: Dict[str, List[list]] = {}
        for key, values in ticks.items():
            norm = str(key).replace("/", "").upper()
            parsed = []
            if isinstance(values, list):
                for row in values:
                    candle = cls._normalize_candle(row)
                    if candle is not None:
                        parsed.append(candle)
            parsed.sort(key=lambda x: x[0])
            out[norm] = parsed[-limit:]
        return out

    async def get_klines(
        self,
        symbols: List[str],
        aggregation: str = "5m",
        limit: int = 120,
        end_time: Optional[int] = None,
    ) -> Dict[str, List[list]]:
        api_agg = self.api_aggregation(aggregation)
        limit = max(2, min(int(limit), 1440))
        end = int(end_time or time.time())
        seconds = self.AGGREGATION_SECONDS[api_agg]
        # Add a small buffer so a boundary/incomplete candle does not leave us short.
        start = end - (limit + 5) * seconds
        rest_assets = [self.rest_symbol(s) for s in symbols[:25]]
        assets = ",".join(rest_assets)

        params = {
            "assets": assets,
            "aggregation": api_agg,
            "start_time": str(start),
            "end_time": str(end),
        }
        # Build the query ourselves to keep BTC/USDT and comma separators literal,
        # matching Mudrex's documented examples exactly.
        query = urlencode(params, safe="/,")
        url = f"{settings.MUDREX_REST_BASE}/kline?{query}"
        logger.info(
            "[MUDREX_REST] GET /kline aggregation=%s(requested=%s) assets=%s",
            api_agg,
            aggregation,
            assets,
        )

        try:
            r = await self.client.get(url)
        except Exception as exc:
            self.last_error = f"REST connection error: {type(exc).__name__}: {exc}"
            logger.warning("[MUDREX_REST] connection failed: %s", self.last_error)
            raise RuntimeError(self.last_error) from exc

        if r.status_code != 200:
            body = r.text[:1200].replace("\n", " ")
            self.last_error = f"HTTP {r.status_code}: {body}"
            logger.warning("[MUDREX_REST] HTTP ERROR url=%s body=%s", str(r.request.url), body)
            raise RuntimeError(f"Mudrex HTTP {r.status_code}: {body[:400]}")

        try:
            obj = r.json()
        except Exception as exc:
            body = r.text[:800].replace("\n", " ")
            self.last_error = f"Invalid JSON: {body}"
            logger.warning("[MUDREX_REST] invalid JSON body=%s", body)
            raise RuntimeError("Mudrex returned invalid JSON") from exc

        try:
            out = self._parse_kline_response(obj, limit)
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("[MUDREX_REST] parse/API error response=%s", json.dumps(obj)[:1200])
            raise

        self.last_rest_ok_at = time.time()
        self.last_error = None
        counts = {k: len(v) for k, v in out.items()}
        logger.info("[MUDREX_REST] OK candles=%s", counts)
        return out

    async def latest_price(self, symbol: str) -> dict:
        s = symbol.upper().replace("/", "")
        cached = self.live.get(s)
        if cached and time.time() - cached.get("received_at", 0) < 30:
            return {
                "symbol": s,
                "price": cached.get("price"),
                "mark_price": cached.get("mark_price"),
                "source": "Mudrex WebSocket ticker@5s",
                "timestamp": cached.get("timestamp"),
            }

        # Public REST fallback: no credential required.
        data = await self.get_klines([s], "1m", 4)
        candles = data.get(s) or []
        if not candles:
            raise RuntimeError(f"Mudrex returned no recent candle for {s}")
        candle = candles[-1]
        return {
            "symbol": s,
            "price": float(candle[4]),
            "mark_price": None,
            "source": "Mudrex public REST 1m kline",
            "timestamp": int(candle[0]),
        }

    async def health(self) -> bool:
        try:
            x = await self.get_klines(["BTCUSDT"], "1m", 2)
            return bool(x.get("BTCUSDT"))
        except Exception as exc:
            logger.warning("[MUDREX] health failed: %s", exc)
            return False

    @staticmethod
    def _extract_tickers(msg: dict):
        """Return zero or more (symbol, price, mark_price, timestamp) tuples."""
        if not isinstance(msg, dict):
            return []
        payload = msg.get("data")
        if payload is None:
            payload = msg

        rows = payload if isinstance(payload, list) else [payload]
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = row.get("s") or row.get("symbol") or row.get("asset")
            price = row.get("p")
            if price is None:
                price = row.get("price") or row.get("last_price") or row.get("lastPrice") or row.get("close") or row.get("c")
            mark_price = row.get("mp") or row.get("mark_price") or row.get("markPrice")
            if not sym or price is None:
                continue
            try:
                out.append(
                    (
                        str(sym).replace("/", "").upper(),
                        float(price),
                        float(mark_price) if mark_price is not None else None,
                        row.get("timestamp") or row.get("time") or int(time.time()),
                    )
                )
            except (TypeError, ValueError):
                continue
        return out

    async def websocket_loop(self):
        import websockets

        while True:
            try:
                async with websockets.connect(
                    settings.MUDREX_WS_URL,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    open_timeout=10,
                ) as ws:
                    self.ws_connected = True
                    self.last_error = None
                    assets = [s.lower().replace("/", "") for s in settings.symbols()]
                    sub = {"id": 1, "method": "SUBSCRIBE", "params": ["ticker@5s"], "assets": assets}
                    await ws.send(json.dumps(sub))
                    logger.info("[MUDREX_WS] connected; SUBSCRIBE ticker@5s assets=%s", ",".join(assets))

                    async for raw in ws:
                        self.ws_last_message_at = time.time()
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            logger.warning("[MUDREX_WS] non-JSON message: %s", str(raw)[:300])
                            continue

                        if isinstance(msg, dict) and msg.get("error"):
                            self.last_error = f"WS error: {msg.get('error')}"
                            logger.warning("[MUDREX_WS] subscription/server error: %s", msg.get("error"))
                            continue

                        if isinstance(msg, dict) and msg.get("result") == "success":
                            logger.info("[MUDREX_WS] subscription acknowledged id=%s", msg.get("id"))
                            continue

                        ticks = self._extract_tickers(msg)
                        for s, price, mark_price, ts in ticks:
                            self.live[s] = {
                                "price": price,
                                "mark_price": mark_price,
                                "timestamp": ts,
                                "received_at": time.time(),
                            }
                        if ticks:
                            logger.debug("[MUDREX_WS] ticker update symbols=%s", [x[0] for x in ticks])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.ws_connected = False
                self.last_error = f"WS: {type(exc).__name__}: {exc}"
                logger.warning("[MUDREX_WS] disconnected: %s; retrying in 5s", exc)
                await asyncio.sleep(5)
            finally:
                self.ws_connected = False


mudrex_service = MudrexService()
