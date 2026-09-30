"""Compact Telegram formatter for ROBO STAFF V4.1 active-flow scalp."""


def _fmt(v):
    try:
        x=float(v)
        if abs(x)>=1000:return f'{x:,.1f}'
        if abs(x)>=10:return f'{x:.2f}'
        return f'{x:.4g}'
    except Exception:
        return str(v)


def format_short_signal(engine, c):
    usym={'BTC':'BTCUSD','ETH':'ETHUSD','GOLD':'XAUTUSD'}.get(c.underlying,c.underlying)
    snap=engine.last_scan.get(usym,{}) or {}
    tf=snap.get('tf') or {};s1=tf.get('1m') or {};s5=tf.get('5m') or {};s15=tf.get('15m') or {};s1h=tf.get('1h') or {}
    direction_icon='🟢' if c.direction=='BULLISH' else '🔴'
    passed=list(snap.get('confirmations_passed') or [])

    labels=[]
    for item in passed:
        if item=='RSI supports': labels.append(f"RSI {'bullish' if c.direction=='BULLISH' else 'bearish'}")
        elif item=='Williams %R supports': labels.append(f"Williams %R {'bullish' if c.direction=='BULLISH' else 'bearish'}")
        elif item=='5M pivot side': labels.append(f"5M Pivot {snap.get('five_zone','')}")
        else: labels.append(item)
    labels=labels[:6]
    conf='\n'.join(f'• {x}' for x in labels)

    ai=f"AI {c.ai_status}"
    if c.ai_reason and c.ai_status!='NO-AI': ai+=f" — {c.ai_reason}"

    return (
        '⚡ *ROBO STAFF — ACTIVE FLOW SCALP*\n\n'
        f'{direction_icon} *{usym}* | *{c.action}* | *{c.quality}*\n'
        f'⭐ Score: *{c.score}/100* | {ai}\n'
        f'Contract: `{c.option_symbol}`\n'
        f'Setup: *{c.pattern}*\n\n'
        f'Entry: `{_fmt(c.premium)}`\n'
        f'SL: `{_fmt(c.sl)}`\n'
        f'T1: `{_fmt(c.t1)}` | T2: `{_fmt(c.t2)}` | T3: `{_fmt(c.t3)}`\n'
        f'R:R T1: `1:{c.rr:.2f}`\n\n'
        'Confirmations:\n'
        f'{conf}\n\n'
        f'15M `{s15.get("trend","MIXED")}` | 1H `{s1h.get("trend","MIXED")}`\n'
        f'1M RSI `{float(s1.get("rsi") or 0):.1f}` | 5M ADX `{float(s5.get("adx") or 0):.1f}` | RVOL `{float(s5.get("rel_volume") or 0):.2f}`\n'
        f'Risk `{float(snap.get("underlying_risk_atr") or 0):.2f} ATR`\n'
        '📡 *SIGNAL ONLY — NO ORDER EXECUTED*'
    )
