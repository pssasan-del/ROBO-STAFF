"""Manual live-order ticket builder for ROBO STAFF.

This module prepares a complete human-review ticket only. It never submits,
modifies, cancels or closes an exchange order. The surrounding gate must be ON
before a signal is handed here; restart/deploy defaults that gate to OFF.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

LEVERAGE_MODEL = 84
ALLOCATION_PCT = 0.10


def _num(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


@dataclass
class ManualOrderTicket:
    underlying: str
    action: str
    contract: str
    direction: str
    entry: float
    sl: float
    t1: float
    t2: float
    t3: float
    allocation: float
    allocation_asset: str
    model_buying_power_usd: float
    model_units: int
    setup_id: str


def build_manual_ticket(candidate, *, available_display: float, asset: str, available_usd: float) -> ManualOrderTicket:
    underlying = str(getattr(candidate, 'underlying', '') or '').upper()
    action = str(getattr(candidate, 'action', '') or '').upper()
    contract = str(getattr(candidate, 'option_symbol', '') or '')
    direction = str(getattr(candidate, 'direction', '') or '').upper()
    setup_id = str(getattr(candidate, 'setup_id', '') or '')

    if underlying not in {'BTC', 'ETH', 'GOLD'}:
        raise RuntimeError('unsupported underlying')
    if action not in {'OPTION BUY', 'OPTION SELL'}:
        raise RuntimeError('unsupported action')
    if not contract or not setup_id:
        raise RuntimeError('contract/setup missing')

    entry = _num(getattr(candidate, 'premium', 0))
    sl = _num(getattr(candidate, 'sl', 0))
    t1 = _num(getattr(candidate, 't1', 0))
    t2 = _num(getattr(candidate, 't2', 0))
    t3 = _num(getattr(candidate, 't3', 0))
    if min(entry, sl, t1, t2, t3) <= 0:
        raise RuntimeError('signal Entry/SL/targets incomplete')

    allocation = max(0.0, float(available_display)) * ALLOCATION_PCT
    model_bp = max(0.0, float(available_usd)) * ALLOCATION_PCT * LEVERAGE_MODEL
    model_units = max(1, int(math.floor(model_bp / max(entry, 1e-9))))

    return ManualOrderTicket(
        underlying=underlying,
        action=action,
        contract=contract,
        direction=direction,
        entry=entry,
        sl=sl,
        t1=t1,
        t2=t2,
        t3=t3,
        allocation=allocation,
        allocation_asset=str(asset),
        model_buying_power_usd=model_bp,
        model_units=model_units,
        setup_id=setup_id,
    )


def format_manual_ticket(t: ManualOrderTicket) -> str:
    return (
        '🤖 *AUTO TRADE PREP — READY TICKET*\n'
        f'{t.underlying} • *{t.action}* • `{t.contract}`\n'
        f'Direction: *{t.direction}*\n'
        f'Capital allocation: *{t.allocation:,.2f} {t.allocation_asset}* (10% current available)\n'
        f'84x sizing model buying power ≈ `${t.model_buying_power_usd:,.2f}`\n'
        f'Model units: `{t.model_units}`  *(verify Delta contract multiplier before manual submit)*\n\n'
        f'Entry: `{t.entry:.6g}` | SL: `{t.sl:.6g}`\n'
        f'T1: `{t.t1:.6g}` | T2: `{t.t2:.6g}` | T3: `{t.t3:.6g}`\n'
        'T1 rule: activate trailing; do not blindly use model units as final exchange quantity.\n\n'
        '✅ Review symbol, quantity, leverage/margin, fees, liquidation and SL in Delta, then submit manually.\n'
        '🔒 *NO EXCHANGE ORDER IS SENT BY THIS MODULE*'
    )
