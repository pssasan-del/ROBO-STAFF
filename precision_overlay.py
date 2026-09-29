"""Runtime overlay for ROBO STAFF V4 precision scalp.

It intentionally changes only the FIRST Delta engine:
- OPTION BUY only during this clean research epoch.
- ATM/1-OTM/2-OTM contract search with stricter ranking.
- Scalp-oriented target ladder: T1=1.20R, T2=1.85R, T3=2.50R.

MASTER MIND is untouched. No order/execution APIs are present.
"""
from __future__ import annotations

from types import MethodType

from config import logger
from delta_options_service import delta_options_service


def install_precision_overlay(engine):
    async def _precision_option_candidates(self, symbol, direction, snap):
        und = self._underlying(symbol)
        rows = await (delta_options_service.get_chain('XAUT') if und == 'GOLD' else delta_options_service.get_chain(und))
        parsed = []
        for row in rows:
            x = delta_options_service._snapshot(row)
            if x.get('strike') and x.get('expiry'):
                parsed.append(x)
        if not parsed and und == 'GOLD':
            rows = await delta_options_service.get_chain('PAXG')
            parsed = [delta_options_service._snapshot(r) for r in rows]
        if not parsed:
            return []

        expiries = sorted({x['expiry'] for x in parsed if x.get('expiry')})
        expiry = next((e for e in expiries if (self._minutes_to_expiry(e, und) or -1) >= 120), None)
        if not expiry:
            return []
        parsed = [x for x in parsed if x.get('expiry') == expiry]
        spot = next((float(x['spot_price']) for x in parsed if x.get('spot_price')), None)
        if not spot:
            return []
        strikes = sorted({float(x['strike']) for x in parsed if x.get('strike') is not None})
        if not strikes:
            return []
        atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))

        side = 'CE' if direction == 'BULLISH' else ('PE' if direction == 'BEARISH' else None)
        if not side:
            return []

        # Buying: prioritize ATM and 1 OTM for better delta / lower lottery behaviour.
        indexed = []
        for step in (0, 1, 2):
            idx = atm + step if side == 'CE' else atm - step
            if 0 <= idx < len(strikes):
                indexed.append((strikes[idx], step))
        targets = {s: d for s, d in indexed}
        pool = [x for x in parsed if x.get('side') == side and float(x.get('strike') or -1) in targets]
        if not pool:
            return []

        liqs = [float(x.get('volume') or 0) + 0.05 * float(x.get('oi') or 0) for x in pool]
        max_liq = max(liqs) if liqs else 1.0
        iv_values = []
        theta_ratios = []
        for x in [z for z in parsed if z.get('side') == side]:
            if x.get('bid_iv') is not None and x.get('ask_iv') is not None:
                iv_values.append((float(x['bid_iv']) + float(x['ask_iv'])) / 2.0)
            elif x.get('bid_iv') is not None:
                iv_values.append(float(x['bid_iv']))
            elif x.get('ask_iv') is not None:
                iv_values.append(float(x['ask_iv']))
        for x in pool:
            mid = (float(x['best_bid']) + float(x['best_ask'])) / 2 if x.get('best_bid') and x.get('best_ask') else 0
            if x.get('theta') is not None and mid > 0:
                theta_ratios.append(abs(float(x['theta'])) / mid)

        ranked = []
        for x in pool:
            y = self._contract_rank(
                und, 'OPTION BUY', x,
                distance=targets[float(x['strike'])],
                max_liquidity=max_liq,
                iv_values=iv_values,
                theta_ratios=theta_ratios,
            )
            if not y:
                continue
            # Extra precision preference: executable delta 0.28-0.62 and rank >=72.
            d = y.get('delta')
            ad = abs(float(d)) if d is not None else None
            if ad is not None and not (0.28 <= ad <= 0.62):
                continue
            if float(y.get('contract_rank_score') or 0) < 72:
                continue
            ranked.append(y)

        if not ranked:
            return []
        ranked.sort(key=lambda z: (-float(z.get('contract_rank_score') or 0), float(z.get('spread_pct') or 99), int(z.get('otm_distance') or 9)))
        best = ranked[0]
        logger.info('[V4_CONTRACT] %s %s selected %s rank=%.1f spread=%.2f%% delta=%s',
                    und, direction, best.get('symbol'), float(best.get('contract_rank_score') or 0),
                    float(best.get('spread_pct') or 0), best.get('delta'))
        return [('OPTION BUY', side, best)]

    def _precision_targets(self, action, entry, spread_abs, tick_size, strong_extension):
        # Wider than spread noise, but not the old fixed 12% rule.
        risk_pct = max(0.15, 3.0 * spread_abs / max(entry, 1e-9), 6.0 * tick_size / max(entry, 1e-9))
        risk_pct = min(0.24, risk_pct)
        risk = entry * risk_pct
        rr1, rr2, rr3 = (1.30, 2.00, 2.70) if strong_extension else (1.20, 1.85, 2.50)
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

    engine._option_candidates = MethodType(_precision_option_candidates, engine)
    engine._dynamic_targets = MethodType(_precision_targets, engine)
    engine.precision_overlay_installed = True
    logger.info('[V4_PRECISION] option BUY-only overlay installed; ATM/1OTM/2OTM ranking; T1 1.20R')
    return engine
