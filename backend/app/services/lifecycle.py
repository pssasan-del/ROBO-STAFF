from __future__ import annotations
from dataclasses import dataclass, asdict
from enum import Enum
from time import time
from typing import Any
import uuid

class SignalState(str, Enum):
    WATCHING="WATCHING"
    ACTIVE="ACTIVE"
    ENTRY="ENTRY"
    T1="T1"
    T2="T2"
    T3="T3"
    SL="SL"
    EXPIRED="EXPIRED"
    CANCELLED="CANCELLED"

@dataclass(slots=True)
class TrackedSignal:
    id: str
    symbol_key: str
    side: str
    entry: float
    entry_low: float
    entry_high: float
    stop: float
    target1: float
    target2: float
    created_at: float
    expires_at: float
    state: SignalState=SignalState.ACTIVE
    target3: float | None=None
    score: int | None=None
    rr: float | None=None
    reason: str | None=None
    timeframe_sec: int=300
    rsi14: float | None=None
    williams_r14: float | None=None
    last_price: float | None=None
    updated_at: float | None=None

    def to_dict(self)->dict[str,Any]:
        d=asdict(self); d["state"]=self.state.value; return d

class SignalLifecycle:
    def __init__(self)->None:
        self.items:dict[str,TrackedSignal]={}

    def create(self, *, symbol_key:str, side:str, entry:float, stop:float, target1:float,
               target2:float, entry_tolerance_pct:float=0.25, ttl_sec:int=1800,
               target3:float|None=None, score:int|None=None, rr:float|None=None,
               reason:str|None=None, timeframe_sec:int=300, rsi14:float|None=None,
               williams_r14:float|None=None)->dict[str,Any]:
        tol=abs(entry)*entry_tolerance_pct/100
        now=time()
        s=TrackedSignal(
            uuid.uuid4().hex[:12], symbol_key, side.upper(), entry, entry-tol, entry+tol,
            stop, target1, target2, now, now+ttl_sec, SignalState.ACTIVE,
            target3, score, rr, reason, timeframe_sec, rsi14, williams_r14,
        )
        self.items[s.id]=s
        # Keep memory bounded while preserving recent history for the app.
        if len(self.items) > 250:
            oldest=sorted(self.items.values(), key=lambda x:x.created_at)[:50]
            for item in oldest:
                self.items.pop(item.id, None)
        return s.to_dict()

    def has_recent(self, symbol_key:str, side:str, window_sec:int=900)->bool:
        cutoff=time()-window_sec
        side=side.upper()
        for s in self.items.values():
            if s.symbol_key==symbol_key and s.side==side and s.created_at>=cutoff and s.state not in {SignalState.CANCELLED, SignalState.EXPIRED}:
                return True
        return False

    def update_price(self, signal_id:str, price:float, now:float|None=None)->dict[str,Any]:
        s=self.items[signal_id]; now=now or time(); s.last_price=price; s.updated_at=now
        if s.state in {SignalState.SL,SignalState.T3,SignalState.EXPIRED,SignalState.CANCELLED}: return s.to_dict()
        if s.state==SignalState.T2 and s.target3 is None: return s.to_dict()
        if now >= s.expires_at and s.state in {SignalState.ACTIVE,SignalState.WATCHING}:
            s.state=SignalState.EXPIRED; return s.to_dict()
        if s.side=="BUY":
            if price <= s.stop: s.state=SignalState.SL
            elif s.target3 is not None and price >= s.target3: s.state=SignalState.T3
            elif price >= s.target2: s.state=SignalState.T2
            elif price >= s.target1: s.state=SignalState.T1
            elif s.entry_low <= price <= s.entry_high and s.state==SignalState.ACTIVE: s.state=SignalState.ENTRY
        else:
            if price >= s.stop: s.state=SignalState.SL
            elif s.target3 is not None and price <= s.target3: s.state=SignalState.T3
            elif price <= s.target2: s.state=SignalState.T2
            elif price <= s.target1: s.state=SignalState.T1
            elif s.entry_low <= price <= s.entry_high and s.state==SignalState.ACTIVE: s.state=SignalState.ENTRY
        return s.to_dict()

    def list(self)->list[dict[str,Any]]:
        return [x.to_dict() for x in sorted(self.items.values(), key=lambda s:s.created_at, reverse=True)]

    def stats(self)->dict[str,Any]:
        rows=list(self.items.values())
        counts={state.value:0 for state in SignalState}
        for item in rows:
            counts[item.state.value]=counts.get(item.state.value,0)+1
        terminal={SignalState.T2,SignalState.T3,SignalState.SL,SignalState.EXPIRED,SignalState.CANCELLED}
        live=sum(1 for item in rows if item.state not in terminal)
        wins=sum(1 for item in rows if item.state in {SignalState.T1,SignalState.T2,SignalState.T3})
        losses=sum(1 for item in rows if item.state==SignalState.SL)
        scored=[item.score for item in rows if item.score is not None]
        return {
            "total":len(rows),
            "live":live,
            "wins":wins,
            "losses":losses,
            "avg_score":round(sum(scored)/len(scored),1) if scored else None,
            "counts":counts,
        }

signal_lifecycle=SignalLifecycle()
