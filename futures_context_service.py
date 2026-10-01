"""Public futures context for ROBO STAFF V4.3 professional scalping.

Reads completed 1m candles plus OI/FUNDING history from Delta public endpoints.
No credentials and no order methods.
"""
from __future__ import annotations

import time

from delta_market_service import delta_market_service
from option_premium_history_service import option_premium_history_service
from option_premium_analysis import ema, atr, analyze_oi_rows


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _closed(rows, seconds=60):
    now = time.time()
    out = list(rows or [])
    while out:
        ts = _f(out[-1].get('time'))
        if ts <= 0 or ts + seconds <= now - 2:
            break
        out.pop()
    return out


def classify_price_oi(price_change_pct, oi_change_pct):
    """Heuristic only; OI cannot uniquely identify trader intent."""
    p = _f(price_change_pct)
    o = None if oi_change_pct is None else _f(oi_change_pct)
    if o is None:
        return {'label': 'OI_UNAVAILABLE', 'bull_score': 50.0, 'bear_score': 50.0}
    pu, pd = p > 0.05, p < -0.05
    ou, od = o > 0.25, o < -0.25
    if pu and ou:
        return {'label': 'PRICE_UP_OI_UP', 'bull_score': 100.0, 'bear_score': 10.0}
    if pu and od:
        return {'label': 'PRICE_UP_OI_DOWN', 'bull_score': 70.0, 'bear_score': 25.0}
    if pd and ou:
        return {'label': 'PRICE_DOWN_OI_UP', 'bull_score': 10.0, 'bear_score': 100.0}
    if pd and od:
        return {'label': 'PRICE_DOWN_OI_DOWN', 'bull_score': 25.0, 'bear_score': 70.0}
    return {'label': 'PRICE_OI_MIXED', 'bull_score': 50.0, 'bear_score': 50.0}


def funding_summary(rows):
    vals = []
    for r in rows or []:
        try:
            vals.append(float(r.get('close')))
        except (TypeError, ValueError):
            pass
    if not vals:
        return {'available': False, 'current': None, 'mean': None, 'bias': 'NEUTRAL'}
    cur = vals[-1]
    mean = sum(vals[-12:]) / min(12, len(vals))
    # Context only, never a standalone trade direction.
    bias = 'LONG_CROWDED' if cur > 0.02 else ('SHORT_CROWDED' if cur < -0.02 else 'NEUTRAL')
    return {'available': True, 'current': cur, 'mean': mean, 'bias': bias}


class FuturesContextService:
    def __init__(self):
        self.cache = {}
        self.cache_seconds = 45.0

    async def analyze(self, symbol, direction, setup_id=''):
        key = f'{symbol}:{direction}:{setup_id}'
        cached = self.cache.get(key)
        if cached and time.time() - cached['at'] < self.cache_seconds:
            return dict(cached['data'])

        raw1 = await delta_market_service.get_candles(symbol, '1m', 40)
        one = _closed(raw1, 60)
        oi_rows = await option_premium_history_service.get_history(f'OI:{symbol}', '5m', 60)
        funding_rows = await option_premium_history_service.get_history(f'FUNDING:{symbol}', '5m', 60)
        if len(one) < 22:
            data = {'ready': False, 'reason': 'INSUFFICIENT_1M_HISTORY', 'rows': len(one)}
            self.cache[key] = {'at': time.time(), 'data': data}
            return data

        closes = [_f(x.get('close')) for x in one]
        px = closes[-1]
        e5, e9 = ema(closes, 5), ema(closes, 9)
        a = max(atr(one, 14), 1e-12)
        recent = one[-3:]
        prev3 = one[-4:-1]

        if direction == 'BULLISH':
            ema_ok = px > e5 > e9
            touched = any(_f(x.get('low')) <= max(e5, e9) + 0.15 * a for x in recent)
            resume = px > max(_f(x.get('high')) for x in prev3)
            hold = all(_f(x.get('close')) > e9 for x in one[-2:])
        else:
            ema_ok = px < e5 < e9
            touched = any(_f(x.get('high')) >= min(e5, e9) - 0.15 * a for x in recent)
            resume = px < min(_f(x.get('low')) for x in prev3)
            hold = all(_f(x.get('close')) < e9 for x in one[-2:])

        retest_trigger = bool(ema_ok and ((touched and hold) or resume))
        extension = abs(px - e5) / a
        no_chase = extension <= 1.35

        # setup_id ends with the completed 5m candle start epoch. Expire the
        # scalp opportunity after roughly three completed 1m bars.
        age_minutes = None
        fresh = True
        try:
            stamp = float(str(setup_id).rsplit(':', 1)[-1])
            close_time = stamp + 300.0
            age_minutes = max(0.0, (time.time() - close_time) / 60.0)
            fresh = age_minutes <= 3.25
        except Exception:
            pass

        look = min(3, len(closes) - 1)
        base = closes[-1 - look]
        price_change = ((px - base) / base * 100.0) if base else 0.0
        oi = analyze_oi_rows(oi_rows)
        poi = classify_price_oi(price_change, oi.get('change_pct'))
        funding = funding_summary(funding_rows)
        dir_oi = poi['bull_score'] if direction == 'BULLISH' else poi['bear_score']
        funding_score = 50.0
        if funding['bias'] == 'LONG_CROWDED':
            funding_score = 35.0 if direction == 'BULLISH' else 65.0
        elif funding['bias'] == 'SHORT_CROWDED':
            funding_score = 65.0 if direction == 'BULLISH' else 35.0

        score = (45.0 if retest_trigger else 0.0) + (20.0 if no_chase else 0.0) + 0.25 * dir_oi + 0.10 * funding_score
        score = max(0.0, min(100.0, score))
        ready = bool(retest_trigger and no_chase and fresh)
        reason = 'READY' if ready else ('EXPIRED' if not fresh else ('CHASE' if not no_chase else 'WAIT_1M_RETEST'))
        data = {
            'ready': ready,
            'reason': reason,
            'score': score,
            'price': px,
            'ema5': e5,
            'ema9': e9,
            'atr1': a,
            'extension_atr': extension,
            'retest_trigger': retest_trigger,
            'no_chase': no_chase,
            'setup_age_minutes': age_minutes,
            'fresh_window': fresh,
            'price_change_3bar_pct': price_change,
            'oi_change_pct': oi.get('change_pct'),
            'oi_trend': oi.get('trend'),
            'price_oi_label': poi['label'],
            'price_oi_direction_score': dir_oi,
            'funding_current': funding.get('current'),
            'funding_mean': funding.get('mean'),
            'funding_bias': funding.get('bias'),
        }
        self.cache[key] = {'at': time.time(), 'data': data}
        if len(self.cache) > 100:
            oldest = min(self.cache, key=lambda k: self.cache[k]['at'])
            self.cache.pop(oldest, None)
        return dict(data)


futures_context_service = FuturesContextService()
