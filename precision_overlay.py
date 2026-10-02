"""ROBO STAFF V5 CLEAN CONFLUENCE option overlay.

Selects one near-ATM OPTION BUY contract with usable spread/liquidity/delta and
uses premium-history momentum when available. History failure does not kill the
underlying signal; bad available premium momentum does. Signal-only.
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


def install_precision_overlay(engine):
    original_analyze_symbol = engine.analyze_symbol
    engine._v5_option_context = {}

    async def _v5_option_candidates(self, symbol, direction, snap):
        und = self._underlying(symbol)
        rows = await (delta_options_service.get_chain('XAUT') if und == 'GOLD' else delta_options_service.get_chain(und))
        parsed = [delta_options_service._snapshot(r) for r in rows]
        parsed = [x for x in parsed if x.get('strike') and x.get('expiry')]
        if not parsed and und == 'GOLD':
            rows = await delta_options_service.get_chain('PAXG')
            parsed = [delta_options_service._snapshot(r) for r in rows]
            parsed = [x for x in parsed if x.get('strike') and x.get('expiry')]
        if not parsed:
            return []

        expiries = sorted({x['expiry'] for x in parsed if x.get('expiry')})
        expiry = next((e for e in expiries if (self._minutes_to_expiry(e, und) or -1) >= 60), None)
        if not expiry:
            return []

        pool = [x for x in parsed if x.get('expiry') == expiry]
        spot = next((_f(x.get('spot_price')) for x in pool if _f(x.get('spot_price')) > 0), 0.0)
        if spot <= 0:
            return []

        side = 'CE' if direction == 'BULLISH' else ('PE' if direction == 'BEARISH' else None)
        if not side:
            return []
        side_pool = [x for x in pool if str(x.get('side') or '').upper() == side]
        strikes = sorted({_f(x.get('strike')) for x in side_pool if _f(x.get('strike')) > 0})
        if not strikes:
            return []
        atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))

        # ATM + one strike either side only: avoid far OTM lottery-style entries.
        idxs = [atm]
        if atm - 1 >= 0: idxs.append(atm - 1)
        if atm + 1 < len(strikes): idxs.append(atm + 1)
        wanted = {strikes[i]: abs(i - atm) for i in idxs}
        candidates = [x for x in side_pool if _f(x.get('strike')) in wanted]
        if not candidates:
            return []

        cap = SPREAD_CAP_PCT.get(und, 5.0)
        max_vol = max([max(0.0, _f(x.get('volume'))) for x in candidates] or [1.0])
        max_oi = max([max(0.0, _f(x.get('oi'))) for x in candidates] or [1.0])
        ranked = []
        for x in candidates:
            bid, ask = _f(x.get('best_bid')), _f(x.get('best_ask'))
            if bid <= 0 or ask <= bid:
                continue
            mid = (bid + ask) / 2.0
            spread_pct = (ask - bid) / mid * 100.0 if mid > 0 else 999.0
            if spread_pct > cap:
                continue
            d = x.get('delta')
            ad = abs(_f(d, -1)) if d is not None else None
            if ad is not None and ad >= 0 and not (0.20 <= ad <= 0.70):
                continue

            vol = max(0.0, _f(x.get('volume')))
            oi = max(0.0, _f(x.get('oi')))
            spread_score = max(0.0, 100.0 * (1.0 - spread_pct / max(cap, 1e-9)))
            vol_score = min(100.0, 100.0 * vol / max(max_vol, 1e-9))
            oi_score = min(100.0, 100.0 * oi / max(max_oi, 1e-9))
            delta_score = 65.0 if ad is None else max(0.0, 100.0 - abs(ad - 0.45) * 190.0)
            distance_score = 100.0 if wanted[_f(x.get('strike'))] == 0 else 82.0
            rank = 0.35 * spread_score + 0.20 * vol_score + 0.20 * oi_score + 0.20 * delta_score + 0.05 * distance_score
            if rank < 42:
                continue
            y = dict(x)
            y.update({'spread_pct': spread_pct, 'static_contract_rank_score': rank, 'contract_rank_score': rank})
            ranked.append(y)

        if not ranked:
            return []
        ranked.sort(key=lambda z: (-_f(z.get('contract_rank_score')), _f(z.get('spread_pct'), 99)))
        shortlist = ranked[:3]

        analyses = await asyncio.gather(
            *(option_premium_history_service.analyze(x.get('symbol')) for x in shortlist),
            return_exceptions=True,
        )

        accepted = []
        fallback = []
        for x, hist in zip(shortlist, analyses):
            if isinstance(hist, Exception):
                y = dict(x)
                y['premium_history_available'] = False
                fallback.append(y)
                continue

            premium = hist.get('premium') or {}
            oi_flow = hist.get('oi_flow') or {}
            if not premium.get('sufficient'):
                y = dict(x)
                y['premium_history_available'] = False
                fallback.append(y)
                continue

            # If we have enough premium history, insist that premium itself is not weak.
            momentum = _f(premium.get('momentum_score'), 0)
            if not premium.get('gate_pass') or momentum < 42:
                logger.info('[V5_OPTION] %s rejected by premium momentum score=%.1f', x.get('symbol'), momentum)
                continue

            full_rank = 0.68 * _f(x.get('static_contract_rank_score')) + 0.24 * momentum + 0.08 * _f(oi_flow.get('score'), 50)
            if full_rank < 50:
                continue
            y = dict(x)
            y['contract_rank_score'] = full_rank
            y['premium_history_available'] = True
            y['premium_analysis'] = premium
            y['oi_flow'] = oi_flow
            accepted.append(y)

        use = accepted if accepted else fallback
        if not use:
            return []
        use.sort(key=lambda z: (-_f(z.get('contract_rank_score')), _f(z.get('spread_pct'), 99)))
        best = use[0]

        if len(self._v5_option_context) >= 200:
            try: self._v5_option_context.pop(next(iter(self._v5_option_context)))
            except Exception: self._v5_option_context.clear()
        self._v5_option_context[str(best.get('symbol'))] = {
            'premium_history_available': best.get('premium_history_available', False),
            'premium_analysis': best.get('premium_analysis') or {},
            'oi_flow': best.get('oi_flow') or {},
            'static_contract_rank_score': best.get('static_contract_rank_score'),
            'final_contract_rank_score': best.get('contract_rank_score'),
        }

        logger.info('[V5_OPTION] %s %s selected %s rank=%.1f spread=%.2f%% history=%s',
                    und, direction, best.get('symbol'), _f(best.get('contract_rank_score')),
                    _f(best.get('spread_pct')), bool(best.get('premium_history_available')))
        return [('OPTION BUY', side, best)]

    def _v5_targets(self, action, entry, spread_abs, tick_size, strong_extension):
        # Preserve the user's 1.85R minimum target model while reducing oversized option stops.
        risk_pct = max(0.12, 1.8 * spread_abs / max(entry, 1e-9), 4.0 * tick_size / max(entry, 1e-9))
        risk_pct = min(0.20, risk_pct)
        risk = entry * risk_pct
        rr1, rr2, rr3 = (1.85, 2.50, 3.20) if strong_extension else (1.85, 2.25, 2.80)
        if action == 'OPTION BUY':
            sl, t1, t2, t3 = entry-risk, entry+risk*rr1, entry+risk*rr2, entry+risk*rr3
        else:
            sl, t1, t2, t3 = entry+risk, entry-risk*rr1, entry-risk*rr2, entry-risk*rr3
        return sl, t1, t2, t3, rr1, risk_pct, risk

    async def _analyze_v5(self, symbol):
        candidates = await original_analyze_symbol(symbol)
        for c in candidates:
            ctx = self._v5_option_context.get(str(c.option_symbol)) or {}
            p = ctx.get('premium_analysis') or {}
            flow = ctx.get('oi_flow') or {}
            c.market.update({
                'v5_clean_confluence': True,
                'premium_history_available': bool(ctx.get('premium_history_available')),
                'premium_close': p.get('close'),
                'premium_ema5': p.get('ema5'),
                'premium_ema9': p.get('ema9'),
                'premium_rsi': p.get('rsi'),
                'premium_williams_r': p.get('williams_r'),
                'premium_structure': p.get('structure'),
                'premium_momentum_score': p.get('momentum_score'),
                'oi_flow_label': flow.get('label'),
                'oi_flow_score': flow.get('score'),
                'static_contract_rank_score': ctx.get('static_contract_rank_score'),
            })
            if ctx.get('premium_history_available'):
                c.reason = (c.reason + ' + PREMIUM MOMENTUM CONFIRMED').strip()
            else:
                c.reason = (c.reason + ' + PREMIUM HISTORY UNAVAILABLE').strip()
        return candidates

    engine._option_candidates = MethodType(_v5_option_candidates, engine)
    engine._dynamic_targets = MethodType(_v5_targets, engine)
    engine.analyze_symbol = MethodType(_analyze_v5, engine)
    engine.precision_overlay_installed = True
    engine.active_flow_overlay_installed = False
    engine.premium_oi_overlay_installed = True
    engine.v5_clean_confluence_installed = True
    engine.active_flow_target_rr = 1.85
    logger.info('[V5_CLEAN] 1m/5m/15m confluence + near-ATM option quality + premium confirmation; T1 1.85R')
    return engine
