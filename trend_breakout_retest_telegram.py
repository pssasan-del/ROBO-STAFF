from types import MethodType
from trend_breakout_retest_stats import tbr_stats


def _pair(p):
    p=p or {}; w=int(p.get('wins',0)); l=int(p.get('losses',0)); n=w+l
    return f"{w}W/{l}L ({round(100*w/n,1) if n else 0.0}%)"


def _report(title,r,engine):
    return f"""{title}
Epoch: `{r.get('epoch')}`
Signals: {r.get('signals',0)} | Resolved: {r.get('resolved',0)}
Net profitable: {r.get('wins',0)} | Net non-profitable: {r.get('losses',0)}
Success rate: *{r.get('success_rate',0)}%*
T1 hit rate: *{r.get('t1_hit_rate',0)}%* | T1 {r.get('t1_hits',0)} | T2 {r.get('t2_hits',0)}
SL exits: {r.get('sl_exits',0)} | Time exits: {r.get('time_exits',0)}
Cancelled setups: {r.get('cancelled',0)} | Expired setups: {r.get('expired',0)}
BTC: {_pair((r.get('assets') or {}).get('BTCUSD'))} | ETH: {_pair((r.get('assets') or {}).get('ETHUSD'))}
LONG: {_pair((r.get('directions') or {}).get('LONG'))} | SHORT: {_pair((r.get('directions') or {}).get('SHORT'))}
Avg net: {r.get('avg_net_r',0):+.2f}R | Realised paper equity: {r.get('realised_equity_pct',0):+.3f}%
Active paper tracks: {len(engine.active)} | Scan errors: {engine.scan_errors}
Mode: *18-candle minimum; more history used when available*"""


def install_tbr_telegram(telegram_bot, engine):
    original=telegram_bot.process_text
    async def process(self,uid,chat,text):
        t=(text or '').lower().strip()
        if t in {'tbr status','trend breakout status','tbr'}:
            lines=['🚀 *TBR V1 STATUS*']
            for sym in ('BTCUSD','ETHUSD'):
                s=engine.last_status.get(sym,{})
                lines.append(f"{sym}: *{s.get('status','NOT SCANNED')}* — {s.get('reason','')}")
            lines.append(f"Active paper tracks: {len(engine.active)} | Last scan: {'yes' if engine.last_scan_at else 'not yet'}")
            lines.append('Signal-only. No automatic order placement.')
            return await self.send(chat,'\n'.join(lines),self.kb())
        if t in {'tbr daily','trend breakout daily'}:
            return await self.send(chat,_report('📊 *TBR V1 DAILY*',tbr_stats.report(1),engine),self.kb())
        if t in {'tbr weekly','trend breakout weekly'}:
            return await self.send(chat,_report('📅 *TBR V1 WEEKLY*',tbr_stats.report(7),engine),self.kb())
        if t in {'tbr latest','trend breakout latest'}:
            s=engine.last_signal
            return await self.send(chat,engine.format_signal(s) if s else 'No TBR V1 valid signal since this engine started.',self.kb())
        return await original(uid,chat,text)
    telegram_bot.process_text=MethodType(process,telegram_bot)
    return telegram_bot
