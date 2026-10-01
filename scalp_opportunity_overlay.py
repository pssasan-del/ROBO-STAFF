"""V4.3 professional scalp opportunity selector.

Adds 1m timing, no-chase logic, transaction-cost economics, futures OI/funding,
IV context and a signal-only comparison of OPTION BUY / OPTION SELL / FUTURE.
No private endpoints and no order execution.
"""
from __future__ import annotations

from types import MethodType

from config import logger
from delta_options_service import delta_options_service
from futures_context_service import futures_context_service
from option_premium_history_service import option_premium_history_service
from option_premium_analysis import ema, atr, rsi, williams_r, recent_cross, structure
from scalp_cost_model import futures_round_trip_cost_points, option_round_trip_cost, edge_after_cost


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _mid_iv(x):
    vals = [_f(x.get('bid_iv'), None), _f(x.get('ask_iv'), None)]
    vals = [v for v in vals if v is not None and v >= 0]
    return sum(vals) / len(vals) if vals else None


def _percentile(value, values):
    vals = sorted(float(x) for x in values if x is not None)
    if value is None or not vals:
        return None
    return 100.0 * sum(v <= float(value) for v in vals) / len(vals)


def _analyze_sell_premium(rows, overextended_atr=1.80):
    rows = list(rows or [])
    if len(rows) < 24:
        return {'sufficient': False, 'gate_pass': False, 'reason': 'INSUFFICIENT_PREMIUM_HISTORY', 'momentum_score': 0.0}
    closes = [_f(x.get('close')) for x in rows]
    close = closes[-1]
    e5, e9, e18 = ema(closes, 5), ema(closes, 9), ema(closes, 18)
    a = max(atr(rows, 14), 1e-12)
    downside_ext = (e5 - close) / a
    cross = recent_cross(closes, 9, 18, 3)
    rv = rsi(closes, 14)
    wr = williams_r(rows, 14)
    st = structure(rows)
    candle_below = close < e5
    alignment = e9 < e18
    cross_ok = cross.get('side') == 'BEARISH' and cross.get('bars_ago') is not None
    rsi_ok = rv <= 50.0
    wr_ok = wr <= -50.0
    structure_ok = st == 'LH/LL'
    overextended = downside_ext > float(overextended_atr)
    score = 0.0
    score += 30.0 if candle_below else 0.0
    score += 20.0 if alignment else 0.0
    score += 15.0 if cross_ok else 0.0
    score += 15.0 if rsi_ok else 0.0
    score += 10.0 if wr_ok else 0.0
    score += 10.0 if structure_ok else 0.0
    if overextended:
        score -= 15.0
    score = max(0.0, min(100.0, score))
    gate = bool(candle_below and not overextended)
    reason = 'OK' if gate else ('WAIT_RETEST_OVEREXTENDED' if overextended else 'PREMIUM_ABOVE_EMA5')
    return {
        'sufficient': True, 'gate_pass': gate, 'reason': reason, 'momentum_score': score,
        'close': close, 'ema5': e5, 'ema9': e9, 'ema18': e18, 'rsi': rv,
        'williams_r': wr, 'structure': st, 'extension_atr': downside_ext,
    }


