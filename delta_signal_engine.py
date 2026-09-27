import asyncio, json, math, time
from dataclasses import dataclass
from typing import Dict, Optional

from config import settings, logger
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from ai_router import ai_router
from performance_store import performance_store
from market_research import research_store
from polish_policy import POLISH_VERSION, evaluate_entry, evaluate_contract
from strategy_engine import ema, rsi, atr, vwap, directional_values, williams_r, fibonacci_pivots


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
    ai_status: str
    reason: str
    setup_id: str
    market: dict
    created: float


class DeltaAutoSignalEngine:
    """Public-data, signal-only engine. No private Delta credentials or order methods."""

    def __init__(self):
        self.running = True
        self.alert_cb = None
        self.last_signal: Optional[Candidate] = None
        self.last_scan_at = 0.0
        self.last_scan: Dict[str, dict] = {}
        self.last_alert: Dict[str, float] = {}
        self.pending: Dict[str, Candidate] = {}
        self.post_sl: Dict[str, dict] = {}
        self.loop_heartbeat = 0.0
        self.ai_last_status = 'NOT CHECKED'
        self.scan_errors = 0

    def set_alert_callback(self, cb):
        self.alert_cb = cb

    async def _alert(self, text):
        if self.alert_cb:
            await self.alert_cb(text)

    @staticmethod
    def _tf_state(rows):
        cl = [x['close'] for x in rows]
        px = cl[-1]
        e5, e9, e20 = ema(cl, 5), ema(cl, 9), ema(cl, 20)
        vw = vwap(rows, 30)
        adx, pdi, mdi = directional_values(rows, 14)
        wr = williams_r(rows, 14)
        rv = rsi(cl, 14)
        a = atr(rows, 14)
        avg = sum(x['volume'] for x in rows[-21:-1]) / max(1, len(rows[-21:-1]))
        rel = (rows[-1]['volume'] / avg) if avg else 0
        if e5 > e9 > e20 and px > vw and pdi >= mdi:
            trend = 'BULLISH'
        elif e5 < e9 < e20 and px < vw and mdi >= pdi:
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
        """Newest EMA5/EMA9 cross in current or previous 3 closed 5m bars."""
        closes = [float(r['close']) for r in rows]
        if len(closes) < 15:
            return {'side': 'NONE', 'bars_ago': None}
        for bars_ago in range(4):
            end = len(closes) - bars_ago
            if end < 10:
                break
            now, prev = closes[:end], closes[:end - 1]
            e5, e9 = ema(now, 5), ema(now, 9)
            p5, p9 = ema(prev, 5), ema(prev, 9)
            if p5 <= p9 and e5 > e9:
                return {'side': 'BULLISH', 'bars_ago': bars_ago}
            if p5 >= p9 and e5 < e9:
                return {'side': 'BEARISH', 'bars_ago': bars_ago}
        return {'side': 'NONE', 'bars_ago': None}

    @staticmethod
    def _pivot_position(price, piv):
        p = float(piv.get('pivot') or 0)
        s1 = float(piv.get('s1') or 0)
        r1 = float(piv.get('r1') or 0)
        if not p:
            return 'UNKNOWN'
        if r1 and price > r1:
            return 'ABOVE_R1'
        if s1 and price < s1:
            return 'BELOW_S1'
        return 'PIVOT_TO_R1' if price >= p else 'S1_TO_PIVOT'

    async def _snapshot(self, symbol):
        lim = settings.DELTA_CANDLE_LIMIT
        tfs = {}
        for tf in ('1m', '5m', '15m', '1h', '1d'):
            rows = await delta_market_service.get_candles(symbol, tf, lim if tf != '1d' else 40)
            if len(rows) < 30:
                raise RuntimeError(f'{symbol} {tf} insufficient candles={len(rows)}')
            tfs[tf] = {'rows': rows, 'state': self._tf_state(rows)}

        daily_piv = fibonacci_pivots(tfs['1d']['rows'][-2])
        five = tfs['5m']['rows']
        five_piv = fibonacci_pivots(five[-2])
        st = self._structure(five)
        s1 = tfs['1m']['state']; s5 = tfs['5m']['state']; s15 = tfs['15m']['state']; s1h = tfs['1h']['state']; sd = tfs['1d']['state']
        bull = sum(x['trend'] == 'BULLISH' for x in (sd, s1h, s15, s5))
        bear = sum(x['trend'] == 'BEARISH' for x in (sd, s1h, s15, s5))
        direction = 'BULLISH' if bull >= 3 else ('BEARISH' if bear >= 3 else 'MIXED')
        trigger = (direction == 'BULLISH' and s1['trend'] == 'BULLISH') or (direction == 'BEARISH' and s1['trend'] == 'BEARISH')
        cross = self._ema_cross_5m(five)
        cross_aligned = cross['side'] == direction and cross['bars_ago'] is not None
        price_ema_aligned = (direction == 'BULLISH' and s5['price'] > s5['ema5'] > s5['ema9']) or (direction == 'BEARISH' and s5['price'] < s5['ema5'] < s5['ema9'])
        chop = s5['adx'] < 16 or (abs(s5['ema5'] - s5['ema20']) / max(s5['price'], 1) < 0.00035 and s5['rel_volume'] < 0.9) or st == 'RANGE'
        over = abs(s5['price'] - s5['vwap']) > max(2.5 * s5['atr'], s5['price'] * .01)

        score = 50
        score += 10 if direction != 'MIXED' else -20
        score += 8 if trigger else -10
        score += 7 if s5['adx'] >= 20 else -5
        score += 6 if s5['rel_volume'] >= 1.0 else -3
        score += 7 if (direction == 'BULLISH' and st == 'HH/HL') or (direction == 'BEARISH' and st == 'LH/LL') else 0
        score += 5 if (direction == 'BULLISH' and s5['price'] >= daily_piv['pivot']) or (direction == 'BEARISH' and s5['price'] <= daily_piv['pivot']) else 0
        score += 5 if cross_aligned else -8
        score += 4 if price_ema_aligned else -6
        if chop: score -= 18
        if over: score -= 12

        last5 = five[-1]
        stamp = str(last5.get('time') or last5.get('timestamp') or last5.get('start') or last5.get('close_time') or len(five))
        setup_id = f'{symbol}:{direction}:{st}:{stamp}'
        return {
            'symbol': symbol, 'direction': direction, 'trigger': trigger,
            'choppy': chop, 'overextended': over, 'score': max(0, min(100, score)),
            'structure': st, 'setup_id': setup_id, 'daily_pivots': daily_piv,
            'five_pivots': five_piv, 'daily_zone': self._pivot_position(s5['price'], daily_piv),
            'five_zone': self._pivot_position(s5['price'], five_piv),
            'ema_cross_5m': cross, 'ema_cross_aligned': cross_aligned,
            'price_ema_aligned': price_ema_aligned,
            'tf': {k: v['state'] for k, v in tfs.items()},
        }

    @staticmethod
    def _underlying(symbol):
        return 'BTC' if symbol == 'BTCUSD' else ('ETH' if symbol == 'ETHUSD' else 'GOLD')

    @staticmethod
    def _quote_quality(x):
        bid, ask = x.get('best_bid'), x.get('best_ask')
        if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
            return None
        mid = (bid + ask) / 2.0
        spread_pct = ((ask - bid) / mid * 100.0) if mid > 0 else 999.0
        liquidity = float(x.get('volume') or 0) + float(x.get('oi') or 0) * 0.05
        return spread_pct, liquidity

    async def _option_candidates(self, symbol, direction):
        und = self._underlying(symbol)
        rows = await (delta_options_service.get_chain('XAUT') if und == 'GOLD' else delta_options_service.get_chain(und))
        parsed = []
        for row in rows:
            snap = delta_options_service._snapshot(row)
            if snap.get('strike') and snap.get('premium') and snap.get('expiry'):
                parsed.append(snap)
        if not parsed and und == 'GOLD':
            rows = await delta_options_service.get_chain('PAXG')
            parsed = [delta_options_service._snapshot(r) for r in rows if delta_options_service._snapshot(r).get('premium')]
        if not parsed:
            return []

        expiry = min(x['expiry'] for x in parsed if x.get('expiry'))
        parsed = [x for x in parsed if x.get('expiry') == expiry]
        spot = next((x.get('spot_price') for x in parsed if x.get('spot_price')), None)
        if not spot:
            return []
        strikes = sorted({x['strike'] for x in parsed})
        atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))

        def pick(side):
            # Choose the best executable contract from the nearest 1-3 OTM strikes,
            # rather than blindly forcing the third OTM strike.
            idxs = []
            for step in (1, 2, 3):
                idx = atm + step if side == 'CE' else atm - step
                if 0 <= idx < len(strikes):
                    idxs.append(idx)
            pool = [x for x in parsed if x.get('side') == side and x.get('strike') in {strikes[i] for i in idxs}]
            ranked = []
            for x in pool:
                q = self._quote_quality(x)
                if q is None:
                    continue
                spread_pct, liquidity = q
                y = dict(x); y['spread_pct'] = spread_pct
                distance = abs(strikes.index(y['strike']) - atm)
                # Lower spread first, then stronger liquidity, then nearer OTM.
                ranked.append((spread_pct, -liquidity, distance, y))
            if not ranked:
                return None
            ranked.sort(key=lambda z: (z[0], z[1], z[2]))
            return ranked[0][3]

        if direction == 'BULLISH':
            return [('OPTION BUY', 'CE', pick('CE')), ('OPTION SELL', 'PE', pick('PE'))]
        if direction == 'BEARISH':
            return [('OPTION BUY', 'PE', pick('PE')), ('OPTION SELL', 'CE', pick('CE'))]
        return []

    async def _ai_review(self, snap, option):
        if not settings.DELTA_AI_CONFIRMATION:
            return 'NO AI CONFIRMATION (disabled)'
        payload = {
            'direction': snap['direction'], 'score': snap['score'], 'structure': snap['structure'],
            'daily_pivots': snap['daily_pivots'], 'five_pivots': snap['five_pivots'],
            'ema_cross_5m': snap.get('ema_cross_5m'), 'daily_zone': snap.get('daily_zone'),
            'five_zone': snap.get('five_zone'), 'timeframes': snap['tf'],
            'option': {k: option.get(k) for k in ('symbol','side','strike','premium','best_bid','best_ask','oi','volume','delta','bid_iv','ask_iv','spread_pct')},
        }
        system = 'Return ONLY compact JSON: {"decision":"CONFIRM|REJECT|WAIT","confidence":0-100,"short_reason":"..."}. You are only a second-opinion reviewer. Never invent data.'
        try:
            raw = await ai_router.answer(json.dumps(payload, separators=(',', ':')), system)
            if raw.startswith('AI response unavailable'):
                return 'NO AI CONFIRMATION (provider unavailable/quota/timeout)'
            raw = raw.strip().removeprefix('```json').removesuffix('```').strip()
            obj = json.loads(raw); d = str(obj.get('decision', '')).upper()
            if d not in {'CONFIRM', 'REJECT', 'WAIT'}:
                raise ValueError('invalid decision')
            return f"{d} ({int(obj.get('confidence') or 0)}%)"
        except Exception as e:
            logger.warning('[DELTA_AI] no confirmation: %s', e)
            return 'NO AI CONFIRMATION (invalid/unavailable)'

    async def analyze_symbol(self, symbol):
        snap = await self._snapshot(symbol)
        self.last_scan[symbol] = snap
        if snap['direction'] == 'MIXED' or not snap['trigger'] or snap['choppy'] or snap['overextended'] or snap['score'] < settings.DELTA_MIN_SCORE:
            return []
        if not snap.get('ema_cross_aligned') or not snap.get('price_ema_aligned'):
            return []

        out = []; underlying = self._underlying(symbol)
        for action, side, opt in await self._option_candidates(symbol, snap['direction']):
            if not opt:
                continue
            allowed, policy_reason = evaluate_entry(underlying, action, snap)
            if not allowed:
                logger.info('[FRESH_V3] %s %s filtered: %s', underlying, action, policy_reason)
                continue

            bid, ask = opt.get('best_bid'), opt.get('best_ask')
            if bid is None or ask is None:
                continue
            # Realistic paper entry: BUY crosses the ask; SELL receives the bid.
            entry = float(ask if action == 'OPTION BUY' else bid)
            tradeable, contract_reason = evaluate_contract(entry, bid=bid, ask=ask)
            if not tradeable:
                logger.info('[FRESH_V3_CONTRACT] %s %s %s filtered: %s', underlying, action, opt.get('symbol'), contract_reason)
                continue
            if (opt.get('volume') or 0) <= 0 and (opt.get('oi') or 0) <= 0:
                continue

            risk = entry * .12
            if action == 'OPTION BUY':
                sl = entry - risk; t1 = entry + risk * settings.RR_T1; t2 = entry + risk * settings.RR_T2; t3 = entry + risk * settings.RR_T3
            else:
                sl = entry + risk; t1 = entry - risk * settings.RR_T1; t2 = entry - risk * settings.RR_T2; t3 = entry - risk * settings.RR_T3
            if min(sl, t1, t2, t3) <= 0:
                continue

            ai = await self._ai_review(snap, opt) if snap['score'] >= settings.DELTA_AI_MIN_SCORE else 'NO AI CONFIRMATION (not required)'
            cross = snap['ema_cross_5m']
            spread_pct = float(opt.get('spread_pct') or 0)
            reason = f"Python valid | {snap['direction']} | {snap['structure']} | EMA5/9 cross {cross['bars_ago']}b | D:{snap['daily_zone']} | 5m:{snap['five_zone']} | ADX {snap['tf']['5m']['adx']:.1f} | RVOL {snap['tf']['5m']['rel_volume']:.2f} | Spread {spread_pct:.1f}% | {POLISH_VERSION}"
            market = {
                'bid': float(bid), 'ask': float(ask), 'mid': float(opt.get('premium') or ((bid + ask) / 2)),
                'spread_pct': spread_pct, 'oi': float(opt.get('oi') or 0), 'volume': float(opt.get('volume') or 0),
                'delta': opt.get('delta'), 'bid_iv': opt.get('bid_iv'), 'ask_iv': opt.get('ask_iv'),
                'mark_price': opt.get('mark_price'), 'last_price': opt.get('last_price'), 'spot_price': opt.get('spot_price'),
                'entry_source': 'ASK' if action == 'OPTION BUY' else 'BID',
            }
            out.append(Candidate(underlying, snap['direction'], action, opt['symbol'], float(opt['strike']), opt['expiry'], entry, sl, t1, t2, t3, settings.RR_T1, int(snap['score']), ai, reason, snap['setup_id'], market, time.time()))
        return out

    def format_signal(self, c):
        q = 'STRONG' if c.score >= settings.DELTA_STRONG_SCORE else 'VALID'
        m = c.market or {}; bid=m.get('bid'); ask=m.get('ask'); spread=m.get('spread_pct')
        quote = f"Bid/Ask: `{bid:.6g}` / `{ask:.6g}` | Spread: `{spread:.2f}%`\n" if isinstance(bid,(int,float)) and isinstance(ask,(int,float)) and isinstance(spread,(int,float)) else ''
        return (f"🔥 *ROBO STAFF — DELTA SIGNAL*\n\n*{c.action}* — `{c.option_symbol}`\nDirection: *{c.direction}* | Quality: *{q}* | Python: `{c.score}/100`\n"
                f"Executable entry ({m.get('entry_source','QUOTE')}): `{c.premium:.6g}`\n{quote}SL: `{c.sl:.6g}`\nT1: `{c.t1:.6g}` | T2: `{c.t2:.6g}` | T3: `{c.t3:.6g}`\nR:R T1: `1:{c.rr:.2f}`\n"
                f"🤖 AI: *{c.ai_status}*\n⚙️ {c.reason}\n\n📡 Signal only — *NO ORDER EXECUTED*")

    @staticmethod
    def _exit_price(c, option_snapshot):
        if not option_snapshot:
            return None
        # Realistic paper exit: close BUY at bid; close SELL at ask.
        value = option_snapshot.get('best_bid') if c.action == 'OPTION BUY' else option_snapshot.get('best_ask')
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _excursion(c, px):
        if not c.premium or px is None:
            return 0.0, 0.0
        if c.action == 'OPTION BUY':
            move = (px - c.premium) / c.premium * 100.0
        else:
            move = (c.premium - px) / c.premium * 100.0
        return max(0.0, move), max(0.0, -move)

    async def _monitor_pending(self):
        for key, c in list(self.pending.items()):
            try:
                und = 'GOLD' if c.underlying == 'GOLD' else c.underlying
                snap = await (delta_options_service.get_gold_strike_snapshot(c.strike, c.expiry) if und == 'GOLD' else delta_options_service.get_strike_snapshot(und, c.strike, c.expiry))
                side = 'ce' if c.option_symbol.startswith('C-') else 'pe'
                o = snap.get(side)
                px = self._exit_price(c, o)
                if px is None:
                    continue
                mfe, mae = self._excursion(c, px)
                research_store.update_excursion(key, mfe, mae)
                success = (px >= c.t1) if c.action == 'OPTION BUY' else (px <= c.t1)
                failed = (px <= c.sl) if c.action == 'OPTION BUY' else (px >= c.sl)
                if success or failed:
                    elapsed = time.time() - c.created
                    performance_store.resolve(c.action, success, c.underlying, c.ai_status, elapsed)
                    research_store.resolve(key, 'T1' if success else 'SL', elapsed, px)
                    self.pending.pop(key, None)
                    if failed:
                        if len(self.post_sl) >= 50:
                            oldest = min(self.post_sl, key=lambda k: self.post_sl[k]['failed_at']); self.post_sl.pop(oldest, None)
                        self.post_sl[key] = {'candidate': c, 'failed_at': time.time(), 't1_seen': False, 't2_seen': False}
                    label = '✅ T1 SUCCESS' if success else '🛑 SL / FAILED'
                    await self._alert(f"{label} — `{c.option_symbol}` | {c.action} | Executable exit `{px:.6g}`")
            except Exception as e:
                logger.debug('[DELTA_MONITOR] %s: %s', key, e)

    async def _monitor_post_sl(self):
        now = time.time()
        for key, item in list(self.post_sl.items()):
            c = item['candidate']
            if now - item['failed_at'] > 7200:
                self.post_sl.pop(key, None); continue
            try:
                und = 'GOLD' if c.underlying == 'GOLD' else c.underlying
                snap = await (delta_options_service.get_gold_strike_snapshot(c.strike, c.expiry) if und == 'GOLD' else delta_options_service.get_strike_snapshot(und, c.strike, c.expiry))
                side = 'ce' if c.option_symbol.startswith('C-') else 'pe'
                px = self._exit_price(c, snap.get(side))
                if px is None:
                    continue
                t1 = (px >= c.t1) if c.action == 'OPTION BUY' else (px <= c.t1)
                t2 = (px >= c.t2) if c.action == 'OPTION BUY' else (px <= c.t2)
                if t1 and not item['t1_seen']:
                    item['t1_seen'] = True; performance_store.mark_sl_recovery('t1'); research_store.mark_recovery(key)
                if t2 and not item['t2_seen']:
                    item['t2_seen'] = True; performance_store.mark_sl_recovery('t2')
                if item['t2_seen']:
                    self.post_sl.pop(key, None)
            except Exception as e:
                logger.debug('[DELTA_POST_SL] %s: %s', key, e)

    async def scan_once(self):
        self.last_scan_at = time.time(); results = {}
        for symbol in settings.delta_symbols():
            try:
                candidates = await self.analyze_symbol(symbol)
                results[symbol] = {'status': 'SIGNAL' if candidates else 'NO_TRADE', 'count': len(candidates)}
                for c in candidates:
                    key = f'{POLISH_VERSION}:{c.underlying}:{c.option_symbol}:{c.action}:{c.direction}:{c.setup_id}'
                    now = time.time()
                    if now - self.last_alert.get(key, 0) < settings.DELTA_SIGNAL_COOLDOWN_MINUTES * 60:
                        continue
                    self.last_alert[key] = now; self.last_signal = c
                    if len(self.pending) >= 50:
                        oldest = min(self.pending, key=lambda k: self.pending[k].created); self.pending.pop(oldest, None)

                    snap = self.last_scan.get({'BTC':'BTCUSD','ETH':'ETHUSD','GOLD':'XAUTUSD'}.get(c.underlying,''), {})
                    tf5 = (snap.get('tf') or {}).get('5m') or {}; tf15=(snap.get('tf') or {}).get('15m') or {}; tf1h=(snap.get('tf') or {}).get('1h') or {}
                    dp = snap.get('daily_pivots') or {}; fp = snap.get('five_pivots') or {}; m=c.market or {}
                    features = {
                        'research_epoch': POLISH_VERSION, 'structure': snap.get('structure'), 'score': snap.get('score'), 'direction': snap.get('direction'),
                        'ema_cross_5m': snap.get('ema_cross_5m'), 'price_ema_aligned': snap.get('price_ema_aligned'),
                        'ema5_5m': tf5.get('ema5'), 'ema9_5m': tf5.get('ema9'), 'ema20_5m': tf5.get('ema20'), 'price_5m': tf5.get('price'),
                        'adx5': tf5.get('adx'), 'plus_di5': tf5.get('plus_di'), 'minus_di5': tf5.get('minus_di'), 'rvol5': tf5.get('rel_volume'),
                        'atr5': tf5.get('atr'), 'rsi5': tf5.get('rsi'), 'wr5': tf5.get('williams_r'), 'trend15': tf15.get('trend'), 'trend1h': tf1h.get('trend'),
                        'daily_pivot': dp.get('pivot'), 'daily_s1': dp.get('s1'), 'daily_r1': dp.get('r1'), 'daily_zone': snap.get('daily_zone'),
                        'five_pivot': fp.get('pivot'), 'five_s1': fp.get('s1'), 'five_r1': fp.get('r1'), 'five_zone': snap.get('five_zone'),
                        'option_bid': m.get('bid'), 'option_ask': m.get('ask'), 'option_mid': m.get('mid'), 'option_spread_pct': m.get('spread_pct'),
                        'option_oi': m.get('oi'), 'option_volume': m.get('volume'), 'option_delta': m.get('delta'), 'option_bid_iv': m.get('bid_iv'), 'option_ask_iv': m.get('ask_iv'),
                        'option_mark': m.get('mark_price'), 'option_last': m.get('last_price'), 'option_spot': m.get('spot_price'), 'entry_source': m.get('entry_source'),
                        'polish_version': POLISH_VERSION,
                    }
                    research_store.add(key, c, features)
                    self.pending[key] = c
                    performance_store.new_signal(c.action, c.ai_status, c.underlying)
                    await self._alert(self.format_signal(c))
            except Exception as e:
                self.scan_errors += 1
                results[symbol] = {'status': 'ERROR', 'error': str(e)[:160]}
                logger.warning('[DELTA_AUTO] %s failed: %s', symbol, e)
        await self._monitor_pending(); await self._monitor_post_sl(); return results

    async def loop(self):
        while True:
            self.loop_heartbeat = time.time()
            try:
                if self.running and settings.DELTA_AUTO_SIGNAL_ENGINE:
                    await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.scan_errors += 1; logger.exception('[DELTA_AUTO] loop error: %s', e)
            await asyncio.sleep(max(15, settings.DELTA_SIGNAL_SCAN_SECONDS))


delta_auto_engine = DeltaAutoSignalEngine()
