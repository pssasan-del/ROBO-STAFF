"""ROBO STAFF V4.2 ACTIVE FLOW premium/OI confirmation overlay.

Keeps the underlying V4.1 EMA/Fib entry logic and the 1.85R target model, then
confirms the selected OPTION BUY contract using its own 5-minute premium chart,
nearby strike OI/liquidity, and OI history. MASTER MIND is untouched.
SIGNAL ONLY — no private APIs and no order methods.
"""
from __future__ import annotations

import asyncio
from types import MethodType

from config import logger
from delta_options_service import delta_options_service
from option_premium_history_service import option_premium_history_service
from polish_policy import SPREAD_CAP_PCT


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _oi_cluster_metrics(selected, pool, near_strikes):
    side=str(selected.get('side') or '').upper()
    near=[x for x in pool if _f(x.get('strike')) in near_strikes]
    same=[x for x in near if str(x.get('side') or '').upper()==side]
    ce=[x for x in near if str(x.get('side') or '').upper()=='CE']
    pe=[x for x in near if str(x.get('side') or '').upper()=='PE']
    selected_oi=max(0.0,_f(selected.get('oi')))
    same_ois=[max(0.0,_f(x.get('oi'))) for x in same]
    same_total=sum(same_ois)
    max_same=max(same_ois or [0.0])
    ce_total=sum(max(0.0,_f(x.get('oi'))) for x in ce)
    pe_total=sum(max(0.0,_f(x.get('oi'))) for x in pe)
    share=(selected_oi/same_total*100.0) if same_total>0 else 0.0
    relative=(selected_oi/max_same*100.0) if max_same>0 else 0.0
    return {
        'selected_oi':selected_oi,'selected_side_total_oi':same_total,
        'selected_oi_share_pct':share,'selected_oi_relative_pct':relative,
        'nearby_ce_oi':ce_total,'nearby_pe_oi':pe_total,
        'nearby_pe_ce_oi_ratio':(pe_total/ce_total) if ce_total>0 else None,
        'nearby_strikes':len(near_strikes),
    }


