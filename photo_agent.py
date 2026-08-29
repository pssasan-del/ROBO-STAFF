import json, re
from ai_router import ai_router
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from config import logger

VISION_SYSTEM='''You inspect trading screenshots sent to a personal crypto assistant. Return STRICT JSON only, no markdown.
Classify image_type as one of: strategy, option_chain, position, chart, pnl_order, other.
Extract only clearly visible facts. Never guess hidden values.
Schema: {"image_type":"...","question":"","symbol":"BTCUSD|ETHUSD|XAUTUSD|UNKNOWN","underlying":"BTC|ETH|XAUT|PAXG|GOLD|UNKNOWN","strike":null,"option_side":"CE|PE|UNKNOWN","expiry":null,"visible":{},"strategy_text":"","confidence":0.0}
For strategy screenshots, put a concise faithful transcription of the visible rules in strategy_text.
For position screenshots, visible may contain side, entry, ltp, qty, pnl, leverage, liquidation, stop_loss, target when actually visible.
For option_chain screenshots, visible may contain strikes/premiums/OI/IV when actually visible.
For charts, visible may contain timeframe, indicators, support/resistance/trend only when visibly inferable.
Use UNKNOWN/null when uncertain.'''

def _json(raw):
    raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw.strip(),flags=re.I|re.S);a=raw.find('{');b=raw.rfind('}')
    if a<0 or b<a:raise ValueError('vision returned no JSON')
    return json.loads(raw[a:b+1])

def _norm_symbol(v):
    s=str(v or '').upper().replace('/','').replace('-','')
    if s in {'BTC','BTCUSDT'}:return 'BTCUSD'
    if s in {'ETH','ETHUSDT'}:return 'ETHUSD'
    if s in {'GOLD','XAU','XAUT','XAUTUSDT'}:return 'XAUTUSD'
    return s if s in {'BTCUSD','ETHUSD','XAUTUSD'} else None

class PhotoAgent:
    async def inspect(self,data:bytes,mime:str,caption=''):
        raw=await ai_router.inspect_image(data,mime,'Caption/question from user: '+(caption or '(none)')+'\nClassify and extract visible trading facts.',VISION_SYSTEM)
        d=_json(raw);d['image_type']=str(d.get('image_type') or 'other').lower();d['symbol']=_norm_symbol(d.get('symbol'))
        if d.get('underlying') not in {'BTC','ETH','XAUT','PAXG','GOLD'}:
            d['underlying']='BTC' if d['symbol']=='BTCUSD' else ('ETH' if d['symbol']=='ETHUSD' else ('GOLD' if d['symbol']=='XAUTUSD' else None))
        try:d['strike']=float(d['strike']) if d.get('strike') is not None else None
        except:d['strike']=None
        logger.info('[PHOTO] type=%s symbol=%s strike=%s confidence=%s',d['image_type'],d.get('symbol'),d.get('strike'),d.get('confidence'))
        return d

    async def answer(self,data:bytes,mime:str,caption=''):
        d=await self.inspect(data,mime,caption)
        if d['image_type']=='strategy':return {'kind':'strategy','inspection':d}
        live='No Delta enrichment available.'
        sym=d.get('symbol')
        try:
            if d['image_type']=='option_chain' and d.get('underlying') and d.get('strike'):
                snap=(await delta_options_service.get_gold_strike_snapshot(d['strike'],d.get('expiry'))) if d['underlying'] in {'GOLD','XAUT','PAXG'} else (await delta_options_service.get_strike_snapshot(d['underlying'],d['strike'],d.get('expiry')));live='DELTA LIVE OPTIONS: '+repr(snap)
            elif sym:
                q=await delta_market_service.get_ticker(sym);live='DELTA LIVE TICKER: '+repr(q)
                vis=d.get('visible') if isinstance(d.get('visible'),dict) else {}
                if d['image_type']=='position' and vis.get('entry') is not None and vis.get('stop_loss') is not None and str(vis.get('side') or '').upper() in {'LONG','SHORT'}:
                    try:
                        from strategy_engine import risk_reward_targets
                        live+='; RR TARGETS: '+repr(risk_reward_targets(float(vis['entry']),float(vis['stop_loss']),str(vis['side']).upper()))
                    except Exception: pass
                if d['image_type']=='chart':
                    rows=await delta_market_service.get_candles(sym,'5m',80);live+=f'; DELTA 5m candles last={rows[-5:] if rows else []}'
        except Exception as e:
            live='Delta enrichment unavailable: '+str(e)
        system=('You are STAFF BOT, a respectful personal crypto screenshot assistant. Reply in the user caption language/style. '
                'Explain what is visibly present in the screenshot and compare with supplied Delta live data when available. '
                'Screenshot values may be stale: never call them live. Never invent missing entry, quantity, P&L, strike, expiry, price, Greeks or indicators. '
                'For positions/charts you may give a concise Hold/Wait/Reduce/Exit-consider analysis only when the visible facts plus live data support it; state invalidation/risk rather than promising profit. '
                'The bot never places orders. If essential information is unreadable, say exactly what is missing.')
        prompt=f'USER CAPTION: {caption or "Analyse this screenshot"}\n\nVISION EXTRACTION: {d}\n\n{live}\n\nGive a concise useful answer.'
        ans=await ai_router.answer(prompt,system)
        return {'kind':'analysis','inspection':d,'answer':ans}
photo_agent=PhotoAgent()
