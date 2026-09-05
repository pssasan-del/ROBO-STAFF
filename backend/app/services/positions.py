from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, asdict
from typing import Any, Awaitable, Callable


@dataclass(slots=True)
class Position:
    key: str
    exchange_segment: str
    instrument_token: str
    trading_symbol: str
    product: str
    net_quantity: int
    total_buy_qty: int
    total_sell_qty: int
    total_buy_amount: float
    total_sell_amount: float
    average_price: float
    ltp: float | None = None
    pnl: float | None = None
    lot_size: int = 1
    multiplier: float = 1.0
    gen_num: float = 1.0
    gen_den: float = 1.0
    prc_num: float = 1.0
    prc_den: float = 1.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExitPlan:
    plan_id: str
    position_key: str
    stop_loss: float | None
    target1: float | None
    target2: float | None
    target1_fraction: float
    auto_exit: bool
    state: str = "ACTIVE"
    triggered_level: str | None = None
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PositionManager:
    """Normalises Kotak positions and maintains live mark-to-market.

    Raw Kotak quantities are retained for execution. PnL follows the formula in
    the official SDK positions documentation.
    """

    def __init__(self) -> None:
        self.items: dict[str, Position] = {}
        self.exit_plans: dict[str, ExitPlan] = {}
        self._exit_lock = asyncio.Lock()
        self._exit_inflight: set[str] = set()

    @staticmethod
    def _v(d: dict[str, Any], *keys: str, default=None):
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return d[k]
        return default

    @staticmethod
    def _i(v: Any) -> int:
        try: return int(float(v or 0))
        except (TypeError, ValueError): return 0

    @staticmethod
    def _f(v: Any, default: float = 0.0) -> float:
        try: return float(v)
        except (TypeError, ValueError): return default

    def _position_from_row(self, row: dict[str, Any], previous: Position | None = None) -> Position | None:
        seg = str(self._v(row, "exSeg", "exchange_segment", default=""))
        tok = str(self._v(row, "tok", "token", "instrument_token", default=""))
        sym = str(self._v(row, "trdSym", "trading_symbol", "sym", "symbol", default=""))
        product = str(self._v(row, "prod", "product", default=""))
        if not (seg and (tok or sym)):
            return None
        key = f"{seg}|{tok or sym}|{product}"

        cf_buy = self._i(self._v(row, "cfBuyQty", "carry_forward_buy_quantity"))
        cf_sell = self._i(self._v(row, "cfSellQty", "carry_forward_sell_quantity"))
        fl_buy = self._i(self._v(row, "flBuyQty", "filled_buy_quantity"))
        fl_sell = self._i(self._v(row, "flSellQty", "filled_sell_quantity"))
        total_buy_qty = cf_buy + fl_buy
        total_sell_qty = cf_sell + fl_sell
        net = total_buy_qty - total_sell_qty

        total_buy_amt = self._f(self._v(row, "cfBuyAmt", "carry_forward_buy_amount")) + self._f(self._v(row, "buyAmt", "buy_amount"))
        total_sell_amt = self._f(self._v(row, "cfSellAmt", "carry_forward_sell_amount")) + self._f(self._v(row, "sellAmt", "sell_amount"))
        multiplier = self._f(self._v(row, "multiplier"), 1.0) or 1.0
        gen_num = self._f(self._v(row, "genNum", "general_numerator"), 1.0) or 1.0
        gen_den = self._f(self._v(row, "genDen", "general_denominator"), 1.0) or 1.0
        prc_num = self._f(self._v(row, "prcNum", "price_numerator"), 1.0) or 1.0
        prc_den = self._f(self._v(row, "prcDen", "price_denominator"), 1.0) or 1.0
        factor = multiplier * (gen_num / gen_den) * (prc_num / prc_den)
        avg = 0.0
        if net > 0 and total_buy_qty:
            avg = total_buy_amt / (total_buy_qty * factor)
        elif net < 0 and total_sell_qty:
            avg = total_sell_amt / (total_sell_qty * factor)
        ltp = previous.ltp if previous else None
        p = Position(key, seg, tok, sym, product, net, total_buy_qty, total_sell_qty,
                     total_buy_amt, total_sell_amt, avg, ltp=ltp,
                     lot_size=max(1, self._i(self._v(row, "lotSz", "lot_size", default=1))),
                     multiplier=multiplier, gen_num=gen_num, gen_den=gen_den,
                     prc_num=prc_num, prc_den=prc_den, updated_at=time.time())
        self._mark(p)
        return p

    def _mark(self, p: Position) -> None:
        if p.ltp is None:
            p.pnl = None
            return
        factor = p.multiplier * (p.gen_num / p.gen_den) * (p.prc_num / p.prc_den)
        p.pnl = (p.total_sell_amount - p.total_buy_amount) + (p.net_quantity * p.ltp * factor)

    def sync_rest(self, payload: Any) -> list[dict[str, Any]]:
        rows = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return self.list()
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict): continue
            seg = str(self._v(row, "exSeg", "exchange_segment", default=""))
            tok = str(self._v(row, "tok", "token", "instrument_token", default=""))
            sym = str(self._v(row, "trdSym", "trading_symbol", "sym", "symbol", default=""))
            product = str(self._v(row, "prod", "product", default=""))
            key = f"{seg}|{tok or sym}|{product}"
            p = self._position_from_row(row, self.items.get(key))
            if p:
                self.items[p.key] = p; seen.add(p.key)
        # REST snapshot is authoritative; keep only current rows.
        for key in list(self.items):
            if key not in seen: self.items.pop(key, None)
        return self.list()

    def on_position_update(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict): return None
        # Position websocket may be partial; merge with prior normalised source where possible.
        seg = str(self._v(data, "exSeg", "exchange_segment", default=""))
        tok = str(self._v(data, "tok", "token", "instrument_token", default=""))
        sym = str(self._v(data, "trdSym", "trading_symbol", "sym", "symbol", default=""))
        product = str(self._v(data, "prod", "product", default=""))
        candidate_keys = [k for k,p in self.items.items() if (not seg or p.exchange_segment==seg) and (not product or p.product==product) and ((tok and p.instrument_token==tok) or (sym and (p.trading_symbol==sym or p.trading_symbol.startswith(sym))))]
        previous = self.items.get(candidate_keys[0]) if candidate_keys else None
        if previous:
            merged = previous.to_dict(); merged.update(data)
            # Translate canonical dataclass names back into parser-friendly names.
            merged.update({"exSeg": previous.exchange_segment, "tok": previous.instrument_token, "trdSym": previous.trading_symbol, "prod": previous.product})
            # Position feed carries day filled quantities/amounts; preserve carry forward if known.
            p = self._position_from_row(merged, previous)
        else:
            p = self._position_from_row(data, None)
        if p:
            self.items[p.key] = p
            return p.to_dict()
        return None

    def on_tick(self, exchange_segment: str, instrument_token: str, ltp: float) -> list[dict[str, Any]]:
        changed=[]
        for p in self.items.values():
            if p.exchange_segment == exchange_segment and p.instrument_token == instrument_token:
                p.ltp=float(ltp); p.updated_at=time.time(); self._mark(p); changed.append(p.to_dict())
        return changed

    def list(self, open_only: bool = False) -> list[dict[str, Any]]:
        vals=list(self.items.values())
        if open_only: vals=[p for p in vals if p.net_quantity != 0]
        return [p.to_dict() for p in sorted(vals, key=lambda x:x.key)]

    def summary(self) -> dict[str, Any]:
        open_items=[p for p in self.items.values() if p.net_quantity != 0]
        pnls=[p.pnl for p in self.items.values() if p.pnl is not None]
        return {"open_positions":len(open_items), "day_mtm":sum(pnls) if pnls else 0.0,
                "marked_positions":len(pnls), "tracked_positions":len(self.items)}

    def get(self, key: str) -> Position | None: return self.items.get(key)

    def build_exit_order(self, key: str, quantity: int | None = None) -> dict[str, Any]:
        p=self.items.get(key)
        if not p or p.net_quantity == 0: raise ValueError("POSITION_NOT_OPEN")
        qty=abs(p.net_quantity) if quantity is None else int(quantity)
        if qty <= 0 or qty > abs(p.net_quantity): raise ValueError("INVALID_EXIT_QUANTITY")
        return {"exchange_segment":p.exchange_segment, "product":p.product, "price":"0", "order_type":"MARKET",
                "quantity":str(qty), "validity":"DAY", "trading_symbol":p.trading_symbol,
                "transaction_type":"S" if p.net_quantity > 0 else "B", "trigger_price":"0", "amo":"NO",
                "tag":f"NST-EXIT-{int(time.time())}"}

    def create_exit_plan(self, key: str, *, stop_loss: float | None, target1: float | None,
                         target2: float | None = None, target1_fraction: float = 0.5,
                         auto_exit: bool = False) -> dict[str, Any]:
        if key not in self.items or self.items[key].net_quantity == 0: raise ValueError("POSITION_NOT_OPEN")
        if not (0 < target1_fraction <= 1): raise ValueError("INVALID_TARGET1_FRACTION")
        pid=f"XP-{abs(hash((key,time.time_ns()))) & 0xffffffff:x}"
        plan=ExitPlan(pid,key,stop_loss,target1,target2,target1_fraction,auto_exit,updated_at=time.time())
        self.exit_plans[pid]=plan
        return plan.to_dict()

    async def evaluate_exit_plans(self, key: str, ltp: float, submitter: Callable[..., Awaitable[dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
        events=[]
        for plan in list(self.exit_plans.values()):
            if plan.position_key != key or plan.state != "ACTIVE": continue
            p=self.items.get(key)
            if not p or p.net_quantity == 0:
                plan.state="CLOSED"; plan.updated_at=time.time(); events.append(plan.to_dict()); continue
            long=p.net_quantity > 0
            level=None
            if plan.stop_loss is not None and ((long and ltp <= plan.stop_loss) or ((not long) and ltp >= plan.stop_loss)): level="STOP_LOSS"
            elif plan.target2 is not None and ((long and ltp >= plan.target2) or ((not long) and ltp <= plan.target2)): level="TARGET2"
            elif plan.target1 is not None and ((long and ltp >= plan.target1) or ((not long) and ltp <= plan.target1)): level="TARGET1"
            if not level: continue
            plan.triggered_level=level; plan.updated_at=time.time()
            if not plan.auto_exit or submitter is None:
                plan.state="TRIGGERED_MANUAL"; events.append(plan.to_dict()); continue
            async with self._exit_lock:
                if plan.plan_id in self._exit_inflight: continue
                self._exit_inflight.add(plan.plan_id)
            try:
                qty=abs(p.net_quantity)
                if level=="TARGET1" and plan.target2 is not None:
                    qty=max(1, min(qty, int(round(qty*plan.target1_fraction))))
                order=self.build_exit_order(key,qty)
                response=await submitter(**order)
                plan.state="EXIT_SUBMITTED"
                events.append({**plan.to_dict(),"order":order,"broker_response":response})
            except Exception as exc:
                plan.state="EXIT_ERROR"; events.append({**plan.to_dict(),"error":str(exc)})
            finally:
                self._exit_inflight.discard(plan.plan_id); plan.updated_at=time.time()
        return events

position_manager=PositionManager()
