import asyncio, json, time
from typing import Dict, List
import httpx, websockets
from config import settings, logger

class DeltaMarketService:
    """Delta Exchange India PUBLIC market data only. No API keys and no order methods."""
    def __init__(self):
        self.client=httpx.AsyncClient(timeout=httpx.Timeout(12,connect=8),headers={'Accept':'application/json','User-Agent':'DeltaCryptoAIBot/5.0'})
        self.cache:Dict[str,dict]={}
        self.ws_connected=False
        self.running=True
        self.last_ws_message=0.0
        self.reconnect_count=0

    @staticmethod
    def normalize_symbol(symbol:str)->str:
        s=(symbol or '').upper().replace('/','').replace('-','')
        aliases={'BTC':'BTCUSD','BTCUSDT':'BTCUSD','XBT':'BTCUSD','ETH':'ETHUSD','ETHUSDT':'ETHUSD'}
        return aliases.get(s,s)

    @staticmethod
    def _num(v):
        try:return float(v) if v is not None else None
        except (TypeError,ValueError):return None

    async def get_ticker(self,symbol:str):
        symbol=self.normalize_symbol(symbol)
        cached=self.cache.get(symbol)
        if cached and time.time()-cached.get('_received',0)<12:
            return dict(cached)
        url=f'{settings.DELTA_REST_BASE}/v2/tickers/{symbol}'
        r=await self.client.get(url)
        if r.status_code!=200:
            raise RuntimeError(f'Delta ticker HTTP {r.status_code}: {r.text[:250]}')
        obj=r.json(); row=obj.get('result') if isinstance(obj,dict) else None
        if not isinstance(row,dict): raise RuntimeError('Delta ticker returned no result')
        price=self._num(row.get('close')) or self._num(row.get('mark_price')) or self._num(row.get('spot_price'))
        if price is None: raise RuntimeError('Delta ticker has no usable price')
        out={'symbol':symbol,'price':price,'mark_price':self._num(row.get('mark_price')),'spot_price':self._num(row.get('spot_price')),'volume':self._num(row.get('volume')),'oi':self._num(row.get('oi')),'timestamp':row.get('timestamp'),'source':'Delta Exchange India public ticker REST','_received':time.time()}
        self.cache[symbol]=out
        return dict(out)

    async def get_candles(self,symbol:str,resolution='5m',limit=120):
        symbol=self.normalize_symbol(symbol)
        seconds={'1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'1h':3600,'2h':7200,'4h':14400,'6h':21600,'12h':43200,'1d':86400,'1w':604800}.get(resolution)
        if not seconds: raise ValueError(f'Unsupported timeframe {resolution}')
        end=int(time.time()); start=end-seconds*(max(20,min(int(limit),2000))+5)
        r=await self.client.get(f'{settings.DELTA_REST_BASE}/v2/history/candles',params={'resolution':resolution,'symbol':symbol,'start':start,'end':end})
        if r.status_code!=200:
            raise RuntimeError(f'Delta candles HTTP {r.status_code}: {r.text[:350]}')
        obj=r.json(); rows=obj.get('result') if isinstance(obj,dict) else None
        if not isinstance(rows,list): raise RuntimeError('Delta candles returned no list')
        rows=sorted(rows,key=lambda x:int(x.get('time',0)))
        out=[]
        for x in rows[-limit:]:
            try: out.append({'time':int(x['time']),'open':float(x['open']),'high':float(x['high']),'low':float(x['low']),'close':float(x['close']),'volume':float(x.get('volume') or 0)})
            except (KeyError,TypeError,ValueError): continue
        logger.info('[DELTA_CANDLES] %s %s candles=%s',symbol,resolution,len(out))
        return out

    async def websocket_loop(self):
        while self.running:
            try:
                async with websockets.connect(settings.DELTA_PUBLIC_WS_URL,ping_interval=25,ping_timeout=10,close_timeout=5) as ws:
                    self.ws_connected=True
                    symbols=settings.delta_symbols()
                    await ws.send(json.dumps({'type':'subscribe','payload':{'channels':[{'name':'ticker','symbols':symbols}]}}))
                    logger.info('[DELTA_WS] connected; ticker symbols=%s',','.join(symbols))
                    async for raw in ws:
                        self.last_ws_message=time.time()
                        try:
                            d=json.loads(raw)
                            sy=d.get('symbol') or d.get('sy') or d.get('s')
                            if not sy: continue
                            sy=self.normalize_symbol(str(sy))
                            price=self._num(d.get('close')) or self._num(d.get('c')) or self._num(d.get('price')) or self._num(d.get('mark_price')) or self._num(d.get('spot_price'))
                            if price is None: continue
                            old=self.cache.get(sy,{})
                            self.cache[sy]={**old,'symbol':sy,'price':price,'mark_price':self._num(d.get('mark_price')) or old.get('mark_price'),'spot_price':self._num(d.get('spot_price')) or old.get('spot_price'),'timestamp':d.get('timestamp') or d.get('ts'),'source':'Delta Exchange India public ticker WebSocket','_received':time.time()}
                        except Exception: continue
            except asyncio.CancelledError: raise
            except Exception as exc:
                self.ws_connected=False; self.reconnect_count+=1; logger.warning('[DELTA_WS] reconnect after error: %s',exc); await asyncio.sleep(3)
        self.ws_connected=False

    async def close(self):
        self.running=False
        await self.client.aclose()

delta_market_service=DeltaMarketService()
