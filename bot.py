import asyncio
from typing import Any,Dict,Optional
import httpx
from config import settings,logger
from market_agent import market_agent
from mudrex_service import mudrex_service
from signal_engine import engine

BASE='https://api.telegram.org/bot'
class TelegramBot:
    def __init__(self): self.token=settings.TELEGRAM_BOT_TOKEN; self.client=httpx.AsyncClient(timeout=25); self.running=False; self.offset=0
    def auth(self,u): return not settings.allowed_user_ids() or u in settings.allowed_user_ids()
    def kb(self):
        return {'keyboard':[[{'text':'₿ BTC Price'},{'text':'Ξ ETH Price'}],[{'text':'▶ Start Crypto Scanner'},{'text':'⛔ Stop Scanner'}],[{'text':'🔎 Scan Now'},{'text':'📊 Status'}]],'resize_keyboard':True,'is_persistent':True}
    async def send(self,chat,text,kb=None):
        if not self.token:return
        p={'chat_id':chat,'text':text,'parse_mode':'Markdown'}
        if kb:p['reply_markup']=kb
        r=await self.client.post(f'{BASE}{self.token}/sendMessage',json=p)
        if r.status_code!=200:
            p.pop('parse_mode',None); await self.client.post(f'{BASE}{self.token}/sendMessage',json=p)
    async def alert(self,text):
        for u in settings.allowed_user_ids(): await self.send(u,text,self.kb())
    async def process(self,text):
        t=text.lower().strip()
        if t in ['/start','start','help']:
            return ('👋 *Mudrex Crypto AI Bot*\n\nMudrex public read-only data + Gemini. BTC/ETH trial first. Signal-only; no order execution.',self.kb())
        if t in ['₿ btc price','btc price']:
            q=await mudrex_service.latest_price('BTCUSDT'); return (f"₿ BTC/USDT: *{q['price']:,.2f}*\nSource: {q['source']}",self.kb())
        if t in ['ξ eth price','eth price']:
            q=await mudrex_service.latest_price('ETHUSDT'); return (f"Ξ ETH/USDT: *{q['price']:,.2f}*\nSource: {q['source']}",self.kb())
        if t in ['▶ start crypto scanner','start scanner']:
            engine.start(); return ('▶️ Crypto scanner started for '+', '.join(settings.symbols())+'.',self.kb())
        if t in ['⛔ stop scanner','stop scanner','stop']:
            engine.stop(); return ('⛔ Crypto scanner stopped.',self.kb())
        if t in ['🔎 scan now','scan now']:
            res=await engine.scan_once(); lines=['🔎 *SCAN RESULT*']+[f"• {s}: {m.get('status')}" for s,m in res.items()]; return ('\n'.join(lines),self.kb())
        if t in ['📊 status','status']:
            return (f"📊 *STATUS*\nMudrex WS: {'🟢' if mudrex_service.ws_connected else '🟡 REST fallback'}\nScanner: {'🟢 RUNNING' if engine.running else '⚪ STOPPED'}\nSymbols: {', '.join(settings.symbols())}\nAuto-trading: DISABLED",self.kb())
        return (await market_agent.answer(text),self.kb())
    async def handle(self,upd):
        m=upd.get('message') or {}; uid=(m.get('from') or {}).get('id'); chat=(m.get('chat') or {}).get('id'); text=(m.get('text') or '').strip()
        if not uid or not chat or not text:return
        if not self.auth(uid): return await self.send(chat,'⛔ Access denied.')
        logger.info('[TELEGRAM] User %s sent: %s',uid,text)
        try:
            msg,kb=await asyncio.wait_for(self.process(text),28)
        except Exception as e:
            logger.exception('[TELEGRAM] request failed: %s',e); msg,kb='⚠️ Request failed safely. Please try again.',self.kb()
        await self.send(chat,msg,kb)
    async def poll(self):
        if not self.token: logger.error('[TELEGRAM] token missing'); return
        self.running=True; logger.info('[TELEGRAM] Connected & polling for updates...')
        while self.running:
            try:
                r=await self.client.get(f'{BASE}{self.token}/getUpdates',params={'offset':self.offset,'timeout':25,'allowed_updates':'["message"]'},timeout=30)
                if r.status_code==409: logger.warning('[TELEGRAM] 409 polling conflict; retrying'); await asyncio.sleep(3); continue
                obj=r.json()
                for u in obj.get('result',[]):
                    self.offset=max(self.offset,int(u['update_id'])+1); asyncio.create_task(self.handle(u))
            except asyncio.CancelledError: raise
            except Exception as e: logger.warning('[TELEGRAM] poll error: %s',e); await asyncio.sleep(2)
telegram_bot=TelegramBot()