async def _chain_context(engine, symbol, direction, expiry, spot, buy_symbol):
    und = engine._underlying(symbol)
    sources = ['XAUT', 'PAXG'] if und == 'GOLD' else [und]
    parsed = []
    for source in sources:
        try:
            rows = await delta_options_service.get_chain(source)
            parsed = [delta_options_service._snapshot(r) for r in rows]
            parsed = [x for x in parsed if x.get('expiry') == expiry and x.get('strike')]
            if parsed:
                break
        except Exception:
            continue
    if not parsed:
        return {'sell': {'available': False, 'reason': 'CHAIN_UNAVAILABLE'}, 'buy_iv_percentile': None, 'iv_regime': 'UNKNOWN'}

    same_buy = next((x for x in parsed if str(x.get('symbol')) == str(buy_symbol)), None)
    buy_side = 'CE' if direction == 'BULLISH' else 'PE'
    iv_values = [_mid_iv(x) for x in parsed if x.get('side') == buy_side]
    buy_iv = _mid_iv(same_buy or {})
    iv_pct = _percentile(buy_iv, iv_values)
    iv_regime = 'HIGH' if iv_pct is not None and iv_pct >= 70 else ('LOW' if iv_pct is not None and iv_pct <= 30 else 'MID')

    sell_side = 'PE' if direction == 'BULLISH' else 'CE'
    pool = [x for x in parsed if x.get('side') == sell_side and _f(x.get('best_bid')) > 0 and _f(x.get('best_ask')) > _f(x.get('best_bid'))]
    if not pool:
        return {'sell': {'available': False, 'reason': 'NO_OPPOSITE_SIDE_CONTRACT'}, 'buy_iv_percentile': iv_pct, 'iv_regime': iv_regime}
    strikes = sorted({_f(x.get('strike')) for x in pool})
    atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    idx = atm - 1 if sell_side == 'PE' else atm + 1
    wanted = strikes[idx] if 0 <= idx < len(strikes) else strikes[atm]
    x = min(pool, key=lambda z: abs(_f(z.get('strike')) - wanted))
    bid, ask = _f(x.get('best_bid')), _f(x.get('best_ask'))

    hist = await option_premium_history_service.get_history(str(x.get('symbol')), '5m', 90)
    if len(hist) < 24:
        mark = await option_premium_history_service.get_history(f'MARK:{x.get("symbol")}', '5m', 90)
        if len(mark) > len(hist):
            hist = mark
    pa = _analyze_sell_premium(hist)
    oi_rows = await option_premium_history_service.get_history(f'OI:{x.get("symbol")}', '5m', 60)
    oi_change = None
    if len(oi_rows) >= 4:
        vals = [_f(r.get('close')) for r in oi_rows[-4:]]
        base = sum(vals[:-1]) / 3.0
        oi_change = ((vals[-1] - base) / base * 100.0) if base > 0 else 0.0
    spread = ask - bid
    econ = option_round_trip_cost(bid, spot, spread)
    risk = max(0.18 * bid, spread * 2.0)
    gross = 0.35 * bid
    edge = edge_after_cost(gross_profit=gross, risk=risk, total_cost=econ['total_cost'])
    oi_support = oi_change is not None and oi_change > 0.20
    score = 0.55 * _f(pa.get('momentum_score')) + (20.0 if oi_support else 8.0) + (25.0 if edge['cost_gate_pass'] else 0.0)
    available = bool(pa.get('gate_pass') and edge['cost_gate_pass'])
    sell = {
        'available': available,
        'symbol': x.get('symbol'),
        'side': sell_side,
        'entry': bid,
        'spread_pct': spread / ((bid + ask) / 2.0) * 100.0,
        'premium_score': pa.get('momentum_score'),
        'premium_reason': pa.get('reason'),
        'oi_change_pct': oi_change,
        'oi_support': oi_support,
        'break_even_pct': econ.get('break_even_pct'),
        'gross_to_cost_multiple': edge.get('gross_to_cost_multiple'),
        'net_rr': edge.get('net_rr'),
        'score': max(0.0, min(100.0, score)),
        'reason': 'READY' if available else ('PREMIUM_NOT_WEAK' if not pa.get('gate_pass') else 'COST_WEAK'),
    }
    return {'sell': sell, 'buy_iv_percentile': iv_pct, 'iv_regime': iv_regime}


