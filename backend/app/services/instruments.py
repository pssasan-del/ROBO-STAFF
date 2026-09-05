from __future__ import annotations
import asyncio, time
from typing import Any
from app.services.broker import broker
from app.services.recovery import recovery_store


class InstrumentResolver:
    def __init__(self, ttl_sec: int = 900) -> None:
        self.ttl_sec = ttl_sec
        self.cache: dict[str, tuple[float, Any]] = {}
        self.core_indices: list[dict[str, Any]] = recovery_store.snapshot().get("core_indices", [])

    async def search(self, exchange_segment: str, symbol: str, expiry: str | None = None,
                     option_type: str | None = None, strike_price: str | None = None,
                     ignore_50multiple: bool = False) -> Any:
        key = "|".join(str(x or "") for x in (exchange_segment, symbol.upper(), expiry, option_type, strike_price, ignore_50multiple))
        item = self.cache.get(key)
        if item and time.time() - item[0] < self.ttl_sec:
            data = item[1]
        else:
            data = None
        if data is None:
            client = broker._ensure_client()
            data = await asyncio.to_thread(client.search_scrip, exchange_segment, symbol, expiry, option_type, strike_price, ignore_50multiple)
            self.cache[key] = (time.time(), data)
        normalized = []
        try:
            from app.services.options import flatten_records
            for row in flatten_records(data):
                if not isinstance(row, dict):
                    continue
                token = row.get("instrument_token") or row.get("instrumentToken") or row.get("token") or row.get("pSymbol") or row.get("p_symbol")
                trading_symbol = row.get("trading_symbol") or row.get("tradingSymbol") or row.get("pTrdSymbol") or row.get("p_trd_symbol") or row.get("symbol") or row.get("name")
                segment = row.get("exchange_segment") or row.get("exchangeSegment") or row.get("segment") or exchange_segment
                if token:
                    recovery_store.remember_instrument(f"{segment}|{token}", row)
                    normalized.append({
                        **row,
                        "instrument_token": str(token),
                        "exchange_segment": str(segment),
                        "trading_symbol": str(trading_symbol or symbol).strip(),
                    })
        except Exception:
            normalized = []
        return {"cached": item is not None and time.time() - item[0] < self.ttl_sec, "data": data, "normalized": normalized}

    async def resolve_option(self, underlying: str, expiry: str, option_type: str, strike_price: float,
                             exchange_segment: str = "NSEFO") -> Any:
        return await self.search(exchange_segment, underlying, expiry, option_type.upper(), str(strike_price), False)

    async def scan_option_candidates(self, *, underlying: str, expiry: str, option_type: str,
                                     underlying_ltp: float, strike_step: float,
                                     strikes_each_side: int = 2, exchange_segment: str = "NSEFO") -> dict[str, Any]:
        """Search strikes around ATM, enrich with broker quotes, then rank quality."""
        from app.services.options import flatten_records, option_selector
        if underlying_ltp <= 0 or strike_step <= 0:
            return {"status": "REJECTED", "reason": "INVALID_PRICE_OR_STRIKE_STEP"}
        atm = round(underlying_ltp / strike_step) * strike_step
        strikes = [atm + i * strike_step for i in range(-max(0, strikes_each_side), max(0, strikes_each_side) + 1)]
        enriched: list[dict[str, Any]] = []
        for strike in strikes:
            sr = await self.resolve_option(underlying, expiry, option_type, strike, exchange_segment)
            records = flatten_records(sr.get("data", sr))
            for rec in records:
                token = rec.get("instrument_token") or rec.get("instrumentToken") or rec.get("token") or rec.get("pSymbol") or rec.get("p_symbol")
                if not token:
                    continue
                try:
                    quote = await broker.quote(exchange_segment, str(token), "all")
                    quote_records = flatten_records(quote)
                    qmatch = next((q for q in quote_records if str(q.get("instrument_token") or q.get("instrumentToken") or q.get("token") or q.get("pSymbol") or q.get("p_symbol") or "") == str(token)), None)
                    merged = dict(rec)
                    if qmatch:
                        merged.update(qmatch)
                    enriched.append(merged)
                except Exception:
                    enriched.append(dict(rec))
        ranked = option_selector.rank(enriched, underlying_ltp=underlying_ltp, option_type=option_type, fallback_segment=exchange_segment)
        accepted = [x for x in ranked if x["accepted"]]
        return {"status": "READY" if accepted else "REJECTED", "atm": atm, "strikes_checked": strikes,
                "selected": accepted[0] if accepted else None, "candidates": ranked[:20],
                "reason": None if accepted else "NO_QUALITY_OPTION"}


    async def sync_core_indices(self) -> dict[str, Any]:
        """Discover core index contracts through the broker search API and subscribe to verified tokens."""
        wanted = [
            ("nse_cm", "NIFTY", "Nifty 50"),
            ("nse_cm", "BANKNIFTY", "Nifty Bank"),
            ("bse_cm", "SENSEX", "Sensex"),
        ]
        discovered=[]
        from app.services.options import flatten_records
        for segment, symbol, index_name in wanted:
            try:
                result = await self.search(segment, symbol)
                rows = flatten_records(result.get('data', result))
                row = rows[0] if rows else None
                if not row:
                    discovered.append({'label': symbol, 'ok': False, 'reason': 'NOT_FOUND'}); continue
                token = row.get('instrument_token') or row.get('instrumentToken') or row.get('token') or row.get('pSymbol') or row.get('p_symbol')
                actual_segment = row.get('exchange_segment') or row.get('exchangeSegment') or segment
                if not token:
                    discovered.append({'label': symbol, 'ok': False, 'reason': 'NO_TOKEN'}); continue
                await broker.subscribe(str(actual_segment), str(index_name), 'index')
                discovered.append({
                    'label': symbol,
                    'ok': True,
                    'exchange_segment': str(actual_segment),
                    'instrument_token': str(index_name),
                    'record': row
                })
            except Exception as exc:
                discovered.append({'label': symbol, 'ok': False, 'reason': str(exc)})
        self.core_indices = discovered
        recovery_store.set_core_indices(discovered)
        return {'ok': any(x.get('ok') for x in discovered), 'indices': discovered}

    def index_snapshot(self) -> list[dict[str, Any]]:
        out=[]
        for item in getattr(self, 'core_indices', []):
            row=dict(item)
            if item.get('ok'):
                key=f"{item['exchange_segment']}|{item['instrument_token']}"
                row['tick']=broker.latest_ticks.get(key)
            out.append(row)
        return out

    async def restore_core_subscriptions(self) -> dict[str, Any]:
        restored=[]
        if not broker.authenticated:
            return {"ok": False, "reason": "LOGIN_REQUIRED", "restored": restored}
        for item in self.core_indices:
            if not item.get("ok"):
                continue
            try:
                await broker.subscribe(str(item["exchange_segment"]), str(item["instrument_token"]), "index")
                restored.append({"label": item.get("label"), "ok": True})
            except Exception as exc:
                restored.append({"label": item.get("label"), "ok": False, "reason": str(exc)})
        return {"ok": all(x.get("ok") for x in restored) if restored else True, "restored": restored}

    def registry_snapshot(self) -> dict[str, Any]:
        snap = recovery_store.snapshot()
        return {"verified_count": len(snap.get("verified_instruments", {})), **snap}


instruments = InstrumentResolver()
