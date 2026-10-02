"""Compact Telegram formatter for ROBO STAFF V5 CLEAN CONFLUENCE signals."""


def _fmt(v):
    try:
        x=float(v)
        if abs(x)>=1000:return f'{x:,.1f}'
        if abs(x)>=10:return f'{x:.2f}'
        return f'{x:.4g}'
    except Exception:return str(v)


def format_short_signal(engine,c):
    usym={'BTC':'BTCUSD','ETH':'ETHUSD','GOLD':'XAUTUSD'}.get(c.underlying,c.underlying)
    snap=engine.last_scan.get(usym,{}) or {}
    tf=snap.get('tf') or {}
    s1=tf.get('1m') or {};s5=tf.get('5m') or {};s15=tf.get('15m') or {};s1h=tf.get('1h') or {}
    m=c.market or {}
    icon='🟢' if c.direction=='BULLISH' else '🔴'
    passed=snap.get('confirmations_passed') or []
    conf=' • '.join(passed[:6]) if passed else 'core confluence passed'
    ph='YES' if m.get('premium_history_available') else 'NO / fallback to live quote quality'
    pm=m.get('premium_momentum_score')
    pm_text=f'{float(pm):.0f}/100' if pm is not None else 'n/a'
    oi_flow=m.get('oi_flow_label') or 'n/a'
    ai=(c.ai_status or 'NO-AI').upper()
    reason=(c.ai_reason or '').strip()
    ai_line=f'{ai}' + (f' — {reason}' if reason else '')

    return (
        '⚡ *ROBO STAFF — V5 CLEAN CONFLUENCE*\n\n'
        f'{icon} *{usym}* | *{c.action}* | *{c.quality}* | Score *{c.score}/100*\n'
        f'Contract `{c.option_symbol}` | Setup *{c.pattern}*\n'
        f'Entry `{_fmt(c.premium)}` | SL `{_fmt(c.sl)}`\n'
        f'T1 `{_fmt(c.t1)}` | T2 `{_fmt(c.t2)}` | T3 `{_fmt(c.t3)}` | RR `1:{c.rr:.2f}`\n\n'
        '*CORE CHECKS*\n'
        f'1M: `{s1.get("trend","MIXED")}` | 5M: `{s5.get("trend","MIXED")}` | 15M: `{s15.get("trend","MIXED")}` | 1H: `{s1h.get("trend","MIXED")}`\n'
        f'ADX `{float(s5.get("adx") or 0):.1f}` | RVOL `{float(s5.get("rel_volume") or 0):.2f}` | RSI1M `{float(s1.get("rsi") or 0):.1f}` | W%R1M `{float(s1.get("williams_r") or 0):.1f}`\n'
        f'Structure `{snap.get("structure") or "n/a"}` | 5M zone `{snap.get("five_zone") or "n/a"}`\n'
        f'Passed: {conf}\n\n'
        '*OPTION QUALITY*\n'
        f'Spread `{float(m.get("spread_pct") or 0):.2f}%` | Delta `{_fmt(m.get("delta"))}` | OI `{_fmt(m.get("oi"))}` | Volume `{_fmt(m.get("volume"))}`\n'
        f'Premium history: *{ph}* | Premium momentum `{pm_text}` | OI flow `{oi_flow}`\n\n'
        f'AI: *{ai_line}* (non-blocking context)\n'
        '📡 *SIGNAL ONLY — NO ORDER EXECUTED*'
    )
