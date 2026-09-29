"""Compact Telegram formatter for the first ROBO STAFF Delta strategy.
Presentation only: it does not change signal eligibility, cooldowns or execution.
"""


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
    m=c.market or {}
    direction_icon='🟢' if c.direction=='BULLISH' else '🔴'
    action_icon='🟢' if c.action=='OPTION BUY' else '🟠'
    passed=list(snap.get('confirmations_passed') or [])
    tf=snap.get('tf') or {};s1=tf.get('1m') or {};s5=tf.get('5m') or {}

    # Keep the message short like the attached Indian-market alert.
    labels=[]
    for item in passed:
        if item=='RSI zone':
            labels.append(f"RSI {'bullish' if c.direction=='BULLISH' else 'bearish'}")
        elif item=='Williams %R':
            labels.append(f"Williams %R {'bullish' if c.direction=='BULLISH' else 'bearish'}")
        elif item=='5M pivot side':
            labels.append(f"5M Pivot {snap.get('five_zone','')}")
        else:
            labels.append(item)
    labels=labels[:6]
    conf='\n'.join(f'• {x}' for x in labels) if labels else '• Local 1M + 5M confirmation'

    ai=f"AI: {c.ai_status}"
    if c.ai_reason and c.ai_status!='NO-AI':
        ai+=f" — {c.ai_reason}"

    return (
        '🔥 *ROBO STAFF — SCALP SIGNAL*\n\n'
        f'{direction_icon} *{usym}* | {action_icon} *{c.action}* | *{c.quality}*\n'
        f'⭐ Score: *{c.score}/100* | {ai}\n'
        f'Contract: `{c.option_symbol}` | Setup: *{c.pattern}*\n\n'
        f'Entry: `{_fmt(c.premium)}`\n'
        f'SL: `{_fmt(c.sl)}`\n'
        f'T1: `{_fmt(c.t1)}` | T2: `{_fmt(c.t2)}`\n'
        f'R:R: `1:{c.rr:.2f}`\n\n'
        'Confirmations:\n'
        f'{conf}\n\n'
        f'1M RSI `{float(s1.get("rsi") or 0):.1f}` | 5M ADX `{float(s5.get("adx") or 0):.1f}` | RVOL `{float(s5.get("rel_volume") or 0):.2f}`\n'
        '📡 *SIGNAL ONLY — NO ORDER EXECUTED*'
    )
