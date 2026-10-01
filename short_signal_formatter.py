"""Compact Telegram formatter for ROBO STAFF V4.3 professional scalp signals."""
from performance_store import performance_store


def _fmt(v):
    try:
        x=float(v)
        if abs(x)>=1000:return f'{x:,.1f}'
        if abs(x)>=10:return f'{x:.2f}'
        return f'{x:.4g}'
    except Exception:return str(v)


def _pct(v):
    try:return f'{float(v):+.2f}%'
    except Exception:return 'n/a'


def _score(v):
    try:return f'{float(v):.0f}/100'
    except Exception:return 'n/a'


def _rel_symbol(rel):
    return {'ABOVE':'>','BELOW':'<','AT':'=','NA':'?'}.get(str(rel or '').upper(),'?')


def format_short_signal(engine,c):
    usym={'BTC':'BTCUSD','ETH':'ETHUSD','GOLD':'XAUTUSD'}.get(c.underlying,c.underlying)
    snap=engine.last_scan.get(usym,{}) or {};tf=snap.get('tf') or {};s5=tf.get('5m') or {};s15=tf.get('15m') or {};s1h=tf.get('1h') or {}
    m=c.market or {};matrix=m.get('opportunity_matrix') or {};future=matrix.get('future') or {};obuy=matrix.get('option_buy') or {};osell=matrix.get('option_sell') or {}
    icon='🟢' if c.direction=='BULLISH' else '🔴'
    five=snap.get('five_fib') or {};fr=snap.get('five_fib_relation') or {};daily=snap.get('daily_fib') or {};dr=snap.get('daily_fib_relation') or {}
    candle_side=str(snap.get('candle_vs_ema5') or s5.get('candle_vs_ema5') or 'NA');ema_rel=str(snap.get('ema9_18_relation') or s5.get('ema9_18_relation') or 'FLAT')
    flow=str(m.get('oi_flow_label') or 'OI_HISTORY_UNAVAILABLE')
    sell_state='READY' if osell.get('available') else str(osell.get('reason') or 'NOT READY')
    age=m.get('v43_setup_age_minutes');age_text=f'{float(age):.1f}m' if age is not None else 'n/a'

    # Record economics only after the engine has passed cooldown and formats an
    # actual alert. These are estimates, not realized P&L.
    try:
        performance_store.record_edge_estimate(c.rr,m.get('option_net_rr'),m.get('option_break_even_pct'),m.get('option_gross_to_cost_multiple'))
    except Exception:
        pass

    return (
        '⚡ *ROBO STAFF — V4.3 PROFESSIONAL SCALP*\n'
        'TIMING + PREMIUM/OI + COST-AWARE VEHICLE CHECK\n\n'
        f'{icon} *{usym}* | *{c.action}* | *{c.quality}* | Score *{c.score}/100*\n'
        f'Contract `{c.option_symbol}` | Setup *{c.pattern}*\n'
        f'Entry `{_fmt(c.premium)}` | SL `{_fmt(c.sl)}`\n'
        f'T1 `{_fmt(c.t1)}` | T2 `{_fmt(c.t2)}` | T3 `{_fmt(c.t3)}` | Gross RR `1:{c.rr:.2f}`\n\n'
        '*UNDERLYING 5M*\n'
        f'Px `{_fmt(s5.get("price"))}` {candle_side} EMA5 `{_fmt(s5.get("ema5"))}` | EMA9 `{_fmt(s5.get("ema9"))}` / EMA18 `{_fmt(s5.get("ema18"))}` → *{ema_rel}*\n'
        f'RSI `{float(s5.get("rsi") or 0):.1f}` | W%R `{float(s5.get("williams_r") or 0):.1f}` | ADX `{float(s5.get("adx") or 0):.1f}` | RVOL `{float(s5.get("rel_volume") or 0):.2f}`\n'
        f'5M Fib: P `{_fmt(five.get("p"))}`({_rel_symbol(fr.get("p"))}) | R1 `{_fmt(five.get("r1"))}`({_rel_symbol(fr.get("r1"))}) | S1 `{_fmt(five.get("s1"))}`({_rel_symbol(fr.get("s1"))})\n'
        f'Daily LOOK: P `{_fmt(daily.get("p"))}`({_rel_symbol(dr.get("p"))}) | R1 `{_fmt(daily.get("r1"))}`({_rel_symbol(dr.get("r1"))}) | S1 `{_fmt(daily.get("s1"))}`({_rel_symbol(dr.get("s1"))})\n\n'
        '*MOMENTUM TIMING — 1M*\n'
        f'Retest/Resume ✅ | Timing score `{_score(m.get("v43_1m_score"))}` | Setup age `{age_text}` | Extension `{float(m.get("v43_1m_extension_atr") or 0):.2f} ATR`\n'
        f'Futures Price/OI *{m.get("futures_price_oi_label") or "n/a"}* | OI change `{_pct(m.get("futures_oi_change_pct"))}` | Funding `{_fmt(m.get("funding_current"))}` ({m.get("funding_bias") or "NEUTRAL"})\n\n'
        '*OPTION PREMIUM 5M*\n'
        f'Premium `{_fmt(m.get("premium_close"))}` > EMA5 `{_fmt(m.get("premium_ema5"))}` | EMA9 `{_fmt(m.get("premium_ema9"))}` / EMA18 `{_fmt(m.get("premium_ema18"))}`\n'
        f'RSI `{float(m.get("premium_rsi") or 0):.1f}` | W%R `{float(m.get("premium_williams_r") or 0):.1f}` | Structure `{m.get("premium_structure") or "n/a"}` | Score `{_score(m.get("premium_momentum_score"))}`\n'
        f'IV percentile `{_fmt(m.get("option_iv_percentile"))}` → *{m.get("option_iv_regime") or "UNKNOWN"}* | Premium/OI *{flow}*\n\n'
        '*BROKERAGE / BREAK-EVEN ESTIMATE*\n'
        f'Option BE `{float(m.get("option_break_even_pct") or 0):.2f}%` | Fee/Premium `{float(m.get("option_fee_to_premium_pct") or 0):.2f}%` | Gross/Cost `{float(m.get("option_gross_to_cost_multiple") or 0):.2f}x` | Net RR `{float(m.get("option_net_rr") or 0):.2f}R`\n'
        f'Future BE `{_fmt(m.get("future_break_even_points"))}` pts | Future net RR `{float(m.get("future_net_rr") or 0):.2f}R`\n\n'
        '*SCALP OPPORTUNITY MATRIX — RESEARCH*\n'
        f'OPTION BUY `{_score(obuy.get("score"))}` ✅ `{obuy.get("symbol") or c.option_symbol}`\n'
        f'{future.get("action") or "FUTURE"} `{_score(future.get("score"))}` {"✅" if future.get("ready") else "⏳"} | BE `{_fmt(future.get("break_even_points"))}` pts\n'
        f'OPTION SELL `{_score(osell.get("score"))}` {"✅" if osell.get("available") else "⏳"} `{osell.get("symbol") or "n/a"}` | {sell_state}\n'
        f'Preferred by current score: *{m.get("preferred_vehicle") or "NO TRADE"}*\n\n'
        '*LIQUIDITY*\n'
        f'OI `{_fmt(m.get("oi"))}` | Volume `{_fmt(m.get("volume"))}` | Spread `{float(m.get("spread_pct") or 0):.2f}%` | Delta `{_fmt(m.get("delta"))}`\n'
        f'15M `{s15.get("trend","MIXED")}` | 1H `{s1h.get("trend","MIXED")}`\n'
        '_Costs are estimates and OI/funding are confirmation context, not guarantees._\n'
        '📡 *SIGNAL ONLY — NO ORDER EXECUTED*'
    )
