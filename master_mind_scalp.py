"""MASTER MIND BTC + XAUT (Gold) scalp engine — NIFTY-style confirmation edition.

Completely separate from the first ROBO STAFF strategy, cooldowns and research.
The same Master Mind confirmation model now scans both BTCUSD and XAUTUSD:
- 15m higher-timeframe price action
- 15m EMA 9/21 confirmation
- 5m EMA 9/21
- 1m EMA 9/21
- Williams %R direction
- Daily CPR position
- Daily Fibonacci S1/R1 position

Each symbol has its own independent Master Mind cooldown so BTC never blocks Gold
and Gold never blocks BTC. Public Delta data only. SIGNAL ONLY: no order
placement/modification/cancel logic.
"""
from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone

from config import logger, settings
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from strategy_engine import ema, fibonacci_pivots

MASTER_MIND_VERSION = "MASTER_MIND_BTC_XAUT_MTF_NIFTY_V4_2026-09-29"
MASTER_MIND_SYMBOLS = ("BTCUSD", "XAUTUSD")
MASTER_MIND_COOLDOWN_SECONDS = 10 * 60


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _ts(v):
    x = _f(v)
    return x / 1000.0 if x > 100_000_000_000 else x


def _closed(rows, seconds):
    out = list(rows or [])
    now = time.time()
    while out:
        t = _ts(out[-1].get('time'))
        if t <= 0 or t + seconds <= now - 2:
            break
        out.pop()
    return out


def _ema(values, period):
    return float(ema([float(x) for x in values], period))


def _williams(rows, period=14):
    if len(rows) < period:
        return -50.0
    block = rows[-period:]
    hh = max(_f(x.get('high')) for x in block)
    ll = min(_f(x.get('low')) for x in block)
    close = _f(block[-1].get('close'))
    rng = hh - ll
    if rng <= 0:
        return -50.0
    return -100.0 * (hh - close) / rng


def _atr(rows, period=14):
    if len(rows) < 2:
        return 0.0
    vals = []
    start = max(1, len(rows) - period)
    for i in range(start, len(rows)):
        h = _f(rows[i].get('high'))
        l = _f(rows[i].get('low'))
        cprev = _f(rows[i - 1].get('close'))
        vals.append(max(h - l, abs(h - cprev), abs(l - cprev)))
    return sum(vals) / len(vals) if vals else 0.0


def _pivot_map(p):
    return {
        'P': _f(p.get('pivot')),
        'R1': _f(p.get('fib_r1') or p.get('r1')),
        'R2': _f(p.get('fib_r2') or p.get('r2')),
        'R3': _f(p.get('fib_r3') or p.get('r3')),
        'S1': _f(p.get('fib_s1') or p.get('s1')),
        'S2': _f(p.get('fib_s2') or p.get('s2')),
        'S3': _f(p.get('fib_s3') or p.get('s3')),
    }


def _cpr(day):
    h, l, c = (_f(day.get(k)) for k in ('high', 'low', 'close'))
    p = (h + l + c) / 3.0
    bc = (h + l) / 2.0
    tc = 2 * p - bc
    return {'P': p, 'BC': min(bc, tc), 'TC': max(bc, tc)}


def _fmt(v):
    return f"{v:,.1f}" if abs(v) >= 1000 else f"{v:.4f}"


def _price_action_15m(rows, direction):
    if len(rows) < 8:
        return False
    prev = rows[-7:-4]
    recent = rows[-4:-1]
    close = _f(rows[-1].get('close'))
    if not prev or not recent:
        return False
    ph = max(_f(x.get('high')) for x in prev)
    pl = min(_f(x.get('low')) for x in prev)
    rh = max(_f(x.get('high')) for x in recent)
    rl = min(_f(x.get('low')) for x in recent)
    if direction == 'BULLISH':
        return (rh > ph or rl > pl) and close >= _f(rows[-2].get('close'))
    return (rh < ph or rl < pl) and close <= _f(rows[-2].get('close'))


def _wick(row, bullish):
    o, h, l, c = (_f(row.get(k)) for k in ('open', 'high', 'low', 'close'))
    body = max(abs(c - o), max(c, 1.0) * 0.0001)
    lower = min(o, c) - l
    upper = h - max(o, c)
    if bullish:
        return lower >= body and c >= o
    return upper >= body and c <= o


