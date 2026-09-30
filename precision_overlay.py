"""ROBO STAFF V4.1 ACTIVE FLOW runtime overlay.

The first Delta engine remains OPTION BUY only for clean signal research, but this
overlay removes the V4.0 contract bottlenecks that could suppress otherwise valid
local-flow scalps. ATM/near-ATM contracts are preferred; quote quality remains
mandatory. MASTER MIND is separate and untouched. SIGNAL ONLY.
"""
from __future__ import annotations

from types import MethodType

from config import logger
from delta_options_service import delta_options_service
from polish_policy import SPREAD_CAP_PCT


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def install_precision_overlay(engine):
    async def _active_option_candidates(self, symbol, direction, snap):
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
        expiry = next((e for e in expiries if (self._minutes_to_expiry(e, und) or -1) >= 45), None)
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

        # Include 1 ITM, ATM, 1 OTM and 2 OTM so active scalps are not starved by
        # one bad quote at a single strike.
        offsets = (-1, 0, 1, 2) if side == 'CE' else (1, 0, -1, -2)
        wanted = []
        for off in offsets:
            idx = atm + off
            if 0 <= idx < len(strikes):
                wanted.append((strikes[idx], off))
        wanted_map = {s: off for s, off in wanted}
        candidates = [x for x in side_pool if _f(x.get('strike')) in wanted_map]
        if not candidates:
            return []

        liq_vals = [_f(x.get('volume')) + 0.05 * _f(x.get('oi')) for x in candidates]
        max_liq = max(liq_vals or [1.0])
        cap = SPREAD_CAP_PCT.get(und, 6.0)
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
            if ad is not None and ad >= 0 and not (0.12 <= ad <= 0.80):
                continue

            liquidity = _f(x.get('volume')) + 0.05 * _f(x.get('oi'))
            spread_score = max(0.0, 100.0 * (1.0 - spread_pct / max(cap, 1e-9)))
            liq_score = min(100.0, 100.0 * liquidity / max(max_liq, 1e-9))
            delta_score = 65.0 if ad is None else max(0.0, 100.0 - abs(ad - 0.45) * 180.0)
            off = wanted_map[_f(x.get('strike'))]
            distance_score = {0: 100.0, 1: 88.0, -1: 82.0, 2: 72.0, -2: 68.0}.get(off, 55.0)
            rank = 0.45 * spread_score + 0.25 * liq_score + 0.20 * delta_score + 0.10 * distance_score
            if rank < 35:
                continue
            y = dict(x)
            y['spread_pct'] = spread_pct
            y['contract_rank_score'] = rank
            y['otm_distance'] = off
            ranked.append(y)

        if not ranked:
            return []
        ranked.sort(key=lambda z: (-_f(z.get('contract_rank_score')), _f(z.get('spread_pct'), 99)))
        best = ranked[0]
        logger.info('[V41_CONTRACT] %s %s selected %s rank=%.1f spread=%.2f%% delta=%s',
                    und, direction, best.get('symbol'), _f(best.get('contract_rank_score')),
                    _f(best.get('spread_pct')), best.get('delta'))
        return [('OPTION BUY', side, best)]

    def _active_targets(self, action, entry, spread_abs, tick_size, strong_extension):
        # Give the option enough breathing room while keeping a scalp-size first target.
        risk_pct = max(0.14, 2.0 * spread_abs / max(entry, 1e-9), 5.0 * tick_size / max(entry, 1e-9))
        risk_pct = min(0.24, risk_pct)
        risk = entry * risk_pct
        rr1, rr2, rr3 = (1.15, 1.70, 2.30) if strong_extension else (1.00, 1.50, 2.00)
        if action == 'OPTION BUY':
            sl = entry - risk
            t1 = entry + risk * rr1
            t2 = entry + risk * rr2
            t3 = entry + risk * rr3
        else:
            sl = entry + risk
            t1 = entry - risk * rr1
            t2 = entry - risk * rr2
            t3 = entry - risk * rr3
        return sl, t1, t2, t3, rr1, risk_pct, risk

    engine._option_candidates = MethodType(_active_option_candidates, engine)
    engine._dynamic_targets = MethodType(_active_targets, engine)
    engine.precision_overlay_installed = True
    engine.active_flow_overlay_installed = True
    logger.info('[V41_ACTIVE] option BUY overlay installed; near-ATM selection; T1 1.00R')
    return engine
