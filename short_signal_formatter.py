"""Compact Telegram formatter for ROBO STAFF V7.1 SCALP OPPORTUNITY signals."""


def _fmt(v):
    try:
        x=float(v)
        if abs(x)>=1000:return f"{x:,.1f}"
        if abs(x)>=10:return f"{x:.2f}"
        return f"{x:.4g}"
    except Exception:return str(v)


def format_short_signal(engine,c):
    usym={"BTC":"BTCUSD","ETH":"ETHUSD","GOLD":"XAUTUSD"}.get(c.underlying,c.underlying)
    snap=engine.last_scan.get(usym,{}) or {};tf=snap.get("tf") or {}
    s1=tf.get("1m") or {};s5=tf.get("5m") or {};s15=tf.get("15m") or {};s1h=tf.get("1h") or {}
    m=c.market or {};icon="🟢" if c.direction=="BULLISH" else "🔴"
    ratio=m.get("taker_buy_ratio");ratio_text=f"{float(ratio):.3f}" if ratio is not None else "fallback"
    passed=snap.get("confirmations_passed") or [];conf=" • ".join(passed[-8:]) if passed else "core checks passed"
    pm=m.get("premium_momentum_score");pm_text=f"{float(pm):.0f}/100" if pm is not None else "n/a"
    ai=(c.ai_status or "NO-AI").upper();reason=(c.ai_reason or "").strip();ai_line=ai+(f" — {reason}" if reason else "")
    window="LIQUID BOOST" if m.get("v7_liquid_window") else "OFF-WINDOW ALLOWED"
    flow_mode="STRONG-TAPE FALLBACK" if m.get("v7_flow_fallback") else str(m.get("v7_flow_conviction") or "FLOW")
    return (
        "⚡ *ROBO STAFF — V7.1 SCALP OPPORTUNITY*\n\n"
        f"{icon} *{usym}* | *{c.action}* | *{c.quality}* | Score *{c.score}/100*\n"
        f"Contract `{c.option_symbol}` | Setup *{c.pattern}*\n"
        f"Entry `{_fmt(c.premium)}` | SL `{_fmt(c.sl)}`\n"
        f"T1 `{_fmt(c.t1)}` | T2 `{_fmt(c.t2)}` | T3 `{_fmt(c.t3)}` | T1 RR `1:{c.rr:.2f}`\n\n"
        "*SCALP FILTERS*\n"
        f"Session *{window}* | Flow *{flow_mode}* | Taker-buy `{ratio_text}` | Trades `{m.get('taker_trade_samples','n/a')}`\n"
        f"1H `{s1h.get('trend','MIXED')}` | 15M `{s15.get('trend','MIXED')}` | 5M `{s5.get('trend','MIXED')}` | 1M `{s1.get('trend','MIXED')}`\n"
        f"RVOL5 `{float(s5.get('rel_volume') or 0):.2f}` | Setup RSI `{_fmt(m.get('pullback_prev_rsi'))}` | ADX5 `{float(s5.get('adx') or 0):.1f}`\n"
        f"Setup mode `{m.get('v7_setup_mode') or 'n/a'}`\n"
        f"Passed: {conf}\n\n"
        "*OPTION QUALITY*\n"
        f"Spread `{float(m.get('spread_pct') or 0):.2f}%` | Delta `{_fmt(m.get('delta'))}` | OI `{_fmt(m.get('oi'))}` | Volume `{_fmt(m.get('volume'))}`\n"
        f"Premium momentum `{pm_text}` | OI flow `{m.get('oi_flow_label') or 'n/a'}`\n\n"
        f"AI: *{ai_line}* (context only)\n"
        "📊 Tracking separately: *10M DIRECTION* + *OPTION T1/SL*\n"
        "📡 *SIGNAL ONLY — NO ORDER EXECUTED*"
    )
