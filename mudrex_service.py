import asyncio, json, time
from typing import Dict, List, Optional
import httpx
from config import settings, logger

class MudrexService:
    """PUBLIC read-only Mudrex market data only. No API secret and no order methods."""
    def __init__(self):
        self.client=httpx.AsyncClient(timeout=12.0, headers={'User-Agent':'MudrexCryptoSignalBot/1.0'})
        self.live: Dict[str,dict]={}
        self.ws_connected=False

    @staticmethod
    def rest_symbol(symbol:str)->str:
        s=symbol.upper().replace('/','')
        if s.endswith('USDT'): return s[:-4]+'/USDT'
        return s

    async def get_klines(self, symbols:List[str], aggregation:str='5m', limit:int=120, end_time:Optional[int]=None)->Dict[str,List[list]]:
        end=int(end_time or time.time())
        seconds={'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400}.get(aggregation,300)
        start=end-(max(2,min(limit,1440))+3)*seconds
        assets=','.join(self.rest_symbol(s) for s in symbols[:25])
        params={'assets':assets,'aggregation':aggregation,'start_time':str(start),'end_time':str(end)}
        url=f'{settings.MUDREX_REST_BASE}/kline'
        logger.info('[MUDREX_REST] kline aggregation=%s assets=%s', aggregation, assets)
        r=await self.client.get(url,params=params)
        r.raise_for_status()
        obj=r.json()
        if not obj.get('success',True): raise RuntimeError(str(obj.get('errors') or 'Mudrex kline error'))
        root=obj.get('data',obj)
        ticks=root.get('asset_ticks',root if isinstance(root,dict) else {})
        out={}
        for key,val in (ticks or {}).items():
            norm=str(key).replace('/','').upper()
            candles=val if isinstance(val,list) else []
            candles=sorted(candles,key=lambda x: int(x[0]))[-limit:]
            out[norm]=candles
        return out

    async def latest_price(self,symbol:str)->dict:
        s=symbol.upper().replace('/','')
        cached=self.live.get(s)
        if cached and time.time()-cached.get('received_at',0)<20:
            return {'symbol':s,'price':cached.get('price'),'source':'Mudrex WebSocket','timestamp':cached.get('timestamp')}
        data=await self.get_klines([s],'1m',3)
        c=(data.get(s) or [])[-1]
        return {'symbol':s,'price':float(c[4]),'source':'Mudrex public 1m kline','timestamp':int(c[0])}

    async def health(self)->bool:
        try:
            x=await self.get_klines(['BTCUSDT'],'1m',2)
            return bool(x.get('BTCUSDT'))
        except Exception as e:
            logger.warning('[MUDREX] health failed: %s',e); return False

    @staticmethod
    def _extract_ticker(msg:dict):
        # Mudrex schemas may wrap stream payloads; parse conservatively.
        candidates=[msg, msg.get('data') if isinstance(msg,dict) else None]
        for d in candidates:
            if not isinstance(d,dict): continue
            sym=d.get('symbol') or d.get('asset') or d.get('s')
            price=d.get('price') or d.get('last_price') or d.get('lastPrice') or d.get('close') or d.get('c')
            if sym and price is not None:
                try: return str(sym).replace('/','').upper(), float(price), d.get('timestamp') or d.get('time') or int(time.time())
                except Exception: pass
        return None

    async def websocket_loop(self):
        import websockets
        while True:
            try:
                async with websockets.connect(settings.MUDREX_WS_URL,ping_interval=20,ping_timeout=20,close_timeout=5) as ws:
                    self.ws_connected=True
                    assets=[s.lower().replace('/','') for s in settings.symbols()]
                    # Current Mudrex public WS envelope: ticker stream + assets array.
                    sub={'method':'SUBSCRIBE','id':1,'params':['ticker@5s'],'assets':assets}
                    await ws.send(json.dumps(sub))
                    logger.info('[MUDREX_WS] connected; subscribed ticker@5s: %s',','.join(assets))
                    async for raw in ws:
                        try:
                            msg=json.loads(raw)
                            tick=self._extract_ticker(msg)
                            if tick:
                                s,p,ts=tick
                                self.live[s]={'price':p,'timestamp':ts,'received_at':time.time()}
                        except Exception: continue
            except asyncio.CancelledError: raise
            except Exception as e:
                self.ws_connected=False
                logger.warning('[MUDREX_WS] disconnected: %s; retrying in 5s',e)
                await asyncio.sleep(5)

mudrex_service=MudrexService()
