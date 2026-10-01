"""Compact Telegram formatter for ROBO STAFF V4.2 premium/OI confirmed signals."""


def _fmt(v):
    try:
        x=float(v)
        if abs(x)>=1000:return f'{x:,.1f}'
        if abs(x)>=10:return f'{x:.2f}'
        return f'{x:.4g}'
    except Exception:
        return str(v)


def _pct(v):
    try:return f'{float(v):+.2f}%'
    except Exception:return 'n/a'


def _rel_symbol(rel):
    return {'ABOVE':'>','BELOW':'<','AT':'=','NA':'?'}.get(str(rel or '').upper(),'?')


def format_short_signal(engine, c):
    usym={'BTC':'BTCUSD','ETH':'ETHUSD','GOLD':'XAUTUSD'}.get(c.underlying,c.underlying)
    snap=engine.last_scan.get(usym,{}) or {}
    tf=snap.get('tf') or {};s1=tf.get('1m') or {};s5=tf.get('5m') or {};s15=tf.get('15m') or {};s1h=tf.get('1h') or {}
    m=c.market or {}
    direction_icon='🟢' if c.direction=='BULLISH' else '🔴'
    passed=list(snap.get('confirmations_passed') or [])

    labels=[]
    for item in passed:
        if item=='RSI supports': labels.append(f"1M RSI {'bullish' if c.direction=='BULLISH' else 'bearish'}")
        elif item=='Williams %R supports': labels.append(f"1M Williams %R {'bullish' if c.direction=='BULLISH' else 'bearish'}")
        elif item=='5M pivot side': labels.append(f"5M Pivot {snap.get('five_zone','')}")
        else: labels.append(item)
    labels=labels[:8]
    conf='\n'.join(f'• {x}' for x in labels)

    ai=f"AI {c.ai_status}"
    if c.ai_reason and c.ai_status!='NO-AI': ai+=f" — {c.ai_reason}"

    candle_side=str(snap.get('candle_vs_ema5') or s5.get('candle_vs_ema5') or 'NA')
    ema_rel=str(snap.get('ema9_18_relation') or s5.get('ema9_18_relation') or 'FLAT')
    cross=snap.get('ema9_18_cross') or {}
    cross_side=str(cross.get('side') or 'NONE');cross_bars=cross.get('bars_ago')
    cross_text=(f'{cross_side} {cross_bars} bar ago' if cross_side!='NONE' and cross_bars is not None else 'NO RECENT CROSS')

    five=snap.get('five_fib') or {};fr=snap.get('five_fib_relation') or {}
    daily=snap.get('daily_fib') or {};dr=snap.get('daily_fib_relation') or {}
    px=_fmt(s5.get('price'))

    p_cross=str(m.get('premium_cross_side') or 'NONE');p_cross_bars=m.get('premium_cross_bars_ago')
    p_cross_text=(f'{p_cross} {p_cross_bars} bar ago' if p_cross!='NONE' and p_cross_bars is not None else 'NO RECENT CROSS')
    p_relation='BULLISH' if float(m.get('premium_ema9') or 0)>float(m.get('premium_ema18') or 0) else 'BEARISH/FLAT'
    flow=str(m.get('oi_flow_label') or 'OI_HISTORY_UNAVAILABLE')

    return (
        '⚡ *ROBO STAFF — V4.2 ACTIVE FLOW*\n'
        'UNDERLYING + OPTION PREMIUM + OI CONFIRMATION\n\n'
        f'{direction_icon} *{usym}* | *{c.action}* | *{c.quality}*\n'
        f'⭐ Score: *{c.score}/100* | {ai}\n'
        f'Contract: `{c.option_symbol}`\n'
        f'Setup: *{c.pattern}*\n\n'
        f'Entry: `{_fmt(c.premium)}`\n'
        f'SL: `{_fmt(c.sl)}`\n'
        f'T1: `{_fmt(c.t1)}` | T2: `{_fmt(c.t2)}` | T3: `{_fmt(c.t3)}`\n'
        f'R:R T1: `1:{c.rr:.2f}`\n\n'
        '*UNDERLYING 5M*\n'
        f'Candle `{px}` is *{candle_side} EMA5* `{_fmt(s5.get("ema5"))}`\n'
        f'EMA9 `{_fmt(s5.get("ema9"))}` | EMA18 `{_fmt(s5.get("ema18"))}` → *{ema_rel}*\n'
        f'EMA9/18 Cross: *{cross_text}*\n'
        f'RSI `{float(s5.get("rsi") or 0):.1f}` | Williams %R `{float(s5.get("williams_r") or 0):.1f}`\n\n'
        '*5M FIB PIVOT*\n'
        f'P `{_fmt(five.get("p"))}` (Px {_rel_symbol(fr.get("p"))} P) | '
        f'R1 `{_fmt(five.get("r1"))}` (Px {_rel_symbol(fr.get("r1"))} R1) | '
        f'S1 `{_fmt(five.get("s1"))}` (Px {_rel_symbol(fr.get("s1"))} S1)\n'
        f'Daily LOOK ONLY: P `{_fmt(daily.get("p"))}` ({_rel_symbol(dr.get("p"))}) | '
        f'R1 `{_fmt(daily.get("r1"))}` ({_rel_symbol(dr.get("r1"))}) | '
        f'S1 `{_fmt(daily.get("s1"))}` ({_rel_symbol(dr.get("s1"))})\n\n'
        '*OPTION PREMIUM 5M*\n'
        f'Source `{m.get("premium_source") or "n/a"}` | Close `{_fmt(m.get("premium_close"))}` > EMA5 `{_fmt(m.get("premium_ema5"))}` ✅\n'
        f'EMA9 `{_fmt(m.get("premium_ema9"))}` | EMA18 `{_fmt(m.get("premium_ema18"))}` → *{p_relation}*\n'
        f'EMA9/18 Cross: *{p_cross_text}* | Structure `{m.get("premium_structure") or "n/a"}`\n'
        f'RSI `{float(m.get("premium_rsi") or 0):.1f}` | Williams %R `{float(m.get("premium_williams_r") or 0):.1f}`\n'
        f'Extension `{float(m.get("premium_extension_atr") or 0):.2f} ATR` | Premium score `{float(m.get("premium_momentum_score") or 0):.0f}/100`\n\n'
        '*OI / LIQUIDITY*\n'
        f'OI `{_fmt(m.get("oi"))}` | OI 3-bar change `{_pct(m.get("oi_history_change_pct"))}` | *{flow}*\n'
        f'Nearby CE OI `{_fmt(m.get("oi_cluster_ce"))}` | PE OI `{_fmt(m.get("oi_cluster_pe"))}`\n'
        f'Selected OI share `{float(m.get("oi_cluster_selected_share_pct") or 0):.1f}%` | '
        f'Volume `{_fmt(m.get("volume"))}` | Spread `{float(m.get("spread_pct") or 0):.2f}%` | Delta `{_fmt(m.get("delta"))}`\n'
        '_OI interpretation is a heuristic confirmation, not a standalone direction rule._\n\n'
        'Confirmations:\n'
        f'{conf}\n\n'
        f'15M `{s15.get("trend","MIXED")}` | 1H `{s1h.get("trend","MIXED")}`\n'
        f'5M ADX `{float(s5.get("adx") or 0):.1f}` | RVOL `{float(s5.get("rel_volume") or 0):.2f}`\n'
        f'Risk `{float(snap.get("underlying_risk_atr") or 0):.2f} ATR`\n'
        '📡 *SIGNAL ONLY — NO ORDER EXECUTED*'
    )
