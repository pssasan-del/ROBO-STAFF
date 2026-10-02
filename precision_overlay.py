"""ROBO STAFF V7.1 liquid option overlay.

Selects one near-ATM OPTION BUY contract after the underlying setup passes.
V7.1 widens delta/rank slightly and treats weak premium momentum as a rank
penalty instead of a universal veto, preventing clean scalps from being lost.
Signal-only.
"""
from __future__ import annotations
import asyncio
from types import MethodType

from config import logger
from delta_options_service import delta_options_service
from option_premium_history_service import option_premium_history_service
from polish_policy import SPREAD_CAP_PCT


def _f(v, default=0.0):
    try:return float(v)
    except (TypeError,ValueError):return default


def install_precision_overlay(engine):
    original_analyze_symbol=engine.analyze_symbol
    engine._v6_option_context={}

    async def _v6_option_candidates(self,symbol,direction,snap):
        und=self._underlying(symbol)
        if und not in {"BTC","ETH"}:return []
        rows=await delta_options_service.get_chain(und)
        parsed=[delta_options_service._snapshot(r) for r in rows]
        parsed=[x for x in parsed if x.get("strike") and x.get("expiry")]
        if not parsed:return []
        expiries=sorted({x["expiry"] for x in parsed if x.get("expiry")})
        expiry=next((e for e in expiries if (self._minutes_to_expiry(e,und) or -1)>=60),None)
        if not expiry:return []
        pool=[x for x in parsed if x.get("expiry")==expiry]
        spot=next((_f(x.get("spot_price")) for x in pool if _f(x.get("spot_price"))>0),0.0)
        if spot<=0:return []
        side="CE" if direction=="BULLISH" else ("PE" if direction=="BEARISH" else None)
        if not side:return []
        side_pool=[x for x in pool if str(x.get("side") or "").upper()==side]
        strikes=sorted({_f(x.get("strike")) for x in side_pool if _f(x.get("strike"))>0})
        if not strikes:return []
        atm=min(range(len(strikes)),key=lambda i:abs(strikes[i]-spot))
        idxs=[atm]
        if atm-1>=0:idxs.append(atm-1)
        if atm+1<len(strikes):idxs.append(atm+1)
        if atm-2>=0:idxs.append(atm-2)
        if atm+2<len(strikes):idxs.append(atm+2)
        wanted={strikes[i]:abs(i-atm) for i in idxs}
        candidates=[x for x in side_pool if _f(x.get("strike")) in wanted]
        if not candidates:return []

        cap=SPREAD_CAP_PCT.get(und,4.0)
        max_vol=max([max(0.0,_f(x.get("volume"))) for x in candidates] or [1.0])
        max_oi=max([max(0.0,_f(x.get("oi"))) for x in candidates] or [1.0])
        ranked=[]
        for x in candidates:
            bid,ask=_f(x.get("best_bid")),_f(x.get("best_ask"))
            if bid<=0 or ask<=bid:continue
            mid=(bid+ask)/2.0;spread_pct=(ask-bid)/mid*100.0 if mid>0 else 999.0
            if spread_pct>cap:continue
            d=x.get("delta");ad=abs(_f(d,-1)) if d is not None else None
            if ad is not None and ad>=0 and not (0.30<=ad<=0.65):continue
            vol=max(0.0,_f(x.get("volume")));oi=max(0.0,_f(x.get("oi")))
            spread_score=max(0.0,100.0*(1.0-spread_pct/max(cap,1e-9)))
            vol_score=min(100.0,100.0*vol/max(max_vol,1e-9));oi_score=min(100.0,100.0*oi/max(max_oi,1e-9))
            delta_score=62.0 if ad is None else max(0.0,100.0-abs(ad-0.47)*210.0)
            distance=wanted[_f(x.get("strike"))];distance_score=100.0 if distance==0 else (84.0 if distance==1 else 68.0)
            rank=0.38*spread_score+0.20*vol_score+0.20*oi_score+0.17*delta_score+0.05*distance_score
            if rank<42:continue
            y=dict(x);y.update({"spread_pct":spread_pct,"static_contract_rank_score":rank,"contract_rank_score":rank,"atm_distance":distance});ranked.append(y)
        if not ranked:return []

        ranked.sort(key=lambda z:(-_f(z.get("contract_rank_score")),_f(z.get("spread_pct"),99)))
        shortlist=ranked[:4]
        analyses=await asyncio.gather(*(option_premium_history_service.analyze(x.get("symbol")) for x in shortlist),return_exceptions=True)
        usable=[]
        for x,hist in zip(shortlist,analyses):
            y=dict(x)
            if isinstance(hist,Exception):
                y["premium_history_available"]=False;usable.append(y);continue
            premium=hist.get("premium") or {};oi_flow=hist.get("oi_flow") or {}
            if not premium.get("sufficient"):
                y["premium_history_available"]=False;usable.append(y);continue
            momentum=_f(premium.get("momentum_score"),0)
            gate=bool(premium.get("gate_pass"))
            # Premium momentum is evidence, not a hard veto. Weak history gets a penalty.
            momentum_component=momentum if gate else min(momentum,35.0)
            full_rank=0.76*_f(x.get("static_contract_rank_score"))+0.18*momentum_component+0.06*_f(oi_flow.get("score"),50)
            if full_rank<42:continue
            y["contract_rank_score"]=full_rank;y["premium_history_available"]=True;y["premium_analysis"]=premium;y["oi_flow"]=oi_flow;y["premium_gate_pass"]=gate
            usable.append(y)
        if not usable:return []
        usable.sort(key=lambda z:(-_f(z.get("contract_rank_score")),_f(z.get("spread_pct"),99)))
        best=usable[0]
        if len(self._v6_option_context)>=200:
            try:self._v6_option_context.pop(next(iter(self._v6_option_context)))
            except Exception:self._v6_option_context.clear()
        self._v6_option_context[str(best.get("symbol"))]={
            "premium_history_available":best.get("premium_history_available",False),
            "premium_analysis":best.get("premium_analysis") or {},"oi_flow":best.get("oi_flow") or {},
            "static_contract_rank_score":best.get("static_contract_rank_score"),"final_contract_rank_score":best.get("contract_rank_score"),
            "atm_distance":best.get("atm_distance"),"premium_gate_pass":best.get("premium_gate_pass"),
        }
        logger.info("[V7.1_OPTION] %s %s selected %s rank=%.1f spread=%.2f%% delta=%s history=%s",und,direction,best.get("symbol"),_f(best.get("contract_rank_score")),_f(best.get("spread_pct")),best.get("delta"),bool(best.get("premium_history_available")))
        return [("OPTION BUY",side,best)]

    def _v6_targets(self,action,entry,spread_abs,tick_size,strong_extension):
        risk_pct=max(0.18,2.0*spread_abs/max(entry,1e-9),5.0*tick_size/max(entry,1e-9));risk_pct=min(0.26,risk_pct);risk=entry*risk_pct
        rr1,rr2,rr3=(1.85,2.60,3.30) if strong_extension else (1.85,2.35,3.00)
        if action=="OPTION BUY":sl,t1,t2,t3=entry-risk,entry+risk*rr1,entry+risk*rr2,entry+risk*rr3
        else:sl,t1,t2,t3=entry+risk,entry-risk*rr1,entry-risk*rr2,entry-risk*rr3
        return sl,t1,t2,t3,rr1,risk_pct,risk

    async def _analyze_v6(self,symbol):
        candidates=await original_analyze_symbol(symbol)
        for c in candidates:
            ctx=self._v6_option_context.get(str(c.option_symbol)) or {};p=ctx.get("premium_analysis") or {};flow=ctx.get("oi_flow") or {}
            c.market.update({
                "v7_1_option_overlay":True,"premium_history_available":bool(ctx.get("premium_history_available")),
                "premium_close":p.get("close"),"premium_ema5":p.get("ema5"),"premium_ema9":p.get("ema9"),"premium_rsi":p.get("rsi"),
                "premium_williams_r":p.get("williams_r"),"premium_structure":p.get("structure"),"premium_momentum_score":p.get("momentum_score"),
                "premium_gate_pass":ctx.get("premium_gate_pass"),"oi_flow_label":flow.get("label"),"oi_flow_score":flow.get("score"),
                "static_contract_rank_score":ctx.get("static_contract_rank_score"),"atm_distance":ctx.get("atm_distance"),
            })
            if ctx.get("premium_history_available"):
                c.reason=(c.reason+" + PREMIUM HISTORY SCORED").strip()
            else:c.reason=(c.reason+" + PREMIUM HISTORY UNAVAILABLE").strip()
        return candidates

    engine._option_candidates=MethodType(_v6_option_candidates,engine);engine._dynamic_targets=MethodType(_v6_targets,engine);engine.analyze_symbol=MethodType(_analyze_v6,engine)
    engine.precision_overlay_installed=True;engine.premium_oi_overlay_installed=True;engine.v7_1_option_overlay_installed=True;engine.active_flow_target_rr=1.85
    logger.info("[V7.1_OPTION] near-ATM ±2, delta 0.30-0.65, rank>=42, premium momentum soft-scored; T1 1.85R")
    return engine
