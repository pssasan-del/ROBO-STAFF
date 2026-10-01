"""ACTIVE FLOW indicator overlay requested for ROBO STAFF.

Adds the following to the existing V4.1 signal engine without touching MASTER MIND:
- 5-minute closed candle vs EMA5
- 5-minute EMA9 / EMA18 alignment and recent cross
- 5-minute Fibonacci Pivot P / R1 / S1 position
- 5-minute RSI and Williams %R confirmation
- Daily Fibonacci P / R1 / S1 as DISPLAY-ONLY context

The entry remains signal-only. The existing 1.85R target overlay is unchanged.
"""
from __future__ import annotations

from types import MethodType

import delta_signal_engine as signal_module
from config import logger
from polish_policy import evaluate_entry as base_evaluate_entry
from strategy_engine import ema


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _side_of(value, level, eps=1e-12):
    value = _f(value)
    level = _f(level)
    if not level:
        return 'NA'
    if value > level + eps:
        return 'ABOVE'
    if value < level - eps:
        return 'BELOW'
    return 'AT'


def _cross_9_18(rows, lookback=3):
    closes = [float(r['close']) for r in rows]
    if len(closes) < 22:
        return {'side': 'NONE', 'bars_ago': None}
    for bars_ago in range(max(1, int(lookback))):
        end = len(closes) - bars_ago
        if end < 20:
            break
        now = closes[:end]
        prev = closes[:end - 1]
        e9, e18 = ema(now, 9), ema(now, 18)
        p9, p18 = ema(prev, 9), ema(prev, 18)
        if p9 <= p18 and e9 > e18:
            return {'side': 'BULLISH', 'bars_ago': bars_ago}
        if p9 >= p18 and e9 < e18:
            return {'side': 'BEARISH', 'bars_ago': bars_ago}
    return {'side': 'NONE', 'bars_ago': None}