def _display_symbol(symbol):
    return 'XAUTUSD (GOLD)' if symbol == 'XAUTUSD' else symbol


def _option_underlying(symbol):
    return 'XAUT' if symbol == 'XAUTUSD' else 'BTC'


class MasterMindScalpEngine:
    def __init__(self):
        self.running = True
        self.alert_cb = None
        self.last_alert_at = {s: 0.0 for s in MASTER_MIND_SYMBOLS}
        self.last_alert_key = {s: '' for s in MASTER_MIND_SYMBOLS}
        self.last_scan_at = 0.0
        self.last_status = 'INIT'
        self.last_reason = ''
        self.last_status_by_symbol = {s: 'INIT' for s in MASTER_MIND_SYMBOLS}
        self.last_reason_by_symbol = {s: '' for s in MASTER_MIND_SYMBOLS}

    def set_alert_callback(self, cb):
        self.alert_cb = cb

    async def _alert(self, text):
        if self.alert_cb:
            await self.alert_cb(text)

    async def _chain(self, symbol):
        underlying = _option_underlying(symbol)
        rows = await delta_options_service.get_chain(underlying)
        if not rows and symbol == 'XAUTUSD':
            rows = await delta_options_service.get_chain('PAXG')
        return rows

    async def _best_strike(self, symbol, direction, spot, pivots):
        """Return an OTM selling strike plus compact option-quality metadata."""
        try:
            rows = await self._chain(symbol)
            parsed = [delta_options_service._snapshot(r) for r in rows]
            parsed = [x for x in parsed if x.get('strike') and x.get('expiry')]
            if not parsed:
                return 'N/A', 'N/A', 0.0, 0

            expiries = sorted({str(x['expiry']) for x in parsed})
            today = datetime.now(timezone.utc).date()
            expiry = next((e for e in expiries if datetime.fromisoformat(e).date() >= today), expiries[0])
            pool = [x for x in parsed if str(x.get('expiry')) == expiry]
            side = 'PE' if direction == 'BULLISH' else 'CE'
            side_pool = [x for x in pool if str(x.get('side') or '').upper() == side]
            strikes = sorted({float(x['strike']) for x in side_pool})
            if not strikes:
                return 'N/A', expiry, 0.0, 0

            if direction == 'BULLISH':
                anchor = max([v for n, v in pivots.items() if n in {'P', 'S1', 'S2'} and 0 < v < spot] or [spot * 0.995])
                eligible = [s for s in strikes if s <= anchor and s < spot]
                strike = max(eligible) if eligible else min(strikes, key=lambda s: abs(s - spot))
            else:
                anchor = min([v for n, v in pivots.items() if n in {'P', 'R1', 'R2'} and v > spot] or [spot * 1.005])
                eligible = [s for s in strikes if s >= anchor and s > spot]
                strike = min(eligible) if eligible else min(strikes, key=lambda s: abs(s - spot))

            chosen = min(side_pool, key=lambda x: abs(float(x.get('strike') or 0) - strike))
            oi = _f(chosen.get('oi'))
            bid = _f(chosen.get('best_bid'))
            ask = _f(chosen.get('best_ask'))
            mid = (bid + ask) / 2 if bid > 0 and ask >= bid else 0
            spread_pct = (ask - bid) / mid * 100 if mid > 0 else 99

            def liq_metric(x):
                return _f(x.get('volume')) + 0.05 * _f(x.get('oi'))

            maxliq = max([liq_metric(x) for x in side_pool] or [1.0])
            rel = min(100.0, 100.0 * liq_metric(chosen) / max(maxliq, 1e-9))
            spread_score = max(0.0, 100.0 - spread_pct * 12.0)
            liquidity = int(round(max(0.0, min(100.0, 0.55 * rel + 0.45 * spread_score))))
            return f"{side[0]}-{int(strike)}", expiry, oi, liquidity
        except Exception as exc:
            logger.debug('[MASTER_MIND] %s strike lookup failed: %s', symbol, exc)
            return 'N/A', 'N/A', 0.0, 0

    async def evaluate(self, symbol):
        r1 = _closed(await delta_market_service.get_candles(symbol, '1m', 120), 60)
        r5 = _closed(await delta_market_service.get_candles(symbol, '5m', 180), 300)
        r15 = _closed(await delta_market_service.get_candles(symbol, '15m', 120), 900)
        days = _closed(await delta_market_service.get_candles(symbol, '1d', 42), 86400)
        if len(r1) < 30 or len(r5) < 40 or len(r15) < 30 or len(days) < 2:
            return None, 'insufficient completed candles'

        c1 = [_f(x.get('close')) for x in r1]
        c5 = [_f(x.get('close')) for x in r5]
        c15 = [_f(x.get('close')) for x in r15]
        close = c5[-1]
        cur5 = r5[-1]
        e1_9, e1_21 = _ema(c1, 9), _ema(c1, 21)
        e5_9, e5_21 = _ema(c5, 9), _ema(c5, 21)
        e15_9, e15_21 = _ema(c15, 9), _ema(c15, 21)
        wr5 = _williams(r5, 14)
        piv = _pivot_map(fibonacci_pivots(days[-1]))
        cpr = _cpr(days[-1])
        atr5 = max(_atr(r5, 14), close * 0.0005)

        bull_checks = [
            ('15M higher-timeframe price action', _price_action_15m(r15, 'BULLISH')),
            ('15M EMA 9/21 bullish confirmation', e15_9 > e15_21),
            ('5M EMA 9/21 bullish', e5_9 > e5_21),
            ('1M EMA 9/21 bullish', e1_9 > e1_21),
            ('Williams %R bullish', wr5 > -50),
            ('Above daily CPR', close > cpr['TC']),
            ('Above daily Fib R1', piv['R1'] > 0 and close > piv['R1']),
        ]
        bear_checks = [
            ('15M higher-timeframe price action', _price_action_15m(r15, 'BEARISH')),
            ('15M EMA 9/21 bearish confirmation', e15_9 < e15_21),
            ('5M EMA 9/21 bearish', e5_9 < e5_21),
            ('1M EMA 9/21 bearish', e1_9 < e1_21),
            ('Williams %R bearish', wr5 < -50),
            ('Below daily CPR', close < cpr['BC']),
            ('Below daily Fib S1', piv['S1'] > 0 and close < piv['S1']),
        ]
        bull_n = sum(ok for _, ok in bull_checks)
        bear_n = sum(ok for _, ok in bear_checks)
        bull_core = e5_9 > e5_21 and e1_9 > e1_21
        bear_core = e5_9 < e5_21 and e1_9 < e1_21

        if bull_core and bull_n >= 5 and bull_n > bear_n:
            direction = 'BULLISH'
            checks = bull_checks
        elif bear_core and bear_n >= 5 and bear_n > bull_n:
            direction = 'BEARISH'
            checks = bear_checks
        else:
            return None, f'WAIT_CONFIRMATIONS bull={bull_n}/7 bear={bear_n}/7'

        recent = r5[-5:-1]
        prior_hi = max(_f(x.get('high')) for x in recent)
        prior_lo = min(_f(x.get('low')) for x in recent)
        _, h, l = (_f(cur5.get(k)) for k in ('open', 'high', 'low'))

        if direction == 'BULLISH':
            if close > prior_hi:
                setup = 'BREAKOUT SCALP'
            elif l <= max(e5_9, e5_21) * 1.0015 and close > e5_9 and _wick(cur5, True):
                setup = 'PULLBACK SCALP'
            else:
                setup = 'TREND SCALP'
            base = min(min(_f(x.get('low')) for x in recent), e5_21)
            risk = max(close - (base - 0.15 * atr5), 0.45 * atr5)
            sl = close - risk
            t1 = close + risk
            t2 = close + 1.85 * risk
            action = 'FUTURE LONG + SELL OTM PUT'
            side = 'BUY'
        else:
            if close < prior_lo:
                setup = 'BREAKDOWN SCALP'
            elif h >= min(e5_9, e5_21) * 0.9985 and close < e5_9 and _wick(cur5, False):
                setup = 'PULLBACK SCALP'
            else:
                setup = 'TREND SCALP'
            base = max(max(_f(x.get('high')) for x in recent), e5_21)
            risk = max((base + 0.15 * atr5) - close, 0.45 * atr5)
            sl = close + risk
            t1 = close - risk
            t2 = close - 1.85 * risk
            action = 'FUTURE SHORT + SELL OTM CALL'
            side = 'SELL'

        confirmations = [label for label, ok in checks if ok]
        n = len(confirmations)
        score = min(95, 55 + n * 5)
        strength = 'STRONG' if n >= 6 else 'VALID'
        strike, expiry, oi, liq = await self._best_strike(symbol, direction, close, piv)
        alert = (
            '🔴🚨 MASTER MIND SIGNAL ALERT 🚨🔴\n\n'
            f'📊 {_display_symbol(symbol)}\n'
            f'🎯 {side} | {strength}\n'
            f'⭐ Score: {score}/100\n'
            f'Setup: {setup}\n'
            f'Action: {action}\n\n'
            f'Entry: {_fmt(close)}\n'
            f'SL: {_fmt(sl)}\n'
            f'T1: {_fmt(t1)}\n'
            f'T2: {_fmt(t2)}\n'
            f'Option: {strike} | Exp: {expiry}\n'
            f'OI: {oi:.0f}\n'
            f'Option liquidity: {liq}/100\n\n'
            'Confirmations:\n' + '\n'.join(f'• {x}' for x in confirmations) + '\n\n'
            f'W%R: {wr5:.1f} | CPR: {_fmt(cpr["BC"])}-{_fmt(cpr["TC"])}\n'
            '⚠️ SIGNAL ONLY — NO ORDER EXECUTED'
        )
        key = f'{symbol}:{direction}:{setup}:{cur5.get("time")}:{strike}'
        return {
            'symbol': symbol,
            'key': key,
            'alert': alert,
            'setup': setup,
            'direction': direction,
            'action': action,
        }, 'SIGNAL'

    async def _scan_symbol(self, symbol):
        signal, status = await self.evaluate(symbol)
        self.last_status_by_symbol[symbol] = status
        if not signal:
            self.last_reason_by_symbol[symbol] = status
            return {'status': status}

        now = time.time()
        if signal['key'] == self.last_alert_key.get(symbol, ''):
            return {'status': 'DUPLICATE_CANDLE'}
        if now - self.last_alert_at.get(symbol, 0.0) < MASTER_MIND_COOLDOWN_SECONDS:
            return {'status': 'MASTER_MIND_COOLDOWN'}

        self.last_alert_key[symbol] = signal['key']
        self.last_alert_at[symbol] = now
        self.last_reason_by_symbol[symbol] = signal['setup']
        await self._alert(signal['alert'])
        logger.info('[MASTER_MIND] %s %s %s %s', symbol, signal['setup'], signal['direction'], signal['action'])
        return {'status': 'SIGNAL', 'setup': signal['setup'], 'direction': signal['direction']}

    async def scan_once(self):
        self.last_scan_at = time.time()
        results = {}
        for symbol in MASTER_MIND_SYMBOLS:
            try:
                results[symbol] = await self._scan_symbol(symbol)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                msg = f'ERROR {str(exc)[:140]}'
                self.last_status_by_symbol[symbol] = msg
                self.last_reason_by_symbol[symbol] = msg
                results[symbol] = {'status': msg}
                logger.warning('[MASTER_MIND] %s scan failed safely: %s', symbol, exc)

        self.last_status = ' | '.join(f'{s}:{results[s].get("status")}' for s in MASTER_MIND_SYMBOLS)
        self.last_reason = ' | '.join(f'{s}:{self.last_reason_by_symbol.get(s, "")}' for s in MASTER_MIND_SYMBOLS)
        return results

    async def loop(self):
        while True:
            try:
                if self.running:
                    await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_status = 'ERROR'
                self.last_reason = str(exc)[:160]
                logger.warning('[MASTER_MIND] loop failed safely: %s', exc)
            await asyncio.sleep(max(30, settings.DELTA_SIGNAL_SCAN_SECONDS))


master_mind_scalp_engine = MasterMindScalpEngine()
