"""Delta public-history service for selected option premium and OI confirmation.

Uses only unauthenticated public endpoints:
- /v2/history/candles?symbol=<OPTION_SYMBOL>
- /v2/history/candles?symbol=MARK:<OPTION_SYMBOL> as a sparse-trade fallback
- /v2/history/candles?symbol=OI:<OPTION_SYMBOL>

No account data and no order methods are present.
"""
from __future__ import annotations

import asyncio
import time

import httpx

from config import logger, settings
from option_premium_analysis import analyze_oi_rows, analyze_premium_rows, classify_premium_oi


class OptionPremiumHistoryService:
    def __init__(self):
        self.client=httpx.AsyncClient(
            timeout=httpx.Timeout(12.0,connect=8.0),
            headers={'Accept':'application/json','User-Agent':'DeltaCryptoAIBot/9.0'},
        )
        self.cache={}
        self.cache_seconds=60.0

    @staticmethod
    def _closed_rows(rows, seconds=300):
        now=time.time();out=list(rows or [])
        while out:
            try: ts=float(out[-1].get('time') or 0)
            except (TypeError,ValueError): ts=0.0
            if ts<=0 or ts+seconds<=now-2:
                break
            out.pop()
        return out

    async def get_history(self, symbol, resolution='5m', limit=90):
        seconds={'1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'1h':3600}.get(resolution)
        if not seconds:
            raise ValueError(f'Unsupported option history timeframe {resolution}')
        end=int(time.time());start=end-seconds*(max(30,min(int(limit),500))+8)
        params={'resolution':resolution,'symbol':str(symbol),'start':start,'end':end}
        try:
            r=await self.client.get(f'{settings.DELTA_REST_BASE}/v2/history/candles',params=params)
        except Exception as exc:
            logger.warning('[OPTION_HISTORY] %s connection failed: %s',symbol,exc)
            return []
        if r.status_code!=200:
            logger.warning('[OPTION_HISTORY] %s HTTP %s: %s',symbol,r.status_code,r.text[:240])
            return []
        try: obj=r.json()
        except Exception:
            return []
        rows=obj.get('result') if isinstance(obj,dict) else None
        if not isinstance(rows,list):
            return []
        out=[]
        for x in sorted(rows,key=lambda z:int(z.get('time') or 0))[-limit:]:
            try:
                out.append({
                    'time':int(x['time']),'open':float(x['open']),'high':float(x['high']),
                    'low':float(x['low']),'close':float(x['close']),'volume':float(x.get('volume') or 0),
                })
            except (KeyError,TypeError,ValueError):
                continue
        return self._closed_rows(out,seconds)

    async def analyze(self, option_symbol):
        key=str(option_symbol or '').upper().strip()
        if not key:
            return {'premium':{'sufficient':False,'gate_pass':False,'reason':'missing option symbol'},'oi':{'sufficient':False},'source':'NONE'}
        cached=self.cache.get(key)
        if cached and time.time()-cached['at']<self.cache_seconds:
            return dict(cached['data'])

        traded_task=asyncio.create_task(self.get_history(key,'5m',90))
        oi_task=asyncio.create_task(self.get_history(f'OI:{key}','5m',90))
        traded,oi_rows=await asyncio.gather(traded_task,oi_task)

        source='TRADED'
        premium_rows=traded
        if len(premium_rows)<24:
            mark_rows=await self.get_history(f'MARK:{key}','5m',90)
            if len(mark_rows)>len(premium_rows):
                premium_rows=mark_rows;source='MARK'

        premium=analyze_premium_rows(premium_rows)
        oi=analyze_oi_rows(oi_rows)
        flow=classify_premium_oi(premium.get('change_3bar_pct'),oi.get('change_pct'))
        data={'premium':premium,'oi':oi,'oi_flow':flow,'source':source,'option_symbol':key}
        self.cache[key]={'at':time.time(),'data':data}
        logger.info('[OPTION_HISTORY] %s source=%s premium_rows=%s gate=%s score=%.1f oi_rows=%s flow=%s',
                    key,source,premium.get('rows'),premium.get('gate_pass'),float(premium.get('momentum_score') or 0),
                    oi.get('rows'),flow.get('label'))
        return dict(data)

    async def close(self):
        await self.client.aclose()


option_premium_history_service=OptionPremiumHistoryService()
