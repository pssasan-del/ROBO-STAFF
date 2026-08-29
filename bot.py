import asyncio, json, math
import httpx
from config import settings,logger
from market_agent import market_agent
from delta_market_service import delta_market_service
from strategy_store import strategy_store
from strategy_engine import engine
from strategy_parser import parse_strategy_text,parse_strategy_file,format_preview
from photo_agent import photo_agent

BASE='https://api.telegram.org/bot'

class TelegramBot:
    def __init__(self):
        self.token=settings.TELEGRAM_BOT_TOKEN; self.client=httpx.AsyncClient(timeout=30); self.running=False; self.offset=0
        self.pending={}  # uid -> {'mode':'create|edit','sid':optional,'parsed':optional,'source':str}
    def auth(self,u):return not settings.allowed_user_ids() or u in settings.allowed_user_ids()
    def kb(self):
        return {'keyboard':[[{'text':'₿ BTC Price'},{'text':'Ξ ETH Price'}],[{'text':'🧾 BTC Options'},{'text':'🧾 ETH Options'}],[{'text':'➕ Create Strategy'},{'text':'💾 Saved Strategies'}],[{'text':'🔎 Scan Active Now'},{'text':'📊 Status'}],[{'text':'⛔ Stop All Strategies'}]],'resize_keyboard':True,'is_persistent':True}
    @staticmethod
    def inline(rows):return {'inline_keyboard':rows}
    async def _post(self,method,payload):
        r=await self.client.post(f'{BASE}{self.token}/{method}',json=payload)
        if r.status_code!=200:logger.warning('[TELEGRAM] %s HTTP %s %s',method,r.status_code,r.text[:300])
        return r
    async def send(self,chat,text,kb=None):
        if not self.token:return
        p={'chat_id':chat,'text':text,'parse_mode':'Markdown'}
        if kb:p['reply_markup']=kb
        r=await self._post('sendMessage',p)
        if r.status_code!=200:
            p.pop('parse_mode',None);await self._post('sendMessage',p)
    async def answer_callback(self,cqid,text=''):
        if cqid:await self._post('answerCallbackQuery',{'callback_query_id':cqid,'text':text[:180]})
    async def alert(self,owner,text):
        if self.auth(owner):await self.send(owner,text,self.kb())

    async def strategy_page(self,uid,chat,page=0):
        items=strategy_store.list(uid); per=5; pages=max(1,math.ceil(len(items)/per)); page=max(0,min(page,pages-1)); subset=items[page*per:(page+1)*per]
        if not subset:return await self.send(chat,'💾 No saved strategies yet. Tap *➕ Create Strategy* and type or upload your rules.',self.kb())
        lines=[f'💾 *Saved Strategies* — {len(items)}/{settings.MAX_SAVED_STRATEGIES}',f'Page {page+1}/{pages} • Active {strategy_store.active_count(uid)}/{settings.MAX_ACTIVE_STRATEGIES}','']
        buttons=[]
        for r in subset:
            state='🟢' if r['active'] else '⚪';lines.append(f"{state} `#{r['id']}` *{r['name']}* — {r['symbol']} {r['timeframe']}")
            buttons.append([{'text':('⛔ Stop' if r['active'] else '▶ Start')+f' #{r["id"]}','callback_data':f'toggle:{r["id"]}:{page}'},{'text':'✏️ Edit','callback_data':f'edit:{r["id"]}'},{'text':'🗑 Delete','callback_data':f'delask:{r["id"]}:{page}'}])
        nav=[]
        if page>0:nav.append({'text':'⬅ Prev','callback_data':f'page:{page-1}'})
        if page+1<pages:nav.append({'text':'Next ➡','callback_data':f'page:{page+1}'})
        if nav:buttons.append(nav)
        await self.send(chat,'\n'.join(lines),self.inline(buttons))

    async def preview(self,uid,chat,data,source,edit_sid=None):
        self.pending[uid]={'mode':'edit' if edit_sid else 'create','sid':edit_sid,'parsed':data,'source':source}
        label='💾 Save Changes' if edit_sid else '💾 Save Strategy'
        await self.send(chat,format_preview(data),self.inline([[{'text':label,'callback_data':'savepending'},{'text':'❌ Cancel','callback_data':'cancelpending'}]]))

    async def parse_text_strategy(self,uid,chat,text,edit_sid=None):
        await self.send(chat,'🧠 Gemini is converting the strategy into deterministic scan rules...')
        try:data=await parse_strategy_text(text);await self.preview(uid,chat,data,text,edit_sid)
        except Exception as e:logger.warning('[STRATEGY] parse failed: %s',e);await self.send(chat,'⚠️ Strategy parse failed. Please write the rules more clearly, e.g. `BTC 5m: EMA20 > EMA50, RSI14 > 55, close > VWAP`.')

    async def download_telegram_file(self,file_id):
        r=await self.client.get(f'{BASE}{self.token}/getFile',params={'file_id':file_id});obj=r.json();path=(obj.get('result') or {}).get('file_path')
        if not path:raise RuntimeError('Telegram file path unavailable')
        rr=await self.client.get(f'https://api.telegram.org/file/bot{self.token}/{path}',timeout=30);rr.raise_for_status();return rr.content

    async def handle_upload(self,uid,chat,m):
        doc=m.get('document'); photos=m.get('photo') or []; caption=(m.get('caption') or '').strip(); pend=self.pending.get(uid) or {}; edit_sid=pend.get('sid') if pend.get('mode')=='edit_wait' else None
        if doc:
            if int(doc.get('file_size') or 0)>10*1024*1024:return await self.send(chat,'⚠️ Keep files under 10 MB.')
            name=(doc.get('file_name') or '').lower(); mime=doc.get('mime_type') or 'application/octet-stream'
            if not (mime.startswith('text/') or mime in {'application/pdf','application/json'} or name.endswith(('.txt','.md','.json','.pdf'))):return await self.send(chat,'Supported documents: TXT, MD, JSON or PDF. Trading screenshots should be sent as photos.')
            data=await self.download_telegram_file(doc['file_id'])
            await self.send(chat,'🧠 Reading the uploaded strategy document...')
            try:parsed=await parse_strategy_file(data,mime,caption);return await self.preview(uid,chat,parsed,caption or '[uploaded strategy]',edit_sid)
            except Exception as e:logger.warning('[STRATEGY] document parse failed: %s',e);return await self.send(chat,'⚠️ I could not safely extract a supported strategy from that document.')
        if not photos:return
        p=photos[-1];data=await self.download_telegram_file(p['file_id']);mime='image/jpeg'
        # If Create/Edit Strategy is explicitly active, preserve the deterministic strategy workflow.
        if pend.get('mode') in {'create_wait','edit_wait'}:
            await self.send(chat,'🧠 Reading the strategy screenshot and converting it to scan rules...')
            try:parsed=await parse_strategy_file(data,mime,caption);return await self.preview(uid,chat,parsed,caption or '[uploaded strategy]',edit_sid)
            except Exception as e:logger.warning('[STRATEGY] image parse failed: %s',e);return await self.send(chat,'⚠️ I could not safely extract the strategy. Try a clearer screenshot or type the rules.')
        await self.send(chat,'👁️ Analysing screenshot...')
        try:
            result=await photo_agent.answer(data,mime,caption)
            if result['kind']=='strategy':
                text=(result['inspection'].get('strategy_text') or '').strip()
                if not text:return await self.send(chat,'🧠 This looks like a strategy screenshot, but the rules are not clear enough to save. Tap *➕ Create Strategy* and send a clearer image.')
                await self.send(chat,'🧠 Strategy screenshot detected. Building a rule preview — nothing will be saved until you confirm.')
                return await self.parse_text_strategy(uid,chat,text)
            return await self.send(chat,result['answer'],self.kb())
        except Exception as e:
            logger.exception('[PHOTO] analysis failed: %s',e);return await self.send(chat,'⚠️ I could not safely analyse that screenshot. Try a clearer image or add a caption such as `hold cheyyano?`, `option chain analyse`, or `strategy save`.')

    async def handle_callback(self,cq):
        uid=(cq.get('from') or {}).get('id');msg=cq.get('message') or {};chat=(msg.get('chat') or {}).get('id');data=cq.get('data') or '';cqid=cq.get('id')
        if not uid or not chat or not self.auth(uid):return await self.answer_callback(cqid,'Access denied')
        try:
            if data.startswith('page:'):
                await self.answer_callback(cqid);return await self.strategy_page(uid,chat,int(data.split(':')[1]))
            if data.startswith('toggle:'):
                _,sid,p=data.split(':');r=strategy_store.get(uid,int(sid))
                if not r:return await self.answer_callback(cqid,'Strategy not found')
                strategy_store.set_active(uid,int(sid),not bool(r['active']));await self.answer_callback(cqid,'Updated');return await self.strategy_page(uid,chat,int(p))
            if data.startswith('edit:'):
                sid=int(data.split(':')[1]);r=strategy_store.get(uid,sid)
                if not r:return await self.answer_callback(cqid,'Not found')
                self.pending[uid]={'mode':'edit_wait','sid':sid};await self.answer_callback(cqid);return await self.send(chat,f'✏️ Send the *replacement rules* for `#{sid} {r["name"]}` as text, screenshot or PDF. I will preview before saving.')
            if data.startswith('delask:'):
                _,sid,p=data.split(':');await self.answer_callback(cqid);return await self.send(chat,f'⚠️ Delete strategy `#{sid}`?',self.inline([[{'text':'✅ Yes, Delete','callback_data':f'del:{sid}:{p}'},{'text':'❌ Cancel','callback_data':f'page:{p}'}]]))
            if data.startswith('del:'):
                _,sid,p=data.split(':');strategy_store.delete(uid,int(sid));await self.answer_callback(cqid,'Deleted');return await self.strategy_page(uid,chat,int(p))
            if data=='cancelpending':
                self.pending.pop(uid,None);await self.answer_callback(cqid,'Cancelled');return await self.send(chat,'Cancelled.',self.kb())
            if data=='savepending':
                pend=self.pending.get(uid) or {};parsed=pend.get('parsed')
                if not parsed:return await self.answer_callback(cqid,'Nothing to save')
                if pend.get('mode')=='edit':strategy_store.replace(uid,int(pend['sid']),parsed,pend.get('source',''));sid=pend['sid'];txt=f'✅ Strategy #{sid} updated.'
                else:sid=strategy_store.create(uid,parsed,pend.get('source',''));txt=f'✅ Strategy saved as #{sid}. It is OFF by default; start it from Saved Strategies.'
                self.pending.pop(uid,None);await self.answer_callback(cqid,'Saved');await self.send(chat,txt,self.kb());return await self.strategy_page(uid,chat,0)
        except ValueError as e:await self.answer_callback(cqid,str(e));await self.send(chat,f'⚠️ {e}')
        except Exception as e:logger.exception('[TELEGRAM] callback failed: %s',e);await self.answer_callback(cqid,'Failed safely')

    async def process_text(self,uid,chat,text):
        t=text.lower().strip()
        if t in ['/start','start','help']:
            return await self.send(chat,'👋 *Delta Crypto AI Bot V7*\n\nDelta-only public market data + Gemini. BTC/ETH live data, options and custom saved strategy scanning. No order execution.',self.kb())
        if t in ['₿ btc price','btc price']:
            q=await delta_market_service.get_ticker('BTCUSD');return await self.send(chat,f"₿ BTC/USD: *${q['price']:,.2f}*\nSource: Delta public market data",self.kb())
        if t in ['ξ eth price','eth price']:
            q=await delta_market_service.get_ticker('ETHUSD');return await self.send(chat,f"Ξ ETH/USD: *${q['price']:,.2f}*\nSource: Delta public market data",self.kb())
        if t in ['🧾 btc options','btc options']:return await self.send(chat,'Ask like: *BTC 77500 CE and PE rate* — nearest expiry is used if expiry is omitted.',self.kb())
        if t in ['🧾 eth options','eth options']:return await self.send(chat,'Ask like: *ETH 2500 CE and PE rate*.',self.kb())
        if t in ['➕ create strategy','create strategy','new strategy']:
            self.pending[uid]={'mode':'create_wait'};return await self.send(chat,'➕ Send your strategy now as *text, Telegram photo/screenshot, TXT/MD/JSON or PDF*.\n\nExample: `BTC 5m, LONG: EMA20 > EMA50, RSI14 > 55, close > VWAP, volume > 1.5x volume SMA20`\n\nGemini will parse → you check Preview → Save.')
        if t in ['💾 saved strategies','saved strategies','strategies','/strategies']:return await self.strategy_page(uid,chat,0)
        if t in ['⛔ stop all strategies','stop all','stop strategies']:
            for r in strategy_store.list(uid):
                if r['active']:strategy_store.set_active(uid,r['id'],False)
            return await self.send(chat,'⛔ All your strategy scanners stopped.',self.kb())
        if t in ['🔎 scan active now','scan now']:
            res=await engine.scan_once(uid);return await self.send(chat,'🔎 Active scan complete. '+('No active strategies.' if not res else ' | '.join(f"#{k}: {v.get('status')}" for k,v in res.items())),self.kb())
        if t in ['📊 status','status']:
            return await self.send(chat,f"📊 *STATUS*\nDelta REST: 🟢 PUBLIC\nDelta WS: {'🟢' if delta_market_service.ws_connected else '🟡 reconnecting / REST fallback'}\nSaved: {strategy_store.count(uid)}/{settings.MAX_SAVED_STRATEGIES}\nActive: {strategy_store.active_count(uid)}/{settings.MAX_ACTIVE_STRATEGIES}\nGemini: {'🟢' if settings.GEMINI_API_KEY else '🔴'}\nPhoto intelligence: 🟢 strategy / option chain / position / chart\nHeartbeat/reconnect: 🟢\nAuto-trading: DISABLED",self.kb())
        pend=self.pending.get(uid) or {}
        if pend.get('mode') in {'create_wait','edit_wait'}:
            return await self.parse_text_strategy(uid,chat,text,pend.get('sid'))
        if t.startswith('strategy:') or t.startswith('strategy '):return await self.parse_text_strategy(uid,chat,text.split(':',1)[-1] if ':' in text else text)
        return await self.send(chat,await market_agent.answer(text),self.kb())

    async def handle_update(self,upd):
        if upd.get('callback_query'):return await self.handle_callback(upd['callback_query'])
        m=upd.get('message') or {};uid=(m.get('from') or {}).get('id');chat=(m.get('chat') or {}).get('id')
        if not uid or not chat:return
        if not self.auth(uid):return await self.send(chat,'⛔ Access denied.')
        try:
            if m.get('document') or m.get('photo'):return await asyncio.wait_for(self.handle_upload(uid,chat,m),35)
            text=(m.get('text') or '').strip()
            if not text:return
            logger.info('[TELEGRAM] User %s sent: %s',uid,text)
            await asyncio.wait_for(self.process_text(uid,chat,text),30)
        except asyncio.TimeoutError:await self.send(chat,'⚠️ Request timed out safely. Please try again.')
        except Exception as e:logger.exception('[TELEGRAM] request failed: %s',e);await self.send(chat,'⚠️ Request failed safely. Please try again.',self.kb())

    async def poll(self):
        if not self.token:logger.error('[TELEGRAM] token missing');return
        self.running=True;logger.info('[TELEGRAM] Connected & polling for updates...')
        while self.running:
            try:
                r=await self.client.get(f'{BASE}{self.token}/getUpdates',params={'offset':self.offset,'timeout':25,'allowed_updates':'["message","callback_query"]'},timeout=30)
                if r.status_code==409:logger.warning('[TELEGRAM] 409 conflict; retrying');await asyncio.sleep(3);continue
                for u in r.json().get('result',[]):self.offset=max(self.offset,int(u['update_id'])+1);asyncio.create_task(self.handle_update(u))
            except asyncio.CancelledError:raise
            except Exception as e:logger.warning('[TELEGRAM] poll error: %s',e);await asyncio.sleep(2)

telegram_bot=TelegramBot()