def install_precision_overlay(engine):
    original_analyze_symbol=engine.analyze_symbol
    engine._premium_oi_context={}

    async def _active_option_candidates(self, symbol, direction, snap):
        und=self._underlying(symbol)
        rows=await (delta_options_service.get_chain('XAUT') if und=='GOLD' else delta_options_service.get_chain(und))
        parsed=[delta_options_service._snapshot(r) for r in rows]
        parsed=[x for x in parsed if x.get('strike') and x.get('expiry')]
        if not parsed and und=='GOLD':
            rows=await delta_options_service.get_chain('PAXG')
            parsed=[delta_options_service._snapshot(r) for r in rows]
            parsed=[x for x in parsed if x.get('strike') and x.get('expiry')]
        if not parsed:
            return []

        expiries=sorted({x['expiry'] for x in parsed if x.get('expiry')})
        expiry=next((e for e in expiries if (self._minutes_to_expiry(e,und) or -1)>=45),None)
        if not expiry:
            return []
        pool=[x for x in parsed if x.get('expiry')==expiry]
        spot=next((_f(x.get('spot_price')) for x in pool if _f(x.get('spot_price'))>0),0.0)
        if spot<=0:
            return []

        side='CE' if direction=='BULLISH' else ('PE' if direction=='BEARISH' else None)
        if not side:
            return []
        side_pool=[x for x in pool if str(x.get('side') or '').upper()==side]
        strikes=sorted({_f(x.get('strike')) for x in side_pool if _f(x.get('strike'))>0})
        if not strikes:
            return []
        atm=min(range(len(strikes)),key=lambda i:abs(strikes[i]-spot))

        # 1 ITM / ATM / 1 OTM / 2 OTM keeps quality choice flexible without
        # drifting far away from the underlying.
        offsets=(-1,0,1,2) if side=='CE' else (1,0,-1,-2)
        wanted=[]
        for off in offsets:
            idx=atm+off
            if 0<=idx<len(strikes):
                wanted.append((strikes[idx],off))
        wanted_map={s:off for s,off in wanted}
        candidates=[x for x in side_pool if _f(x.get('strike')) in wanted_map]
        if not candidates:
            return []

        near_strikes=set(strikes[max(0,atm-2):min(len(strikes),atm+3)])
        cap=SPREAD_CAP_PCT.get(und,6.0)
        max_volume=max([max(0.0,_f(x.get('volume'))) for x in candidates] or [1.0])
        max_oi=max([max(0.0,_f(x.get('oi'))) for x in candidates] or [1.0])
        ranked=[]
        for x in candidates:
            bid,ask=_f(x.get('best_bid')),_f(x.get('best_ask'))
            if bid<=0 or ask<=bid:
                continue
            mid=(bid+ask)/2.0
            spread_pct=(ask-bid)/mid*100.0 if mid>0 else 999.0
            if spread_pct>cap:
                continue
            d=x.get('delta');ad=abs(_f(d,-1)) if d is not None else None
            if ad is not None and ad>=0 and not (0.12<=ad<=0.80):
                continue

            volume=max(0.0,_f(x.get('volume')));oi=max(0.0,_f(x.get('oi')))
            spread_score=max(0.0,100.0*(1.0-spread_pct/max(cap,1e-9)))
            volume_score=min(100.0,100.0*volume/max(max_volume,1e-9))
            oi_score=min(100.0,100.0*oi/max(max_oi,1e-9))
            delta_score=65.0 if ad is None else max(0.0,100.0-abs(ad-0.45)*180.0)
            off=wanted_map[_f(x.get('strike'))]
            distance_score={0:100.0,1:88.0,-1:82.0,2:72.0,-2:68.0}.get(off,55.0)
            static_rank=(0.35*spread_score+0.18*volume_score+0.17*oi_score+0.20*delta_score+0.10*distance_score)
            if static_rank<35:
                continue
            y=dict(x)
            y.update({
                'spread_pct':spread_pct,'static_contract_rank_score':static_rank,
                'contract_rank_score':static_rank,'otm_distance':off,
                'volume_score':volume_score,'oi_level_score':oi_score,
                'oi_cluster':_oi_cluster_metrics(x,pool,near_strikes),
            })
            ranked.append(y)

        if not ranked:
            return []
        ranked.sort(key=lambda z:(-_f(z.get('static_contract_rank_score')),_f(z.get('spread_pct'),99)))

        # History calls are only made for the strongest three live contracts.
        # The history service caches results for 60s, so a 5m signal engine does
        # not hammer Delta REST on every scan.
        shortlist=ranked[:3]
        analyses=await asyncio.gather(
            *(option_premium_history_service.analyze(x.get('symbol')) for x in shortlist),
            return_exceptions=True,
        )
        confirmed=[]
        for x,h in zip(shortlist,analyses):
            if isinstance(h,Exception):
                logger.warning('[V42_PREMIUM] %s history failed: %s',x.get('symbol'),h)
                continue
            premium=h.get('premium') or {};oi_hist=h.get('oi') or {};oi_flow=h.get('oi_flow') or {}
            if not premium.get('sufficient'):
                logger.info('[V42_PREMIUM] %s rejected: insufficient premium history rows=%s',x.get('symbol'),premium.get('rows'))
                continue
            if not premium.get('gate_pass'):
                logger.info('[V42_PREMIUM] %s rejected: %s close=%s ema5=%s ext=%.2fATR',
                            x.get('symbol'),premium.get('reason'),premium.get('close'),premium.get('ema5'),
                            _f(premium.get('extension_atr')))
                continue

            premium_score=_f(premium.get('momentum_score'),50.0)
            oi_flow_score=_f(oi_flow.get('score'),50.0)
            full_rank=0.60*_f(x.get('static_contract_rank_score'))+0.28*premium_score+0.12*oi_flow_score
            if full_rank<45:
                continue
            x=dict(x)
            x['contract_rank_score']=full_rank
            x['premium_analysis']=premium
            x['premium_source']=h.get('source') or 'UNKNOWN'
            x['oi_history']=oi_hist
            x['oi_flow']=oi_flow
            x['premium_oi_confirmed']=True
            confirmed.append(x)

        if not confirmed:
            return []
        confirmed.sort(key=lambda z:(-_f(z.get('contract_rank_score')),_f(z.get('spread_pct'),99)))
        best=confirmed[0]

        ctx={
            'premium_analysis':best.get('premium_analysis') or {},
            'premium_source':best.get('premium_source'),
            'oi_history':best.get('oi_history') or {},
            'oi_flow':best.get('oi_flow') or {},
            'oi_cluster':best.get('oi_cluster') or {},
            'static_contract_rank_score':best.get('static_contract_rank_score'),
            'final_contract_rank_score':best.get('contract_rank_score'),
        }
        if len(self._premium_oi_context)>=200:
            try:self._premium_oi_context.pop(next(iter(self._premium_oi_context)))
            except Exception:self._premium_oi_context.clear()
        self._premium_oi_context[str(best.get('symbol'))]=ctx

        logger.info('[V42_CONTRACT] %s %s selected %s rank=%.1f premium=%.1f oi_flow=%s spread=%.2f%%',
                    und,direction,best.get('symbol'),_f(best.get('contract_rank_score')),
                    _f((best.get('premium_analysis') or {}).get('momentum_score')),
                    (best.get('oi_flow') or {}).get('label'),_f(best.get('spread_pct')))
        return [('OPTION BUY',side,best)]

    def _active_targets(self, action, entry, spread_abs, tick_size, strong_extension):
        # Keep the 1.85R experiment fixed while entry quality is being improved.
        risk_pct=max(0.14,2.0*spread_abs/max(entry,1e-9),5.0*tick_size/max(entry,1e-9))
        risk_pct=min(0.24,risk_pct)
        risk=entry*risk_pct
        rr1,rr2,rr3=(1.85,2.60,3.40) if strong_extension else (1.85,2.30,3.00)
        if action=='OPTION BUY':
            sl=entry-risk;t1=entry+risk*rr1;t2=entry+risk*rr2;t3=entry+risk*rr3
        else:
            sl=entry+risk;t1=entry-risk*rr1;t2=entry-risk*rr2;t3=entry-risk*rr3
        return sl,t1,t2,t3,rr1,risk_pct,risk

    async def _analyze_with_premium_oi(self, symbol):
        candidates=await original_analyze_symbol(symbol)
        for c in candidates:
            ctx=self._premium_oi_context.get(str(c.option_symbol)) or {}
            if not ctx:
                continue
            p=ctx.get('premium_analysis') or {};o=ctx.get('oi_history') or {};flow=ctx.get('oi_flow') or {};cl=ctx.get('oi_cluster') or {}
            c.market.update({
                'premium_source':ctx.get('premium_source'),'premium_close':p.get('close'),'premium_ema5':p.get('ema5'),
                'premium_ema9':p.get('ema9'),'premium_ema18':p.get('ema18'),'premium_rsi':p.get('rsi'),
                'premium_williams_r':p.get('williams_r'),'premium_structure':p.get('structure'),
                'premium_cross_side':p.get('cross_side'),'premium_cross_bars_ago':p.get('cross_bars_ago'),
                'premium_extension_atr':p.get('extension_atr'),'premium_relative_volume':p.get('relative_volume'),
                'premium_momentum_score':p.get('momentum_score'),'premium_change_3bar_pct':p.get('change_3bar_pct'),
                'oi_history_change_pct':o.get('change_pct'),'oi_history_trend':o.get('trend'),
                'oi_flow_label':flow.get('label'),'oi_flow_score':flow.get('score'),
                'oi_cluster_selected_share_pct':cl.get('selected_oi_share_pct'),
                'oi_cluster_selected_relative_pct':cl.get('selected_oi_relative_pct'),
                'oi_cluster_ce':cl.get('nearby_ce_oi'),'oi_cluster_pe':cl.get('nearby_pe_oi'),
                'oi_cluster_pe_ce_ratio':cl.get('nearby_pe_ce_oi_ratio'),
                'static_contract_rank_score':ctx.get('static_contract_rank_score'),
                'premium_oi_confirmed':True,
            })
            c.reason=(c.reason+' + OPTION PREMIUM/OI CONFIRMED').strip()
        return candidates

    engine._option_candidates=MethodType(_active_option_candidates,engine)
    engine._dynamic_targets=MethodType(_active_targets,engine)
    engine.analyze_symbol=MethodType(_analyze_with_premium_oi,engine)
    engine.precision_overlay_installed=True
    engine.active_flow_overlay_installed=True
    engine.premium_oi_overlay_installed=True
    engine.active_flow_target_rr=1.85
    logger.info('[V42_ACTIVE] option BUY + premium EMA5 gate + premium momentum/OI confirmation; T1 1.85R')
    return engine
