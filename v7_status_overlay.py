"""Telegram Daily/Weekly status formatter for V7 dual outcome tracking."""


def _rate_pair(p):
    w=int((p or {}).get("wins",0)); l=int((p or {}).get("losses",0)); n=w+l
    return f"{w}W/{l}L ({round(100*w/n,1) if n else 0.0}%)"


def install_v7_status_overlay(telegram_bot):
    def _perf_text(title, r):
        def pair(group,name):
            p=r.get(group,{}).get(name,{})
            w=int(p.get("success",0)); l=int(p.get("failed",0)); n=w+l
            return f"{w}W/{l}L ({round(100*w/n,1) if n else 0.0}%)"
        tm=r.get("timing",{})
        d=r.get("direction_10m",{}) or {}
        assets=d.get("assets",{}) or {}
        sides=d.get("sides",{}) or {}
        return f"""{title}
Epoch: `{r.get('epoch','')}`

🎯 *10M DIRECTION STATUS*
Overall: {_rate_pair(d)} | Samples: {d.get('total',0)}
BTC: {_rate_pair(assets.get('BTC',{}))} | ETH: {_rate_pair(assets.get('ETH',{}))}
BULL: {_rate_pair(sides.get('BULLISH',{}))} | BEAR: {_rate_pair(sides.get('BEARISH',{}))}
Avg taker-buy: {d.get('avg_taker_buy_ratio',0)} | Avg RVOL: {d.get('avg_rvol',0)}
Avg signed 10m move: {d.get('avg_move_pct',0):+.4f}%

📊 *OPTION OUTCOME STATUS*
Total: {r['total']} | T1: {r['success']} | Failed/SL: {r['failed']} | Unresolved: {r['unresolved']}
STALE: {r.get('stale',0)} | INVALIDATED: {r.get('invalidated',0)}
Option T1 success: *{r['success_rate']}%*
OPTION BUY: {pair('actions','OPTION BUY')} | OPTION SELL: {pair('actions','OPTION SELL')}
BTC: {pair('assets','BTC')} | ETH: {pair('assets','ETH')} | GOLD: {pair('assets','GOLD')}
SL timing: <5m {tm.get('sl_under_5m',0)} | 5-15m {tm.get('sl_5_15m',0)} | >15m {tm.get('sl_over_15m',0)}
SL → later T1: {r.get('sl_later_t1',0)} | later T2: {r.get('sl_later_t2',0)}"""
    telegram_bot.__class__._perf_text = staticmethod(_perf_text)
    return telegram_bot
