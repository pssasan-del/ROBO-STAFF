from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Iterable


def _num(v: Any) -> float | None:
    try:
        if v is None or v == "": return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _first(d: dict[str, Any], names: Iterable[str]) -> Any:
    for n in names:
        if n in d and d[n] not in (None, ""):
            return d[n]
    return None


def flatten_records(payload: Any) -> list[dict[str, Any]]:
    """Extract dict records from common broker response envelopes without assuming one SDK shape."""
    out: list[dict[str, Any]] = []
    def walk(x: Any) -> None:
        if isinstance(x, dict):
            # A leaf-ish instrument/quote record has at least one identifying/price field.
            keys = {str(k).lower() for k in x}
            markers = {"instrument_token", "instrumenttoken", "trading_symbol", "tradingsymbol", "p_symbol", "psymbol", "ptrdsymbol", "psymbolname", "pscriprefkey", "ltp", "last_traded_price", "strike_price", "strikeprice"}
            if keys & markers:
                out.append(x)
            for v in x.values():
                if isinstance(v, (dict, list, tuple)): walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x: walk(v)
    walk(payload)
    # stable de-duplication by repr of sorted scalar fields
    seen=set(); unique=[]
    for r in out:
        sig=tuple(sorted((str(k), str(v)) for k,v in r.items() if not isinstance(v,(dict,list,tuple))))
        if sig not in seen:
            seen.add(sig); unique.append(r)
    return unique


@dataclass(slots=True)
class OptionCandidate:
    trading_symbol: str
    instrument_token: str
    exchange_segment: str
    option_type: str
    strike: float
    expiry: str | None = None
    ltp: float | None = None
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    oi: float | None = None
    spread_pct: float | None = None
    distance_pct: float | None = None
    score: float = 0.0
    accepted: bool = False
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]: return asdict(self)


class OptionSelector:
    """Deterministic option contract quality filter and scorer.

    It never fabricates liquidity. Missing broker fields are reported as unavailable.
    """
    def __init__(self, *, max_spread_pct: float = 2.0, min_premium: float = 5.0,
                 max_premium: float = 1000.0, max_distance_pct: float = 5.0) -> None:
        self.max_spread_pct=max_spread_pct
        self.min_premium=min_premium
        self.max_premium=max_premium
        self.max_distance_pct=max_distance_pct

    def normalize(self, rec: dict[str, Any], *, fallback_segment: str="NSEFO", fallback_type: str="") -> OptionCandidate | None:
        token=str(_first(rec, ("instrument_token","instrumentToken","token","pSymbol","p_symbol")) or "")
        symbol=str(_first(rec, ("trading_symbol","tradingSymbol","symbol","pTrdSymbol","p_trd_symbol")) or "")
        strike=_num(_first(rec, ("strike_price","strikePrice","strike","stkprc")))
        if not token or strike is None: return None
        option_type=str(_first(rec,("option_type","optionType","optType","optt")) or fallback_type).upper()
        segment=str(_first(rec,("exchange_segment","exchangeSegment","segment","exchange_segment_name")) or fallback_segment)
        expiry=_first(rec,("expiry","expiry_date","expiryDate","expdt"))
        ltp=_num(_first(rec,("last_traded_price","ltp","lastPrice","last_price","lp")))
        bid=_num(_first(rec,("best_bid_price","bid","bidPrice","bp")))
        ask=_num(_first(rec,("best_ask_price","ask","askPrice","sp")))
        volume=_num(_first(rec,("volume_traded_today","volume","vol","v")))
        oi=_num(_first(rec,("open_interest","oi","openInterest")))
        return OptionCandidate(symbol,token,segment,option_type,strike,str(expiry) if expiry else None,ltp,bid,ask,volume,oi)

    def evaluate(self, c: OptionCandidate, underlying_ltp: float) -> OptionCandidate:
        reasons=[]
        if underlying_ltp <= 0: reasons.append("INVALID_UNDERLYING_PRICE")
        else:
            c.distance_pct=abs(c.strike-underlying_ltp)/underlying_ltp*100
            if c.distance_pct > self.max_distance_pct: reasons.append("STRIKE_TOO_FAR")
        if c.ltp is None: reasons.append("MISSING_LTP")
        elif not (self.min_premium <= c.ltp <= self.max_premium): reasons.append("PREMIUM_OUT_OF_RANGE")
        if c.bid is not None and c.ask is not None and c.bid > 0 and c.ask >= c.bid:
            mid=(c.ask+c.bid)/2
            c.spread_pct=(c.ask-c.bid)/mid*100 if mid else None
            if c.spread_pct is not None and c.spread_pct > self.max_spread_pct: reasons.append("SPREAD_TOO_WIDE")
        else:
            reasons.append("SPREAD_UNAVAILABLE")
        # Volume/OI are useful scoring inputs but not hard requirements because feeds/segments vary.
        score=100.0
        if c.distance_pct is not None: score -= min(30.0, c.distance_pct*6)
        if c.spread_pct is not None: score -= min(35.0, c.spread_pct*10)
        else: score -= 15.0
        if c.volume is None: score -= 5.0
        elif c.volume <= 0: score -= 15.0
        if c.oi is None: score -= 3.0
        elif c.oi <= 0: score -= 7.0
        hard={"INVALID_UNDERLYING_PRICE","STRIKE_TOO_FAR","MISSING_LTP","PREMIUM_OUT_OF_RANGE","SPREAD_TOO_WIDE"}
        c.accepted=not any(r in hard for r in reasons)
        c.reasons=tuple(reasons)
        c.score=round(max(0.0,score),2)
        return c

    def rank(self, records: list[dict[str,Any]], *, underlying_ltp: float,
             option_type: str, fallback_segment: str="NSEFO") -> list[dict[str,Any]]:
        ranked=[]
        for rec in records:
            c=self.normalize(rec,fallback_segment=fallback_segment,fallback_type=option_type)
            if c and (not option_type or c.option_type in ("",option_type.upper())):
                ranked.append(self.evaluate(c,underlying_ltp))
        ranked.sort(key=lambda x:(not x.accepted,-x.score,x.distance_pct if x.distance_pct is not None else 999))
        return [x.to_dict() for x in ranked]


option_selector=OptionSelector()
