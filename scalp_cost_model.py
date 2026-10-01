"""Cost-aware signal economics for ROBO STAFF V4.3.

Research/signal helper only. It never submits orders. Defaults mirror Delta
India's published retail fee page as of 2026-10-01, but every rate is
configurable because promotions/tier pricing can change.
"""
from __future__ import annotations

import os


def _env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


GST_RATE = _env('DELTA_GST_RATE', 0.18)
FUTURES_MAKER_RATE = _env('DELTA_FUTURES_MAKER_RATE', 0.0002)
FUTURES_TAKER_RATE = _env('DELTA_FUTURES_TAKER_RATE', 0.0005)
OPTIONS_RATE = _env('DELTA_OPTIONS_RATE', 0.0001)
OPTION_FEE_CAP_PREMIUM = _env('DELTA_OPTION_FEE_CAP_PREMIUM', 0.035)
ESTIMATED_SLIPPAGE_BPS = _env('DELTA_ESTIMATED_SLIPPAGE_BPS', 1.5)
MIN_GROSS_TO_COST_MULTIPLE = _env('DELTA_MIN_GROSS_TO_COST_MULTIPLE', 3.0)


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def futures_round_trip_cost_points(entry_price: float, *, entry_taker=True, exit_taker=True,
                                   slippage_bps: float | None = None) -> dict:
    """Estimated per-unit round-trip cost in underlying price points."""
    px = max(_f(entry_price), 0.0)
    er = FUTURES_TAKER_RATE if entry_taker else FUTURES_MAKER_RATE
    xr = FUTURES_TAKER_RATE if exit_taker else FUTURES_MAKER_RATE
    fees = px * (er + xr) * (1.0 + GST_RATE)
    slip = px * ((ESTIMATED_SLIPPAGE_BPS if slippage_bps is None else _f(slippage_bps)) / 10000.0)
    total = fees + slip
    return {
        'fee_points': fees,
        'slippage_points': slip,
        'total_cost_points': total,
        'break_even_points': total,
        'break_even_pct': (total / px * 100.0) if px else 0.0,
        'entry_rate': er,
        'exit_rate': xr,
        'gst_rate': GST_RATE,
    }


def option_round_trip_cost(premium: float, spot: float, spread_abs: float = 0.0,
                           *, slippage_pct: float = 0.20) -> dict:
    """Conservative option round-trip cost per one underlying unit.

    Delta option fees are notional based. Spot is used as notional per one
    underlying unit, the published premium cap is applied per side, GST is
    added, then the observed spread and a small premium slippage allowance.
    """
    p = max(_f(premium), 0.0)
    s = max(_f(spot), 0.0)
    spread = max(_f(spread_abs), 0.0)
    if p <= 0:
        return {
            'total_cost': 0.0, 'break_even_pct': 999.0, 'fee_total': 0.0,
            'spread_cost': spread, 'slippage_cost': 0.0, 'fee_to_premium_pct': 0.0,
        }
    raw_side = s * OPTIONS_RATE
    capped_side = min(raw_side, p * OPTION_FEE_CAP_PREMIUM)
    fee_total = 2.0 * capped_side * (1.0 + GST_RATE)
    slip = p * max(0.0, _f(slippage_pct)) / 100.0
    total = fee_total + spread + slip
    return {
        'fee_total': fee_total,
        'spread_cost': spread,
        'slippage_cost': slip,
        'total_cost': total,
        'break_even_pct': total / p * 100.0,
        'fee_to_premium_pct': fee_total / p * 100.0,
        'options_rate': OPTIONS_RATE,
        'premium_cap': OPTION_FEE_CAP_PREMIUM,
        'gst_rate': GST_RATE,
    }


def edge_after_cost(*, gross_profit: float, risk: float, total_cost: float) -> dict:
    gross = max(_f(gross_profit), 0.0)
    r = max(_f(risk), 1e-12)
    c = max(_f(total_cost), 0.0)
    net = gross - c
    multiple = (gross / c) if c > 0 else 99.0
    net_rr = net / (r + c) if (r + c) > 0 else 0.0
    return {
        'gross_profit': gross,
        'estimated_cost': c,
        'net_profit_at_target': net,
        'gross_to_cost_multiple': multiple,
        'net_rr': net_rr,
        'cost_gate_pass': bool(net > 0 and multiple >= MIN_GROSS_TO_COST_MULTIPLE),
        'min_gross_to_cost_multiple': MIN_GROSS_TO_COST_MULTIPLE,
    }
