import asyncio
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Dict, Optional

from config import settings, logger
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from ai_router import ai_router
from performance_store import performance_store
from market_research import research_store
from polish_policy import (
    POLISH_VERSION, MIN_ALERT_SCORE, STRONG_SCORE, ELITE_SCORE,
    BASE_COOLDOWN_MINUTES, SUCCESS_COOLDOWN_MINUTES, FAIL_COOLDOWN_MINUTES,
    CONTRACT_COOLDOWN_MINUTES, CORRELATION_WINDOW_MINUTES, CORRELATION_THRESHOLD,
    DAILY_SIGNAL_CAP, SPREAD_CAP_PCT, ai_adjustment, contract_gate, evaluate_entry,
    quality_label, quality_score,
)
from strategy_engine import ema, rsi, atr, vwap, directional_values, williams_r, fibonacci_pivots

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class Candidate:
    underlying: str
    direction: str
    action: str
    option_symbol: str
    strike: float
    expiry: str
    premium: float
    sl: float
    t1: float
    t2: float
    t3: float
    rr: float
    score: int
    adjusted_score: int
    quality: str
    ai_status: str
    ai_reason: str
    reason: str
    pattern: str
    setup_id: str
    market: dict
    created: float


class DeltaAutoSignalEngine:
    """Public-data signal engine. There are intentionally no private/order methods."""

    def __init__(self):
        self.running = True
        self.alert_cb = None
        self.last_signal: Optional[Candidate] = None
        self.last_scan_at = 0.0
        self.last_scan: Dict[str, dict] = {}
        self.last_alert: Dict[str, float] = {}
        self.pending: Dict[str, Candidate] = {}
        self.pending_state: Dict[str, dict] = {}
        self.post_sl: Dict[str, dict] = {}
        self.setup_seen: Dict[str, float] = {}
        self.last_direction_emit: Dict[tuple, float] = {}
        self.last_contract_emit: Dict[str, float] = {}
        self.last_resolution: Dict[tuple, dict] = {}
        self.recent_emit: Dict[str, dict] = {}
        self.loop_heartbeat = 0.0
        self.ai_last_status = 'NOT CHECKED'
        self.scan_errors = 0

    def set_alert_callback(self, cb):
        self.alert_cb = cb

    async def _alert(self, text):
        if self.alert_cb:
            await self.alert_cb(text)

    @staticmethod
    def _ts_seconds(v):
        try:
            x = float(v)
            return x / 1000.0 if x > 100_000_000_000 else x
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _closed_rows(cls, rows, seconds):
        """Use completed candles only; Delta history may include a forming candle."""
        now = time.time()
        out = list(rows)
        while out:
            ts = cls._ts_seconds(out[-1].get('time'))
            if ts <= 0 or ts + seconds <= now - 2:
                break
            out.pop()
        return out

    @staticmethod
    def _tf_state(rows):
        cl = [float(x['close']) for x in rows]
        px = cl[-1]
        e5, e9, e20 = ema(cl, 5), ema(cl, 9), ema(cl, 20)
        vw = vwap(rows, 30)
        adx, pdi, mdi = directional_values(rows, 14)
        wr = williams_r(rows, 14)
        rv = rsi(cl, 14)
        a = atr(rows, 14)
        history = rows[-21:-1]
        avg = sum(float(x.get('volume') or 0) for x in history) / max(1, len(history))
        rel = float(rows[-1].get('volume') or 0) / avg if avg else 0.0
        if e5 > e9 > e20 and px > vw and pdi > mdi:
            trend = 'BULLISH'
        elif e5 < e9 < e20 and px < vw and mdi > pdi:
            trend = 'BEARISH'
        else:
            trend = 'MIXED'
        return {
            'price': px, 'ema5': e5, 'ema9': e9, 'ema20': e20, 'vwap': vw,
            'adx': adx, 'plus_di': pdi, 'minus_di': mdi, 'williams_r': wr,
            'rsi': rv, 'atr': a, 'rel_volume': rel, 'trend': trend,
        }

    @staticmethod
    def _structure(rows):
        a, b = rows[-12:-6], rows[-6:]
        if not a or not b:
            return 'UNKNOWN'
        ah, al = max(x['high'] for x in a), min(x['low'] for x in a)
        bh, bl = max(x['high'] for x in b), min(x['low'] for x in b)
        if bh > ah and bl > al:
            return 'HH/HL'
        if bh < ah and bl < al:
            return 'LH/LL'
        return 'RANGE'

    @staticmethod
    def _ema_cross_5m(rows):
        """Newest cross on completed 5m bars; only bar 0/1 is relevant to V3.2."""
        closes = [float(r['close']) for r in rows]
        if len(closes) < 15:
            return {'side': 'NONE', 'bars_ago': None}
        for bars_ago in range(2):
            end = len(closes) - bars_ago
            now, prev = closes[:end], closes[:end - 1]
            e5, e9 = ema(now, 5), ema(now, 9)
            p5, p9 = ema(prev, 5), ema(prev, 9)
            if p5 <= p9 and e5 > e9:
                return {'side': 'BULLISH', 'bars_ago': bars_ago}
            if p5 >= p9 and e5 < e9:
                return {'side': 'BEARISH', 'bars_ago': bars_ago}
        return {'side': 'NONE', 'bars_ago': None}

    @staticmethod
    def _pivot_levels(piv):
        return {
            'pivot': float(piv.get('pivot') or 0),
            'r1': float(piv.get('fib_r1') or piv.get('r1') or 0),
            'r2': float(piv.get('fib_r2') or piv.get('r2') or 0),
            'r3': float(piv.get('fib_r3') or piv.get('r3') or 0),
            's1': float(piv.get('fib_s1') or piv.get('s1') or 0),
            's2': float(piv.get('fib_s2') or piv.get('s2') or 0),
            's3': float(piv.get('fib_s3') or piv.get('s3') or 0),
        }

    @classmethod
    def _pivot_position(cls, price, piv):
        p = cls._pivot_levels(piv)
        if not p['pivot']:
            return 'UNKNOWN'
        if p['r1'] and price > p['r1']:
            return 'ABOVE_R1'
        if p['s1'] and price < p['s1']:
            return 'BELOW_S1'
        return 'PIVOT_TO_R1' if price >= p['pivot'] else 'S1_TO_PIVOT'

    @staticmethod
    def _returns(rows, n=24):
        closes = [float(x['close']) for x in rows[-(n + 1):]]
        out = []
        for i in range(1, len(closes)):
            if closes[i - 1]:
                out.append(closes[i] / closes[i - 1] - 1.0)
        return out[-n:]

    @staticmethod
    def _corr(a, b):
        n = min(len(a), len(b))
        if n < 12:
            return 0.0
        a, b = a[-n:], b[-n:]
        ma, mb = sum(a)/n, sum(b)/n
        va = sum((x-ma)**2 for x in a); vb = sum((x-mb)**2 for x in b)
        if va <= 0 or vb <= 0:
            return 0.0
        return sum((a[i]-ma)*(b[i]-mb) for i in range(n)) / math.sqrt(va*vb)

    @classmethod
    def _next_obstacle_atr(cls, direction, price, atr5, daily_piv, five_piv, five_rows):
        if atr5 <= 0:
            return 0.0
        levels = []
        for piv in (daily_piv, five_piv):
            q = cls._pivot_levels(piv)
            levels.extend([q['r1'], q['r2'], q['r3'], q['s1'], q['s2'], q['s3'], q['pivot']])
        recent_hi = max(float(x['high']) for x in five_rows[-20:])
        recent_lo = min(float(x['low']) for x in five_rows[-20:])
        if direction == 'BULLISH':
            higher = [x for x in levels + [recent_hi] if x > price]
            return (min(higher)-price)/atr5 if higher else 99.0
        lower = [x for x in levels + [recent_lo] if 0 < x < price]
        return (price-max(lower))/atr5 if lower else 99.0

    async def _snapshot(self, symbol):
        lim = settings.DELTA_CANDLE_LIMIT
        sec = {'1m':60, '5m':300, '15m':900, '1h':3600, '1d':86400}
        tfs = {}
        for tf in ('1m', '5m', '15m', '1h', '1d'):
            want = lim if tf != '1d' else 42
            raw = await delta_market_service.get_candles(symbol, tf, want)
            rows = self._closed_rows(raw, sec[tf])
            if len(rows) < 30:
                raise RuntimeError(f'{symbol} {tf} insufficient closed candles={len(rows)}')
            tfs[tf] = {'rows': rows, 'state': self._tf_state(rows)}

        one, five = tfs['1m']['rows'], tfs['5m']['rows']
        s1 = tfs['1m']['state']; s5 = tfs['5m']['state']; s15 = tfs['15m']['state']; s1h = tfs['1h']['state']
        daily_piv = fibonacci_pivots(tfs['1d']['rows'][-1])
        five_piv = fibonacci_pivots(five[-2])

        bull_1h = s1h['ema5'] > s1h['ema9'] > s1h['ema20'] and s1h['price'] > s1h['vwap'] and s1h['plus_di'] > s1h['minus_di'] and s1h['adx'] >= 18
        bear_1h = s1h['ema5'] < s1h['ema9'] < s1h['ema20'] and s1h['price'] < s1h['vwap'] and s1h['minus_di'] > s1h['plus_di'] and s1h['adx'] >= 18
        bull_15 = s15['ema5'] > s15['ema9'] and s15['price'] > s15['vwap'] and s15['plus_di'] > s15['minus_di'] and s15['adx'] >= 18
        bear_15 = s15['ema5'] < s15['ema9'] and s15['price'] < s15['vwap'] and s15['minus_di'] > s15['plus_di'] and s15['adx'] >= 18
        direction = 'BULLISH' if bull_1h and bull_15 else ('BEARISH' if bear_1h and bear_15 else 'MIXED')

        st = self._structure(five)
        cross = self._ema_cross_5m(five)
        a5 = max(float(s5['atr']), 1e-12)
        current = five[-1]
        prev6 = five[-7:-1]
        bull_level = max(float(x['high']) for x in prev6)
        bear_level = min(float(x['low']) for x in prev6)
        pattern = 'NONE'; breakout_level = bull_level if direction == 'BULLISH' else bear_level

        if direction == 'BULLISH' and cross.get('side') == direction:
            if cross.get('bars_ago') == 0 and float(current['close']) > bull_level:
                pattern = 'BREAKOUT'
            elif cross.get('bars_ago') == 1 and len(five) >= 9:
                base = five[-8:-2]; level = max(float(x['high']) for x in base); crossbar = five[-2]
                held = float(crossbar['close']) > level
                touch = float(current['low']) <= max(level, s5['ema9']) + 0.15*a5
                close_back = float(current['close']) > max(level, s5['ema9'])
                if held and touch and close_back:
                    pattern = 'RETEST'; breakout_level = level
        elif direction == 'BEARISH' and cross.get('side') == direction:
            if cross.get('bars_ago') == 0 and float(current['close']) < bear_level:
                pattern = 'BREAKOUT'
            elif cross.get('bars_ago') == 1 and len(five) >= 9:
                base = five[-8:-2]; level = min(float(x['low']) for x in base); crossbar = five[-2]
                held = float(crossbar['close']) < level
                touch = float(current['high']) >= min(level, s5['ema9']) - 0.15*a5
                close_back = float(current['close']) < min(level, s5['ema9'])
                if held and touch and close_back:
                    pattern = 'RETEST'; breakout_level = level

        price_ema_aligned = (direction == 'BULLISH' and s5['price'] > s5['ema5'] > s5['ema9']) or (direction == 'BEARISH' and s5['price'] < s5['ema5'] < s5['ema9'])

        one_prev3 = one[-4:-1]
        one_breakout = False; one_hold = False
        if direction == 'BULLISH':
            one_breakout = s1['price'] > max(float(x['high']) for x in one_prev3)
            one_hold = len(one) >= 2 and all(float(x['close']) > breakout_level for x in one[-2:])
            one_ema = s1['price'] > s1['ema5'] > s1['ema9'] and s1['plus_di'] > s1['minus_di']
        elif direction == 'BEARISH':
            one_breakout = s1['price'] < min(float(x['low']) for x in one_prev3)
            one_hold = len(one) >= 2 and all(float(x['close']) < breakout_level for x in one[-2:])
            one_ema = s1['price'] < s1['ema5'] < s1['ema9'] and s1['minus_di'] > s1['plus_di']
        else:
            one_ema = False
        one_trigger = bool(one_ema and (one_breakout or one_hold))

        daily_zone = self._pivot_position(s5['price'], daily_piv)
        five_zone = self._pivot_position(s5['price'], five_piv)
        dp, fp = self._pivot_levels(daily_piv), self._pivot_levels(five_piv)
        pivot_extension_valid = True
        if direction == 'BULLISH' and (daily_zone == 'ABOVE_R1' or five_zone == 'ABOVE_R1'):
            refs = [x for x in (dp['r1'], fp['r1']) if x > 0 and x < s5['price']]
            ref = max(refs) if refs else 0
            pivot_extension_valid = bool(ref and s5['price']-ref <= 0.35*a5 and float(current['low']) <= ref + 0.15*a5)
        elif direction == 'BEARISH' and (daily_zone == 'BELOW_S1' or five_zone == 'BELOW_S1'):
            refs = [x for x in (dp['s1'], fp['s1']) if x > s5['price']]
            ref = min(refs) if refs else 0
            pivot_extension_valid = bool(ref and ref-s5['price'] <= 0.35*a5 and float(current['high']) >= ref - 0.15*a5)

        vwap_distance_atr = abs(s5['price']-s5['vwap'])/a5
        ema9_distance_atr = abs(s5['price']-s5['ema9'])/a5
        compression = abs(s5['ema5']-s5['ema20'])/max(s5['price'],1) < 0.0004 and s5['rel_volume'] < 1.10
        over = vwap_distance_atr > 2.0 or ema9_distance_atr > 1.0
        choppy = st == 'RANGE' or s5['adx'] < 22 or compression
        breakout_extension_atr = abs(s5['price']-breakout_level)/a5 if breakout_level else 99.0
        next_room = self._next_obstacle_atr(direction, s5['price'], a5, daily_piv, five_piv, five)

        recent_low = min(float(x['low']) for x in five[-6:])
        recent_high = max(float(x['high']) for x in five[-6:])
        if direction == 'BULLISH':
            supports = [recent_low, float(s5['ema20'])] + [x for x in (dp['pivot'], fp['pivot']) if x > 0]
            structural_invalidation = min(supports) - 0.25*a5
        elif direction == 'BEARISH':
            resist = [recent_high, float(s5['ema20'])] + [x for x in (dp['pivot'], fp['pivot']) if x > 0]
            structural_invalidation = max(resist) + 0.25*a5
        else:
            structural_invalidation = 0.0

        stamp = str(five[-1].get('time') or len(five))
        setup_id = f'{symbol}:{direction}:{pattern}:{stamp}'
        snap = {
            'symbol': symbol, 'direction': direction, 'structure': st, 'pattern': pattern,
            'setup_id': setup_id, 'daily_pivots': daily_piv, 'five_pivots': five_piv,
            'daily_zone': daily_zone, 'five_zone': five_zone,
            'ema_cross_5m': cross, 'price_ema_aligned': price_ema_aligned,
            'one_min_trigger': one_trigger, 'one_min_breakout': one_breakout,
            'one_min_ema_hold': bool(one_ema), 'choppy': choppy, 'overextended': over,
            'pivot_extension_valid': pivot_extension_valid,
            'distance_to_next_pivot_atr': next_room, 'breakout_extension_atr': breakout_extension_atr,
            'vwap_distance_atr': vwap_distance_atr, 'ema9_distance_atr': ema9_distance_atr,
            'breakout_level': breakout_level, 'structural_invalidation': structural_invalidation,
            'returns5_24': self._returns(five, 24), 'last_closed_5m': float(five[-1]['close']),
            'tf': {k: v['state'] for k, v in tfs.items()},
        }
        snap['base_score'] = quality_score(self._underlying(symbol), snap, 0.0)
        snap['score'] = snap['base_score']
        return snap

    @staticmethod
    def _underlying(symbol):
        return 'BTC' if symbol == 'BTCUSD' else ('ETH' if symbol == 'ETHUSD' else 'GOLD')

    @staticmethod
    def _minutes_to_expiry(expiry, underlying):
        try:
            d = datetime.fromisoformat(str(expiry)).date()
        except (TypeError, ValueError):
            return None
        clock = dt_time(21, 30) if underlying == 'GOLD' else dt_time(17, 30)
        exp_dt = datetime.combine(d, clock, tzinfo=IST)
        return (exp_dt - datetime.now(IST)).total_seconds()/60.0

    @staticmethod
    def _percentile(value, values):
        vals = sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
        if value is None or not vals:
            return None
        v = float(value)
        below = sum(x <= v for x in vals)
        return 100.0 * below / len(vals)

    @staticmethod
    def _component_score_band(value, lo, hi, preferred):
        if value is None:
            return None
        v = abs(float(value))
        if v < lo or v > hi:
            return 0.0
        half = max((hi-lo)/2.0, 1e-9)
        return max(0.0, 100.0 - abs(v-preferred)/half*100.0)

    def _contract_rank(self, underlying, action, x, *, distance, max_liquidity, iv_values, theta_ratios):
        bid, ask = x.get('best_bid'), x.get('best_ask')
        if bid is None or ask is None or bid <= 0 or ask <= bid:
            return None
        mid = (bid+ask)/2.0; spread_pct=(ask-bid)/mid*100.0
        cap = SPREAD_CAP_PCT.get(underlying, 3.0)
        if spread_pct > cap:
            return None
        liquidity = float(x.get('volume') or 0) + 0.05*float(x.get('oi') or 0)
        spread_score = max(0.0, 100.0*(1.0-spread_pct/cap))
        liquidity_score = min(100.0, 100.0*liquidity/max(max_liquidity, 1e-9))
        distance_score = {1:100.0, 2:80.0, 3:60.0}.get(distance, 0.0)

        d = x.get('delta')
        if action == 'OPTION BUY':
            delta_score = self._component_score_band(d, 0.25, 0.50, 0.35)
            iv_lo, iv_hi = 20.0, 70.0
        else:
            delta_score = self._component_score_band(d, 0.15, 0.35, 0.25)
            iv_lo, iv_hi = 40.0, 85.0

        iv_mid = None
        if x.get('bid_iv') is not None and x.get('ask_iv') is not None:
            iv_mid = (float(x['bid_iv'])+float(x['ask_iv']))/2.0
        elif x.get('bid_iv') is not None:
            iv_mid = float(x['bid_iv'])
        elif x.get('ask_iv') is not None:
            iv_mid = float(x['ask_iv'])
        iv_pct = self._percentile(iv_mid, iv_values)
        iv_score = None if iv_pct is None else (100.0 if iv_lo <= iv_pct <= iv_hi else max(0.0, 100.0-min(abs(iv_pct-iv_lo), abs(iv_pct-iv_hi))*3.0))

        theta_ratio = None
        if x.get('theta') is not None and mid > 0:
            theta_ratio = abs(float(x['theta']))/mid
        theta_pct = self._percentile(theta_ratio, theta_ratios)
        if theta_pct is None:
            theta_score = None
        elif action == 'OPTION BUY':
            theta_score = max(0.0, 100.0-theta_pct)
        else:
            theta_score = 100.0-abs(theta_pct-65.0)*1.5
            theta_score = max(0.0, min(100.0, theta_score))

        components = [
            (35.0, spread_score), (25.0, liquidity_score), (10.0, distance_score),
            (15.0, delta_score), (10.0, iv_score), (5.0, theta_score),
        ]
        used = [(w,s) for w,s in components if s is not None]
        total_w = sum(w for w,_ in used) or 1.0
        rank = sum(w*s for w,s in used)/total_w
        y = dict(x)
        y.update({
            'spread_pct': spread_pct, 'liquidity_metric': liquidity, 'otm_distance': distance,
            'iv_percentile': iv_pct, 'theta_ratio': theta_ratio, 'contract_rank_score': rank,
        })
        return y

    async def _option_candidates(self, symbol, direction, snap):
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
        expiry = next((e for e in expiries if (self._minutes_to_expiry(e, und) or -1) >= 90), None)
        if not expiry:
            return []
        parsed = [x for x in parsed if x.get('expiry') == expiry]
        spot = next((float(x['spot_price']) for x in parsed if x.get('spot_price')), None)
        if not spot:
            return []
        strikes = sorted({float(x['strike']) for x in parsed if x.get('strike') is not None})
        if not strikes:
            return []
        atm = min(range(len(strikes)), key=lambda i: abs(strikes[i]-spot))

        def pick(side, action):
            indexed=[]
            for step in (1,2,3):
                idx = atm+step if side == 'CE' else atm-step
                if 0 <= idx < len(strikes):
                    indexed.append((strikes[idx], step))
            targets={s:d for s,d in indexed}
            pool=[x for x in parsed if x.get('side') == side and float(x.get('strike') or -1) in targets]
            if not pool:
                return None
            liqs=[float(x.get('volume') or 0)+0.05*float(x.get('oi') or 0) for x in pool]
            max_liq=max(liqs) if liqs else 1.0
            iv_values=[]; theta_ratios=[]
            for x in [z for z in parsed if z.get('side') == side]:
                if x.get('bid_iv') is not None and x.get('ask_iv') is not None:
                    iv_values.append((float(x['bid_iv'])+float(x['ask_iv']))/2.0)
                elif x.get('bid_iv') is not None: iv_values.append(float(x['bid_iv']))
                elif x.get('ask_iv') is not None: iv_values.append(float(x['ask_iv']))
            for x in pool:
                mid=(float(x['best_bid'])+float(x['best_ask']))/2 if x.get('best_bid') and x.get('best_ask') else 0
                if x.get('theta') is not None and mid>0:
                    theta_ratios.append(abs(float(x['theta']))/mid)
            ranked=[]
            for x in pool:
                y=self._contract_rank(und, action, x, distance=targets[float(x['strike'])], max_liquidity=max_liq, iv_values=iv_values, theta_ratios=theta_ratios)
                if y and y['contract_rank_score'] >= 70:
                    ranked.append(y)
            if not ranked:
                return None
            ranked.sort(key=lambda z: (-z['contract_rank_score'], z['spread_pct'], z['otm_distance']))
            return ranked[0]

        if direction == 'BULLISH':
            return [('OPTION BUY','CE',pick('CE','OPTION BUY')),('OPTION SELL','PE',pick('PE','OPTION SELL'))]
        if direction == 'BEARISH':
            return [('OPTION BUY','PE',pick('PE','OPTION BUY')),('OPTION SELL','CE',pick('CE','OPTION SELL'))]
        return []

    async def _ai_review(self, snap, option, action, python_score):
        if not settings.DELTA_AI_CONFIRMATION:
            return {'decision':'NO-AI','confidence':0,'risk_flags':[],'short_reason':'disabled'}
        payload = {
            'underlying': self._underlying(snap['symbol']), 'direction': snap['direction'], 'action': action,
            'python_score': python_score, 'pattern': snap.get('pattern'),
            'ema_cross_bars_ago': (snap.get('ema_cross_5m') or {}).get('bars_ago'),
            'structure_5m': snap.get('structure'), 'trend_1h': (snap.get('tf') or {}).get('1h',{}).get('trend'),
            'trend_15m': (snap.get('tf') or {}).get('15m',{}).get('trend'),
            'adx_5m': (snap.get('tf') or {}).get('5m',{}).get('adx'),
            'plus_di_5m': (snap.get('tf') or {}).get('5m',{}).get('plus_di'),
            'minus_di_5m': (snap.get('tf') or {}).get('5m',{}).get('minus_di'),
            'rvol_5m': (snap.get('tf') or {}).get('5m',{}).get('rel_volume'),
            'rsi_5m': (snap.get('tf') or {}).get('5m',{}).get('rsi'),
            'williams_5m': (snap.get('tf') or {}).get('5m',{}).get('williams_r'),
            'daily_zone': snap.get('daily_zone'), 'five_min_zone': snap.get('five_zone'),
            'distance_from_vwap_atr': snap.get('vwap_distance_atr'),
            'distance_to_next_pivot_atr': snap.get('distance_to_next_pivot_atr'),
            'option': {
                'symbol': option.get('symbol'), 'entry': option.get('entry'), 'bid': option.get('best_bid'),
                'ask': option.get('best_ask'), 'spread_pct': option.get('spread_pct'), 'oi': option.get('oi'),
                'volume': option.get('volume'), 'delta': option.get('delta'), 'iv_percentile': option.get('iv_percentile'),
                'minutes_to_expiry': option.get('minutes_to_expiry'),
            },
        }
        system = (
            'You are a second-opinion risk reviewer for a deterministic crypto-options signal engine. '
            'You MUST NOT invent missing data. Do not recommend execution. Assess only false-breakout risk, '
            'trend agreement, extension, liquidity, and internal consistency. Return JSON only: '
            '{"decision":"CONFIRM|REJECT|WAIT","confidence":0-100,"risk_flags":["..."],'
            '"short_reason":"maximum 20 words"}.'
        )
        try:
            raw = await ai_router.answer(json.dumps(payload, separators=(',',':')), system)
            if raw.startswith('AI response unavailable'):
                return {'decision':'NO-AI','confidence':0,'risk_flags':['provider unavailable'],'short_reason':'provider unavailable'}
            raw=raw.strip().removeprefix('```json').removesuffix('```').strip(); obj=json.loads(raw)
            decision=str(obj.get('decision') or '').upper(); confidence=int(obj.get('confidence') or 0)
            if decision not in {'CONFIRM','REJECT','WAIT'}:
                raise ValueError('invalid decision')
            flags=obj.get('risk_flags') if isinstance(obj.get('risk_flags'),list) else []
            return {'decision':decision,'confidence':max(0,min(100,confidence)),'risk_flags':[str(x)[:60] for x in flags[:4]],'short_reason':str(obj.get('short_reason') or '')[:120]}
        except Exception as exc:
            logger.warning('[DELTA_AI] no confirmation: %s', exc)
            return {'decision':'NO-AI','confidence':0,'risk_flags':['invalid/unavailable'],'short_reason':'invalid/unavailable'}

    @staticmethod
    def _dynamic_targets(action, entry, spread_abs, tick_size, strong_extension):
        risk_pct=max(0.12, 2.5*spread_abs/max(entry,1e-9), 4.0*tick_size/max(entry,1e-9))
        risk_pct=min(0.20, risk_pct)
        risk=entry*risk_pct
        rr1,rr2,rr3=(2.0,2.5,3.2) if strong_extension else (1.85,2.30,3.00)
        if action == 'OPTION BUY':
            sl=entry-risk; t1=entry+risk*rr1; t2=entry+risk*rr2; t3=entry+risk*rr3
        else:
            sl=entry+risk; t1=entry-risk*rr1; t2=entry-risk*rr2; t3=entry-risk*rr3
        return sl,t1,t2,t3,rr1,risk_pct,risk

    async def analyze_symbol(self, symbol):
        snap=await self._snapshot(symbol); self.last_scan[symbol]=snap
        underlying=self._underlying(symbol)
        allowed,reason=evaluate_entry(underlying,'SETUP',snap)
        if not allowed:
            logger.info('[V32_ENTRY] %s filtered: %s', underlying, reason)
            return []

        out=[]
        for action,side,opt in await self._option_candidates(symbol,snap['direction'],snap):
            if not opt:
                continue
            bid,ask=opt.get('best_bid'),opt.get('best_ask')
            if bid is None or ask is None:
                continue
            entry=float(ask if action == 'OPTION BUY' else bid)
            mte=self._minutes_to_expiry(opt.get('expiry'),underlying)
            opt['minutes_to_expiry']=mte; opt['entry']=entry

            ok,creason,cmetrics=contract_gate(
                underlying,action,entry=entry,bid=bid,ask=ask,spot=opt.get('spot_price'),delta=opt.get('delta'),
                tick_size=0.01,minutes_to_expiry=mte,python_score=100,
            )
            if not ok:
                logger.info('[V32_CONTRACT] %s %s %s filtered: %s',underlying,action,opt.get('symbol'),creason);continue
            final_score=quality_score(underlying,snap,float(opt.get('contract_rank_score') or 0)/10.0)
            if final_score < MIN_ALERT_SCORE:
                logger.info('[V32_SCORE] %s %s score=%s<%s',underlying,action,final_score,MIN_ALERT_SCORE);continue
            ok,creason,cmetrics=contract_gate(
                underlying,action,entry=entry,bid=bid,ask=ask,spot=opt.get('spot_price'),delta=opt.get('delta'),
                tick_size=0.01,minutes_to_expiry=mte,python_score=final_score,
            )
            if not ok:
                logger.info('[V32_CONTRACT] %s %s %s filtered: %s',underlying,action,opt.get('symbol'),creason);continue

            spread_abs=float(ask)-float(bid); tick_size=0.01
            strong_ext=final_score>=92 and float(snap['tf']['5m']['adx'])>=28 and float(snap['tf']['5m']['rel_volume'])>=1.50 and float(snap['distance_to_next_pivot_atr'])>=1.50
            sl,t1,t2,t3,rr1,risk_pct,risk=self._dynamic_targets(action,entry,spread_abs,tick_size,strong_ext)
            if min(sl,t1,t2,t3) <= 0 or risk < max(4*tick_size,2.5*spread_abs):
                continue

            ai=await self._ai_review(snap,opt,action,final_score)
            adj=max(0,min(100,final_score+ai_adjustment(ai['decision'],ai['confidence'])))
            ai_status = 'NO-AI' if ai['decision']=='NO-AI' else f"{ai['decision']} ({ai['confidence']}%)"
            why=f"{snap['pattern']} + {snap['structure']} + HTF aligned + DI/RVOL + pivot room {snap['distance_to_next_pivot_atr']:.2f}ATR"
            market={
                'bid':float(bid),'ask':float(ask),'mid':(float(bid)+float(ask))/2.0,
                'spread_pct':float(opt.get('spread_pct') or cmetrics.get('spread_pct') or 0),
                'spread_abs':spread_abs,'tick_size':tick_size,'oi':float(opt.get('oi') or 0),'volume':float(opt.get('volume') or 0),
                'delta':opt.get('delta'),'bid_iv':opt.get('bid_iv'),'ask_iv':opt.get('ask_iv'),'iv_percentile':opt.get('iv_percentile'),
                'theta':opt.get('theta'),'theta_ratio':opt.get('theta_ratio'),'mark_price':opt.get('mark_price'),'last_price':opt.get('last_price'),
                'spot_price':opt.get('spot_price'),'entry_source':'ASK' if action=='OPTION BUY' else 'BID',
                'otm_distance':opt.get('otm_distance'),'contract_rank_score':opt.get('contract_rank_score'),
                'minutes_to_expiry':mte,'risk_pct':risk_pct*100.0,'risk_abs':risk,
                'underlying_invalidation':snap.get('structural_invalidation'),'why':why,
            }
            out.append(Candidate(
                underlying,snap['direction'],action,opt['symbol'],float(opt['strike']),opt['expiry'],entry,sl,t1,t2,t3,rr1,
                final_score,adj,quality_label(final_score),ai_status,ai.get('short_reason') or '',why,snap['pattern'],snap['setup_id'],market,time.time()
            ))
        return out

    def format_signal(self,c):
        m=c.market or {}
        return (
            f"🔥 *V7.1 {c.action}* — *{c.underlying} {c.direction}*\n"
            f"Contract: \`{c.option_symbol}\` | Quality: *{c.quality}* ({c.adjusted_score}/100)\n"
            f"Entry: \`{c.premium:.6g}\` | SL: \`{c.sl:.6g}\`\n"
            f"T1: \`{c.t1:.6g}\` | T2: \`{c.t2:.6g}\` | T3: \`{c.t3:.6g}\`\n"
            f"RR: \`1:{c.rr:.2f}\` | Pattern: *{c.pattern}*\n"
            f"Reason: {m.get('why') or c.reason}\n"
            "📡 *SIGNAL ONLY*"
        )

    @staticmethod
    def _exit_price(c, option_snapshot):
        if not option_snapshot:
            return None
        value = option_snapshot.get('best_bid') if c.action == 'OPTION BUY' else option_snapshot.get('best_ask')
        try:return float(value) if value is not None else None
        except (TypeError,ValueError):return None

    @staticmethod
    def _r_move(c, px):
        risk=abs(c.premium-c.sl)
        if risk <= 0 or px is None:return 0.0
        pnl=(px-c.premium) if c.action=='OPTION BUY' else (c.premium-px)
        return pnl/risk

    @staticmethod
    def _excursion(c,px):
        if not c.premium or px is None:return 0.0,0.0,0.0,0.0
        pct=((px-c.premium)/c.premium*100.0) if c.action=='OPTION BUY' else ((c.premium-px)/c.premium*100.0)
        r=DeltaAutoSignalEngine._r_move(c,px)
        return max(0,pct),max(0,-pct),max(0,r),max(0,-r)

    def _underlying_snap_for(self,c):
        return self.last_scan.get({'BTC':'BTCUSD','ETH':'ETHUSD','GOLD':'XAUTUSD'}.get(c.underlying,''),{})

    async def _resolve_special(self,key,c,outcome,px,elapsed):
        r=self._r_move(c,px)
        research_store.resolve(key,outcome,elapsed,px,outcome_r=r)
        performance_store.resolve_special(c.action,outcome,c.underlying,c.ai_status,elapsed)
        self.pending.pop(key,None);self.pending_state.pop(key,None)
        self.last_resolution[(c.underlying,c.direction)]={'time':time.time(),'outcome':outcome}
        recent=self.recent_emit.get(c.underlying)
        if recent and recent.get('key')==key:recent['resolved']=True
        await self._alert(f"⏱ {outcome} — `{c.option_symbol}` | {c.action} | Executable exit `{px:.6g}` | `{r:+.2f}R`")

    async def _monitor_pending(self):
        for key,c in list(self.pending.items()):
            try:
                und='GOLD' if c.underlying=='GOLD' else c.underlying
                snap=await (delta_options_service.get_gold_strike_snapshot(c.strike,c.expiry) if und=='GOLD' else delta_options_service.get_strike_snapshot(und,c.strike,c.expiry))
                side='ce' if c.option_symbol.startswith('C-') else 'pe';o=snap.get(side);px=self._exit_price(c,o)
                if px is None:continue
                elapsed=time.time()-c.created
                st=self.pending_state.setdefault(key,{'sl_breaches':0,'weak_sent':False,'max_mfe_r':0.0})
                mfe,mae,mfe_r,mae_r=self._excursion(c,px);st['max_mfe_r']=max(st['max_mfe_r'],mfe_r)
                research_store.update_excursion(key,mfe,mae,mfe_r,mae_r)
                success=(px>=c.t1) if c.action=='OPTION BUY' else (px<=c.t1)
                premium_breach=(px<=c.sl) if c.action=='OPTION BUY' else (px>=c.sl)
                loss_r=max(0.0,-self._r_move(c,px))
                usnap=self._underlying_snap_for(c);uclose=float(usnap.get('last_closed_5m') or 0);inv=float((c.market or {}).get('underlying_invalidation') or 0)
                structural=(c.direction=='BULLISH' and inv and uclose<inv) or (c.direction=='BEARISH' and inv and uclose>inv)

                if success:
                    performance_store.resolve(c.action,True,c.underlying,c.ai_status,elapsed)
                    research_store.resolve(key,'T1',elapsed,px,outcome_r=c.rr)
                    self.pending.pop(key,None);self.pending_state.pop(key,None)
                    self.last_resolution[(c.underlying,c.direction)]={'time':time.time(),'outcome':'T1'}
                    recent=self.recent_emit.get(c.underlying)
                    if recent and recent.get('key')==key:recent['resolved']=True
                    await self._alert(f"✅ T1 SUCCESS — `{c.option_symbol}` | {c.action} | Executable exit `{px:.6g}` | `+{c.rr:.2f}R`")
                    continue

                if premium_breach:st['sl_breaches']+=1
                else:st['sl_breaches']=0
                failed=bool(structural or loss_r>=1.35 or st['sl_breaches']>=2)
                if failed:
                    performance_store.resolve(c.action,False,c.underlying,c.ai_status,elapsed)
                    research_store.resolve(key,'SL',elapsed,px,outcome_r=-min(max(loss_r,1.0),3.0))
                    self.pending.pop(key,None);self.pending_state.pop(key,None)
                    self.last_resolution[(c.underlying,c.direction)]={'time':time.time(),'outcome':'SL'}
                    recent=self.recent_emit.get(c.underlying)
                    if recent and recent.get('key')==key:recent['resolved']=True
                    if len(self.post_sl)>=50:
                        oldest=min(self.post_sl,key=lambda k:self.post_sl[k]['failed_at']);self.post_sl.pop(oldest,None)
                    self.post_sl[key]={'candidate':c,'failed_at':time.time(),'t1_seen':False,'t2_seen':False}
                    cause='STRUCTURE' if structural else ('SEVERE' if loss_r>=1.35 else '2x CONFIRMED')
                    await self._alert(f"🛑 SL / FAILED ({cause}) — `{c.option_symbol}` | {c.action} | Executable exit `{px:.6g}`")
                    continue

                if elapsed>=900 and st['max_mfe_r']<0.50 and not st['weak_sent']:
                    st['weak_sent']=True;await self._alert(f"⚠️ WEAK/STALLED — `{c.option_symbol}` | {c.action} | <0.5R MFE after 15m")
                s5=(usnap.get('tf') or {}).get('5m') or {}
                ema_broken=(c.direction=='BULLISH' and not (s5.get('price',0)>s5.get('ema5',0)>s5.get('ema9',0))) or (c.direction=='BEARISH' and not (s5.get('price',0)<s5.get('ema5',0)<s5.get('ema9',0)))
                if elapsed>=1800 and ema_broken:
                    await self._resolve_special(key,c,'INVALIDATED',px,elapsed);continue
                max_hold=3600 if c.underlying=='GOLD' else 2700
                if elapsed>=max_hold:
                    await self._resolve_special(key,c,'STALE',px,elapsed);continue
            except Exception as exc:
                logger.debug('[DELTA_MONITOR] %s: %s',key,exc)

    async def _monitor_post_sl(self):
        now=time.time()
        for key,item in list(self.post_sl.items()):
            c=item['candidate']
            if now-item['failed_at']>7200:self.post_sl.pop(key,None);continue
            try:
                und='GOLD' if c.underlying=='GOLD' else c.underlying
                snap=await (delta_options_service.get_gold_strike_snapshot(c.strike,c.expiry) if und=='GOLD' else delta_options_service.get_strike_snapshot(und,c.strike,c.expiry))
                side='ce' if c.option_symbol.startswith('C-') else 'pe';px=self._exit_price(c,snap.get(side))
                if px is None:continue
                t1=(px>=c.t1) if c.action=='OPTION BUY' else (px<=c.t1);t2=(px>=c.t2) if c.action=='OPTION BUY' else (px<=c.t2)
                if t1 and not item['t1_seen']:
                    item['t1_seen']=True;performance_store.mark_sl_recovery('t1');research_store.mark_recovery(key)
                if t2 and not item['t2_seen']:
                    item['t2_seen']=True;performance_store.mark_sl_recovery('t2');research_store.mark_recovery(key,'t2')
                if item['t2_seen']:self.post_sl.pop(key,None)
            except Exception as exc:logger.debug('[DELTA_POST_SL] %s: %s',key,exc)

    def _prune_runtime_memory(self):
        cutoff=time.time()-86400*2
        for d in (self.setup_seen,self.last_contract_emit,self.last_alert):
            for k,v in list(d.items()):
                if float(v)<cutoff:d.pop(k,None)

    def _correlation_suppression(self,c):
        if c.underlying not in {'BTC','ETH'}:return False,''
        other='ETH' if c.underlying=='BTC' else 'BTC';rec=self.recent_emit.get(other)
        if not rec or rec.get('resolved') or rec.get('direction')!=c.direction:return False,''
        age=time.time()-float(rec.get('time') or 0)
        if age>CORRELATION_WINDOW_MINUTES*60:return False,''
        a=self._underlying_snap_for(c).get('returns5_24') or []
        osym='ETHUSD' if other=='ETH' else 'BTCUSD';b=(self.last_scan.get(osym) or {}).get('returns5_24') or []
        corr=self._corr(a,b)
        if abs(corr)>=CORRELATION_THRESHOLD and c.score < int(rec.get('score') or 0)+8:
            return True,f'{other} same-direction corr={corr:.2f} within {CORRELATION_WINDOW_MINUTES}m'
        return False,''

    def _cooldown_reason(self,c):
        now=time.time();pair=(c.underlying,c.direction)
        if c.setup_id in self.setup_seen:return 'setup-id already alerted'
        if any(x.underlying==c.underlying for x in self.pending.values()):return 'one unresolved signal already active for underlying'
        if performance_store.signal_count_today(c.underlying)>=DAILY_SIGNAL_CAP.get(c.underlying,4):return 'daily underlying signal cap reached'
        last=self.last_direction_emit.get(pair)
        if last and now-last<BASE_COOLDOWN_MINUTES*60:return f'{BASE_COOLDOWN_MINUTES}m symbol/direction cooldown'
        lr=self.last_resolution.get(pair)
        if lr:
            need=SUCCESS_COOLDOWN_MINUTES if lr.get('outcome')=='T1' else FAIL_COOLDOWN_MINUTES
            if now-float(lr.get('time') or 0)<need*60:return f'{need}m post-{lr.get("outcome")} cooldown'
        lc=self.last_contract_emit.get(c.option_symbol)
        if lc and now-lc<CONTRACT_COOLDOWN_MINUTES*60:return f'{CONTRACT_COOLDOWN_MINUTES}m contract cooldown'
        corr,reason=self._correlation_suppression(c)
        if corr:return reason
        return ''

    def _features(self,c,snap,*,suppressed=False,suppression_reason=''):
        tf=snap.get('tf') or {};s5=tf.get('5m') or {};s15=tf.get('15m') or {};s1h=tf.get('1h') or {};m=c.market or {};dp=self._pivot_levels(snap.get('daily_pivots') or {});fp=self._pivot_levels(snap.get('five_pivots') or {})
        return {
            'research_epoch':POLISH_VERSION,'pattern':c.pattern,'structure':snap.get('structure'),'score':c.score,'adjusted_score':c.adjusted_score,'direction':c.direction,
            'ema_cross_5m':snap.get('ema_cross_5m'),'price_ema_aligned':snap.get('price_ema_aligned'),'one_min_trigger':snap.get('one_min_trigger'),
            'adx5':s5.get('adx'),'plus_di5':s5.get('plus_di'),'minus_di5':s5.get('minus_di'),'rvol5':s5.get('rel_volume'),'atr5':s5.get('atr'),'rsi5':s5.get('rsi'),'wr5':s5.get('williams_r'),
            'trend15':s15.get('trend'),'trend1h':s1h.get('trend'),'vwap_distance_atr':snap.get('vwap_distance_atr'),'distance_to_next_pivot_atr':snap.get('distance_to_next_pivot_atr'),
            'daily_pivot':dp.get('pivot'),'daily_s1':dp.get('s1'),'daily_r1':dp.get('r1'),'daily_zone':snap.get('daily_zone'),'five_pivot':fp.get('pivot'),'five_s1':fp.get('s1'),'five_r1':fp.get('r1'),'five_zone':snap.get('five_zone'),
            'option_bid':m.get('bid'),'option_ask':m.get('ask'),'option_spread_pct':m.get('spread_pct'),'option_oi':m.get('oi'),'option_volume':m.get('volume'),'option_delta':m.get('delta'),'option_iv_percentile':m.get('iv_percentile'),'option_theta_ratio':m.get('theta_ratio'),
            'otm_distance':m.get('otm_distance'),'contract_rank_score':m.get('contract_rank_score'),'minutes_to_expiry':m.get('minutes_to_expiry'),'risk_pct':m.get('risk_pct'),'entry_source':m.get('entry_source'),
            'ai_status':c.ai_status,'correlation_suppressed':suppressed,'suppression_reason':suppression_reason,'polish_version':POLISH_VERSION,
        }

    async def scan_once(self):
        self.last_scan_at=time.time();results={};self._prune_runtime_memory()
        for symbol in settings.delta_symbols():
            try:
                candidates=await self.analyze_symbol(symbol);results[symbol]={'status':'SIGNAL' if candidates else 'NO_TRADE','count':len(candidates)}
                for c in candidates:
                    snap=self._underlying_snap_for(c);reason=self._cooldown_reason(c)
                    key=f'{POLISH_VERSION}:{c.underlying}:{c.option_symbol}:{c.action}:{c.direction}:{c.setup_id}'
                    if reason:
                        if reason.startswith('ETH same-direction') or reason.startswith('BTC same-direction'):
                            research_store.add_suppressed(key,c,self._features(c,snap,suppressed=True,suppression_reason=reason),reason)
                        logger.info('[V32_COOLDOWN] %s suppressed: %s',key,reason);continue
                    now=time.time();self.setup_seen[c.setup_id]=now;self.last_direction_emit[(c.underlying,c.direction)]=now;self.last_contract_emit[c.option_symbol]=now
                    self.last_signal=c;self.last_alert[key]=now
                    if len(self.pending)>=30:
                        oldest=min(self.pending,key=lambda k:self.pending[k].created);self.pending.pop(oldest,None);self.pending_state.pop(oldest,None)
                    research_store.add(key,c,self._features(c,snap));self.pending[key]=c;self.pending_state[key]={'sl_breaches':0,'weak_sent':False,'max_mfe_r':0.0}
                    performance_store.new_signal(c.action,c.ai_status,c.underlying)
                    self.recent_emit[c.underlying]={'key':key,'time':now,'direction':c.direction,'score':c.score,'resolved':False}
                    await self._alert(self.format_signal(c))
            except Exception as exc:
                self.scan_errors+=1;results[symbol]={'status':'ERROR','error':str(exc)[:160]};logger.warning('[DELTA_AUTO] %s failed: %s',symbol,exc)
        await self._monitor_pending();await self._monitor_post_sl();return results

    async def loop(self):
        while True:
            self.loop_heartbeat=time.time()
            try:
                if self.running and settings.DELTA_AUTO_SIGNAL_ENGINE:await self.scan_once()
            except asyncio.CancelledError:raise
            except Exception as exc:self.scan_errors+=1;logger.exception('[DELTA_AUTO] loop error: %s',exc)
            await asyncio.sleep(max(15,settings.DELTA_SIGNAL_SCAN_SECONDS))


delta_auto_engine=DeltaAutoSignalEngine()
