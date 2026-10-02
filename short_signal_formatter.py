"""Compact Telegram formatter for ROBO STAFF V6 HTF TREND RETEST signals."""


def _fmt(v):
    try:
        x = float(v)
        if abs(x) >= 1000:
            return f"{x:,.1f}"
        if abs(x) >= 10:
            return f"{x:.2f}"
        return f"{x:.4g}"
    except Exception:
        return str(v)


def format_short_signal(engine, c):
    usym = {"BTC": "BTCUSD", "ETH": "ETHUSD", "GOLD": "XAUTUSD"}.get(c.underlying, c.underlying)
    snap = engine.last_scan.get(usym, {}) or {}
    tf = snap.get("tf") or {}
    s1 = tf.get("1m") or {}
    s5 = tf.get("5m") or {}
    s15 = tf.get("15m") or {}
    s1h = tf.get("1h") or {}
    m = c.market or {}

    icon = "🟢" if c.direction == "BULLISH" else "🔴"
    passed = snap.get("confirmations_passed") or []
    failed = snap.get("confirmations_failed") or []
    conf = " • ".join(passed[:6]) if passed else "core checks passed"
    context_fail = " • ".join(failed[:3]) if failed else "none"

    ph = "YES" if m.get("premium_history_available") else "NO / live quote fallback"
    pm = m.get("premium_momentum_score")
    pm_text = f"{float(pm):.0f}/100" if pm is not None else "n/a"
    ai = (c.ai_status or "NO-AI").upper()
    reason = (c.ai_reason or "").strip()
    ai_line = ai + (f" — {reason}" if reason else "")

    return (
        "⚡ *ROBO STAFF — V6 HTF TREND RETEST*\n\n"
        f"{icon} *{usym}* | *{c.action}* | *{c.quality}* | Score *{c.score}/100*\n"
        f"Contract `{c.option_symbol}` | Setup *{c.pattern}*\n"
        f"Entry `{_fmt(c.premium)}` | SL `{_fmt(c.sl)}`\n"
        f"T1 `{_fmt(c.t1)}` | T2 `{_fmt(c.t2)}` | T3 `{_fmt(c.t3)}` | T1 RR `1:{c.rr:.2f}`\n\n"
        "*TREND → SETUP → TRIGGER*\n"
        f"1H regime `{s1h.get('trend','MIXED')}` | 15M confirm `{s15.get('trend','MIXED')}`\n"
        f"5M `{s5.get('trend','MIXED')}` | 1M timing `{s1.get('trend','MIXED')}`\n"
        f"ADX5 `{float(s5.get('adx') or 0):.1f}` | RVOL5 `{float(s5.get('rel_volume') or 0):.2f}` | "
        f"RSI1 `{float(s1.get('rsi') or 0):.1f}` | W%R1 `{float(s1.get('williams_r') or 0):.1f}`\n"
        f"Structure `{snap.get('structure') or 'n/a'}` | 5M zone `{snap.get('five_zone') or 'n/a'}`\n"
        f"Core passed: {conf}\n"
        f"Context not passed: {context_fail}\n\n"
        "*OPTION QUALITY*\n"
        f"Spread `{float(m.get('spread_pct') or 0):.2f}%` | Delta `{_fmt(m.get('delta'))}` | "
        f"OI `{_fmt(m.get('oi'))}` | Volume `{_fmt(m.get('volume'))}`\n"
        f"Premium history: *{ph}* | Premium momentum `{pm_text}` | OI flow `{m.get('oi_flow_label') or 'n/a'}`\n\n"
        f"AI: *{ai_line}* (context only; never blocks deterministic signal)\n"
        "📊 Outcome tracking: T1 / SL / STALE / INVALIDATED → Daily & Weekly\n"
        "📡 *SIGNAL ONLY — NO ORDER EXECUTED*"
    )