def install_scalp_opportunity_overlay(engine):
    original_analyze = engine.analyze_symbol

    async def _professional_analyze(self, symbol):
        candidates = await original_analyze(symbol)
        if not candidates:
            return []
        snap = self.last_scan.get(symbol, {}) or {}
        direction = str(snap.get('direction') or '')
        timing = await futures_context_service.analyze(symbol, direction, snap.get('setup_id') or '')
        if not timing.get('ready'):
            logger.info('[V43_TIMING] %s suppressed: %s age=%s ext=%.2f', symbol, timing.get('reason'), timing.get('setup_age_minutes'), _f(timing.get('extension_atr')))
            return []

        out = []
        for c in candidates:
            m = c.market or {}
            spot = _f(m.get('spot_price') or (snap.get('tf') or {}).get('5m', {}).get('price'))
            spread_abs = max(0.0, _f(m.get('ask')) - _f(m.get('bid')))
            opt_cost = option_round_trip_cost(c.premium, spot, spread_abs)
            opt_edge = edge_after_cost(
                gross_profit=abs(c.t1 - c.premium),
                risk=abs(c.premium - c.sl),
                total_cost=opt_cost['total_cost'],
            )
            if not opt_edge['cost_gate_pass']:
                logger.info('[V43_COST] %s %s suppressed: gross/cost=%.2f breakeven=%.2f%%', c.underlying, c.option_symbol, opt_edge['gross_to_cost_multiple'], opt_cost['break_even_pct'])
                continue

            fut_px = _f(timing.get('price'))
            inv = _f(snap.get('structural_invalidation'))
            atr5 = _f((snap.get('tf') or {}).get('5m', {}).get('atr'))
            fut_risk = abs(fut_px - inv) if inv > 0 else max(atr5, fut_px * 0.002)
            fut_risk = min(max(fut_risk, fut_px * 0.0015), fut_px * 0.0065)
            fut_gross = 1.85 * fut_risk
            fut_cost = futures_round_trip_cost_points(fut_px, entry_taker=True, exit_taker=True)
            fut_edge = edge_after_cost(gross_profit=fut_gross, risk=fut_risk, total_cost=fut_cost['total_cost_points'])
            future_score = 0.65 * _f(timing.get('score')) + (35.0 if fut_edge['cost_gate_pass'] else 0.0)

            chain = await _chain_context(self, symbol, direction, c.expiry, spot, c.option_symbol)
            sell = chain.get('sell') or {}
            option_buy_score = 0.50 * _f(m.get('premium_momentum_score')) + 0.18 * _f(m.get('oi_flow_score'), 50.0) + 0.12 * _f(timing.get('price_oi_direction_score'), 50.0) + 20.0
            option_buy_score = max(0.0, min(100.0, option_buy_score))
            matrix = {
                'future': {
                    'action': 'FUTURE LONG' if direction == 'BULLISH' else 'FUTURE SHORT',
                    'score': max(0.0, min(100.0, future_score)),
                    'ready': bool(fut_edge['cost_gate_pass']),
                    'entry': fut_px,
                    'risk_points': fut_risk,
                    'target_points': fut_gross,
                    'break_even_points': fut_cost['break_even_points'],
                    'net_rr': fut_edge['net_rr'],
                    'price_oi': timing.get('price_oi_label'),
                },
                'option_buy': {
                    'action': c.action,
                    'symbol': c.option_symbol,
                    'score': option_buy_score,
                    'ready': True,
                    'break_even_pct': opt_cost['break_even_pct'],
                    'fee_to_premium_pct': opt_cost['fee_to_premium_pct'],
                    'gross_to_cost_multiple': opt_edge['gross_to_cost_multiple'],
                    'net_rr': opt_edge['net_rr'],
                },
                'option_sell': sell,
            }
            choices = [('OPTION BUY', matrix['option_buy']['score'])]
            if matrix['future']['ready']:
                choices.append((matrix['future']['action'], matrix['future']['score']))
            if sell.get('available'):
                choices.append(('OPTION SELL', _f(sell.get('score'))))
            preferred = max(choices, key=lambda x: x[1])[0] if choices else 'NO TRADE'

            m.update({
                'v43_timing_ready': True,
                'v43_1m_score': timing.get('score'),
                'v43_1m_extension_atr': timing.get('extension_atr'),
                'v43_setup_age_minutes': timing.get('setup_age_minutes'),
                'futures_oi_change_pct': timing.get('oi_change_pct'),
                'futures_price_oi_label': timing.get('price_oi_label'),
                'funding_current': timing.get('funding_current'),
                'funding_bias': timing.get('funding_bias'),
                'option_iv_percentile': chain.get('buy_iv_percentile'),
                'option_iv_regime': chain.get('iv_regime'),
                'option_break_even_pct': opt_cost['break_even_pct'],
                'option_fee_to_premium_pct': opt_cost['fee_to_premium_pct'],
                'option_total_cost': opt_cost['total_cost'],
                'option_gross_to_cost_multiple': opt_edge['gross_to_cost_multiple'],
                'option_net_rr': opt_edge['net_rr'],
                'future_break_even_points': fut_cost['break_even_points'],
                'future_net_rr': fut_edge['net_rr'],
                'opportunity_matrix': matrix,
                'preferred_vehicle': preferred,
                'net_cost_gate_pass': True,
            })
            c.market = m
            c.reason = (c.reason + ' + 1M RETEST + COST EDGE + FUTURES OI/FUNDING').strip()
            out.append(c)
        return out

    engine.analyze_symbol = MethodType(_professional_analyze, engine)
    engine.professional_scalp_overlay_installed = True
    engine.cost_gate_installed = True
    engine.one_minute_timing_gate_installed = True
    logger.info('[V43_PRO] 1M retest/no-chase + futures OI/funding + cost gate + IV + instrument selector enabled')
    return engine