def install_active_flow_indicator_overlay(engine):
    original_tf_state = engine._tf_state
    original_cross_5_9 = engine._ema_cross_5m
    original_snapshot = engine._snapshot

    def _tf_state_with_ema18(self, rows):
        state = dict(original_tf_state(rows))
        closes = [float(x['close']) for x in rows]
        e18 = ema(closes, 18)
        state['ema18'] = e18
        px = _f(state.get('price'))
        e5 = _f(state.get('ema5'))
        e9 = _f(state.get('ema9'))
        state['candle_vs_ema5'] = 'ABOVE' if px > e5 else ('BELOW' if px < e5 else 'AT')
        state['ema9_18_relation'] = 'BULLISH' if e9 > e18 else ('BEARISH' if e9 < e18 else 'FLAT')
        return state

    def _cross_with_9_18(self, rows):
        old = dict(original_cross_5_9(rows) or {})
        cross = _cross_9_18(rows, 3)
        old['ema9_18_side'] = cross['side']
        old['ema9_18_bars_ago'] = cross['bars_ago']
        return old

    async def _snapshot_with_requested_indicators(self, symbol):
        snap = await original_snapshot(symbol)
        tf = snap.get('tf') or {}
        s5 = tf.get('5m') or {}
        price = _f(s5.get('price'))

        cross = snap.get('ema_cross_5m') or {}
        snap['candle_vs_ema5'] = s5.get('candle_vs_ema5', 'NA')
        snap['ema9_18_relation'] = s5.get('ema9_18_relation', 'FLAT')
        snap['ema9_18_cross'] = {
            'side': cross.get('ema9_18_side', 'NONE'),
            'bars_ago': cross.get('ema9_18_bars_ago'),
        }

        five = self._pivot_levels(snap.get('five_pivots') or {})
        daily = self._pivot_levels(snap.get('daily_pivots') or {})
        snap['five_fib'] = {'p': five['pivot'], 'r1': five['r1'], 's1': five['s1']}
        snap['daily_fib'] = {'p': daily['pivot'], 'r1': daily['r1'], 's1': daily['s1']}
        snap['five_fib_relation'] = {
            'p': _side_of(price, five['pivot']),
            'r1': _side_of(price, five['r1']),
            's1': _side_of(price, five['s1']),
        }
        snap['daily_fib_relation'] = {
            'p': _side_of(price, daily['pivot']),
            'r1': _side_of(price, daily['r1']),
            's1': _side_of(price, daily['s1']),
        }
        snap['daily_fib_context_only'] = True
        return snap

    def _enhanced_evaluate_entry(underlying, action, snap):
        ok, reason = base_evaluate_entry(underlying, action, snap)
        if not ok:
            return ok, reason

        direction = str(snap.get('direction') or '').upper()
        tf = snap.get('tf') or {}
        s5 = tf.get('5m') or {}
        candle_side = str(snap.get('candle_vs_ema5') or s5.get('candle_vs_ema5') or 'NA')
        ema_relation = str(snap.get('ema9_18_relation') or s5.get('ema9_18_relation') or 'FLAT')

        candle_ok = (direction == 'BULLISH' and candle_side == 'ABOVE') or (direction == 'BEARISH' and candle_side == 'BELOW')
        ema_ok = ema_relation == direction

        passed = list(snap.get('confirmations_passed') or [])
        failed = list(snap.get('confirmations_failed') or [])

        def mark(label, yes):
            if label in passed:
                passed.remove(label)
            if label in failed:
                failed.remove(label)
            (passed if yes else failed).append(label)

        mark('5M candle vs EMA5', candle_ok)
        mark('5M EMA9/18 alignment', ema_ok)

        cross = snap.get('ema9_18_cross') or {}
        cross_ok = cross.get('side') == direction and cross.get('bars_ago') is not None and int(cross.get('bars_ago')) <= 2
        mark('5M EMA9/18 recent cross', cross_ok)

        rsi5 = _f(s5.get('rsi'), 50.0)
        wr5 = _f(s5.get('williams_r'), -50.0)
        rsi_ok = rsi5 >= 50.0 if direction == 'BULLISH' else rsi5 <= 50.0
        wr_ok = wr5 >= -50.0 if direction == 'BULLISH' else wr5 <= -50.0
        mark('5M RSI supports', rsi_ok)
        mark('5M Williams %R supports', wr_ok)

        fib_rel = snap.get('five_fib_relation') or {}
        pivot_ok = fib_rel.get('p') in ({'ABOVE', 'AT'} if direction == 'BULLISH' else {'BELOW', 'AT'})
        mark('5M Fib Pivot bias', pivot_ok)

        snap['confirmations_passed'] = passed
        snap['confirmations_failed'] = failed
        snap['requested_indicator_overlay'] = True

        # The two requested moving-average checks are the directional gate.
        # RSI/W%R and 5M Fib P/R1/S1 remain confirmations/context so signal
        # frequency is not starved. Daily Fib is display-only by design.
        if not candle_ok:
            return False, f'EMA5 reject: 5M candle is {candle_side}, direction={direction}'
        if not ema_ok:
            return False, f'EMA9/18 reject: relation={ema_relation}, direction={direction}'
        return True, f'{reason} + EMA5/EMA9-18/FIB CHECK'

    engine._tf_state = MethodType(_tf_state_with_ema18, engine)
    engine._ema_cross_5m = MethodType(_cross_with_9_18, engine)
    engine._snapshot = MethodType(_snapshot_with_requested_indicators, engine)

    # delta_signal_engine imported evaluate_entry directly from polish_policy,
    # so replace that module-level reference for this runtime only.
    signal_module.evaluate_entry = _enhanced_evaluate_entry
    engine.requested_indicator_overlay_installed = True
    logger.info('[ACTIVE_INDICATORS] 5M candle/EMA5 + EMA9/18 cross/alignment + RSI/W%%R + Fib P/R1/S1 enabled; daily Fib context only')
    return engine
