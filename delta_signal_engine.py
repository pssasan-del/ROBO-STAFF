import asyncio, json, math, time
from dataclasses import dataclass, asdict
from typing import Dict, Optional
from config import settings, logger
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from ai_router import ai_router
from performance_store import performance_store
from market_research import research_store
from polish_policy import POLISH_VERSION, evaluate_entry, evaluate_contract
from strategy_engine import ema, rsi, atr, vwap, directional_values, williams_r, fibonacci_pivots

@dataclass
class Candidate:
    underlying:str; direction:str; action:str; option_symbol:str; strike:float; expiry:str
    premium:float; sl:float; t1:float; t2:float; t3:float; rr:float; score:int
    ai_status:str; reason:str; setup_id:str; created:float

class DeltaAutoSignalEngine:
    """Signal-only engine. It has no private Delta credentials and no order methods."""
    def __init__(self):
        self.running=True; self.alert_cb=None; self.last_signal:Optional[Candidate]=None; self.last_scan_at=0.0
        self.last_scan:Dict[str,dict]={};self.last_alert:Dict[str,float]={};self.pending:Dict[str,Candidate]={};self.post_sl:Dict[str,dict]={};self.loop_heartbeat=0.0
        self.ai_last_status='NOT CHECKED';self.scan_errors=0
    def set_alert_callback(self,cb):self.alert_cb=cb
    async def _alert(self,text):
        if self.alert_cb:await self.alert_cb(text)
    @staticmethod
    def _tf_state(rows):
        cl=[x['close'] for x in rows];px=cl[-1];e5,e9,e20=ema(cl,5),ema(cl,9),ema(cl,20);vw=vwap(rows,30);adx,pdi,mdi=directional_values(rows,14);wr=williams_r(rows,14);rv=rsi(cl,14);a=atr(rows,14)
        avg=sum(x['volume'] for x in rows[-21:-1])/max(1,len(rows[-21:-1]));rel=(rows[-1]['volume']/avg) if avg else 0
        if e5>e9>e20 and px>vw and pdi>=mdi:trend='BULLISH'
        elif e5<e9<e20 and px<vw and mdi>=pdi:trend='BEARISH'
        else:trend='MIXED'
        return {'price':px,'ema5':e5,'ema9':e9,'ema20':e20,'vwap':vw,'adx':adx,'plus_di':pdi,'minus_di':mdi,'williams_r':wr,'rsi':rv,'atr':a,'rel_volume':rel,'trend':trend}
    @staticmethod
    def _structure(rows):
        a=rows[-12:-6];b=rows[-6:]
        if not a or not b:return 'UNKNOWN'
        ah,al=max(x['high'] for x in a),min(x['low'] for x in a);bh,bl=max(x['high'] for x in b),min(x['low'] for x in b)
        if bh>ah and bl>al:return 'HH/HL'
        if bh<ah and bl<al:return 'LH/LL'
        return 'RANGE'
    @staticmethod
    def _ema_cross_5m(rows):
        """Find the newest EMA5/EMA9 cross in the current or previous 3 closed 5m bars."""
        closes=[float(r['close']) for r in rows]
        if len(closes)<15:return {'side':'NONE','bars_ago':None}
        for bars_ago in range(0,4):
            end=len(closes)-bars_ago
            if end<10:break
            now=closes[:end];prev=closes[:end-1]
            e5=ema(now,5);e9=ema(now,9);p5=ema(prev,5);p9=ema(prev,9)
            if p5<=p9 and e5>e9:return {'side':'BULLISH','bars_ago':bars_ago}
            if p5>=p9 and e5<e9:return {'side':'BEARISH','bars_ago':bars_ago}
        return {'side':'NONE','bars_ago':None}
    @staticmethod
    def _pivot_position(price,piv):
        p=float(piv.get('pivot') or 0);s1=float(piv.get('s1') or 0);r1=float(piv.get('r1') or 0)
        if not p:return 'UNKNOWN'
        if r1 and price>r1:return 'ABOVE_R1'
        if s1 and price<s1:return 'BELOW_S1'
        if price>=p:return 'PIVOT_TO_R1'
        return 'S1_TO_PIVOT'
    async def _snapshot(self,symbol):
        lim=settings.DELTA_CANDLE_LIMIT;tfs={}
        for tf in ('1m','5m','15m','1h','1d'):
            rows=await delta_market_service.get_candles(symbol,tf,lim if tf!='1d' else 40)
            if len(rows)<30:raise RuntimeError(f'{symbol} {tf} insufficient candles={len(rows)}')
            tfs[tf]={'rows':rows,'state':self._tf_state(rows)}
        day=tfs['1d']['rows'];daily_piv=fibonacci_pivots(day[-2]);five=tfs['5m']['rows'];five_piv=fibonacci_pivots(five[-2])
        st=self._structure(five);s1=tfs['1m']['state'];s5=tfs['5m']['state'];s15=tfs['15m']['state'];s1h=tfs['1h']['state'];sd=tfs['1d']['state']
        bull=sum(x['trend']=='BULLISH' for x in (sd,s1h,s15,s5));bear=sum(x['trend']=='BEARISH' for x in (sd,s1h,s15,s5))
        direction='BULLISH' if bull>=3 else ('BEARISH' if bear>=3 else 'MIXED')
        trigger=(direction=='BULLISH' and s1['trend']=='BULLISH') or (direction=='BEARISH' and s1['trend']=='BEARISH')
        cross=self._ema_cross_5m(five);cross_aligned=cross['side']==direction and cross['bars_ago'] is not None
        price_ema_aligned=(direction=='BULLISH' and s5['price']>s5['ema5']>s5['ema9']) or (direction=='BEARISH' and s5['price']<s5['ema5']<s5['ema9'])
        chop=s5['adx']<16 or (abs(s5['ema5']-s5['ema20'])/max(s5['price'],1)<0.00035 and s5['rel_volume']<0.9) or st=='RANGE'
        over=abs(s5['price']-s5['vwap'])>max(2.5*s5['atr'],s5['price']*.01)
        score=50
        score+=10 if direction!='MIXED' else -20;score+=8 if trigger else -10;score+=7 if s5['adx']>=20 else -5;score+=6 if s5['rel_volume']>=1.0 else -3
        score+=7 if (direction=='BULLISH' and st=='HH/HL') or (direction=='BEARISH' and st=='LH/LL') else 0
        score+=5 if (direction=='BULLISH' and s5['price']>=daily_piv['pivot']) or (direction=='BEARISH' and s5['price']<=daily_piv['pivot']) else 0
        score+=5 if cross_aligned else -8;score+=4 if price_ema_aligned else -6
        if chop:score-=18
        if over:score-=12
        last5=five[-1];setup_stamp=str(last5.get('time') or last5.get('timestamp') or last5.get('start') or last5.get('close_time') or len(five));setup_id=f"{symbol}:{direction}:{st}:{setup_stamp}"
        return {'symbol':symbol,'direction':direction,'trigger':trigger,'choppy':chop,'overextended':over,'score':max(0,min(100,score)),'structure':st,'setup_id':setup_id,'daily_pivots':daily_piv,'five_pivots':five_piv,'daily_zone':self._pivot_position(s5['price'],daily_piv),'five_zone':self._pivot_position(s5['price'],five_piv),'ema_cross_5m':cross,'ema_cross_aligned':cross_aligned,'price_ema_aligned':price_ema_aligned,'tf':{k:v['state'] for k,v in tfs.items()}}
    @staticmethod
    def _underlying(symbol):return 'BTC' if symbol=='BTCUSD' else ('ETH' if symbol=='ETHUSD' else 'GOLD')
    async def _option_candidates(self,symbol,direction):
        und=self._underlying(symbol);rows=await (delta_options_service.get_chain('XAUT') if und=='GOLD' else delta_options_service.get_chain(und));parsed=[]
        for row in rows:
            snap=delta_options_service._snapshot(row)
            if snap.get('strike') and snap.get('premium') and snap.get('expiry'):parsed.append(snap)
        if not parsed and und=='GOLD':
            rows=await delta_options_service.get_chain('PAXG');parsed=[delta_options_service._snapshot(r) for r in rows if delta_options_service._snapshot(r).get('premium')]
        if not parsed:return []
        expiry=min(x['expiry'] for x in parsed if x.get('expiry'));parsed=[x for x in parsed if x.get('expiry')==expiry];spot=next((x.get('spot_price') for x in parsed if x.get('spot_price')),None)
        if not spot:return []
        strikes=sorted({x['strike'] for x in parsed});atm=min(range(len(strikes)),key=lambda i:abs(strikes[i]-spot))
        def pick(side,otm_steps=3):
            idx=min(len(strikes)-1,atm+otm_steps) if side=='CE' else max(0,atm-otm_steps);target=strikes[idx];pool=[x for x in parsed if x.get('side')==side and x.get('strike')==target]
            if not pool:return None
            x=pool[0];bid=x.get('best_bid');ask=x.get('best_ask');prem=x.get('premium');spread=((ask-bid)/prem) if bid is not None and ask is not None and prem else None;x=dict(x);x['spread_pct']=spread*100 if spread is not None else None;return x
        if direction=='BULLISH':return [('OPTION BUY','CE',pick('CE')),('OPTION SELL','PE',pick('PE'))]
        if direction=='BEARISH':return [('OPTION BUY','PE',pick('PE')),('OPTION SELL','CE',pick('CE'))]
        return []
    async def _ai_review(self,snap,option):
        if not settings.DELTA_AI_CONFIRMATION:return 'NO AI CONFIRMATION (disabled)'
        payload={'direction':snap['direction'],'score':snap['score'],'structure':snap['structure'],'daily_pivots':snap['daily_pivots'],'five_pivots':snap['five_pivots'],'ema_cross_5m':snap.get('ema_cross_5m'),'daily_zone':snap.get('daily_zone'),'five_zone':snap.get('five_zone'),'timeframes':snap['tf'],'option':{k:option.get(k) for k in ('symbol','side','strike','premium','best_bid','best_ask','oi','volume','delta','bid_iv','ask_iv','spread_pct')}}
        system='Return ONLY compact JSON: {"decision":"CONFIRM|REJECT|WAIT","confidence":0-100,"short_reason":"..."}. You are only a second-opinion reviewer. Never invent data.'
        try:
            raw=await ai_router.answer(json.dumps(payload,separators=(',',':')),system)
            if raw.startswith('AI response unavailable'):return 'NO AI CONFIRMATION (provider unavailable/quota/timeout)'
            raw=raw.strip().removeprefix('```json').removesuffix('```').strip();obj=json.loads(raw);d=str(obj.get('decision','')).upper()
            if d not in {'CONFIRM','REJECT','WAIT'}:raise ValueError('invalid decision')
            return f"{d} ({int(obj.get('confidence') or 0)}%)"
        except Exception as e:
            logger.warning('[DELTA_AI] no confirmation: %s',e);return 'NO AI CONFIRMATION (invalid/unavailable)'
    async def analyze_symbol(self,symbol):
        snap=await self._snapshot(symbol);self.last_scan[symbol]=snap
        if snap['direction']=='MIXED' or not snap['trigger'] or snap['choppy'] or snap['overextended'] or snap['score']<settings.DELTA_MIN_SCORE:return []
        if not snap.get('ema_cross_aligned') or not snap.get('price_ema_aligned'):return []
        out=[];underlying=self._underlying(symbol)
        for action,side,opt in await self._option_candidates(symbol,snap['direction']):
            if not opt:continue
            allowed,policy_reason=evaluate_entry(underlying,action,snap)
            if not allowed:
                logger.info('[FRESH_V2] %s %s filtered: %s',underlying,action,policy_reason);continue
            tradeable,contract_reason=evaluate_contract(opt.get('premium'),bid=opt.get('best_bid'),ask=opt.get('best_ask'))
            if not tradeable:
                logger.info('[FRESH_V2_CONTRACT] %s %s %s filtered: %s',underlying,action,opt.get('symbol'),contract_reason);continue
            spread=opt.get('spread_pct')
            if spread is not None and spread>8:continue
            if (opt.get('volume') or 0)<=0 and (opt.get('oi') or 0)<=0:continue
            p=float(opt['premium']);risk=p*.12
            if action=='OPTION BUY':sl=p-risk;t1=p+risk*settings.RR_T1;t2=p+risk*settings.RR_T2;t3=p+risk*settings.RR_T3
            else:sl=p+risk;t1=p-risk*settings.RR_T1;t2=p-risk*settings.RR_T2;t3=p-risk*settings.RR_T3
            if min(sl,t1,t2,t3)<=0:continue
            ai=await self._ai_review(snap,opt) if snap['score']>=settings.DELTA_AI_MIN_SCORE else 'NO AI CONFIRMATION (not required)'
            cross=snap['ema_cross_5m'];reason=f"Python valid | {snap['direction']} | {snap['structure']} | EMA5/9 cross {cross['bars_ago']}b | D:{snap['daily_zone']} | 5m:{snap['five_zone']} | ADX {snap['tf']['5m']['adx']:.1f} | RVOL {snap['tf']['5m']['rel_volume']:.2f} | {POLISH_VERSION}"
            out.append(Candidate(underlying,snap['direction'],action,opt['symbol'],float(opt['strike']),opt['expiry'],p,sl,t1,t2,t3,settings.RR_T1,int(snap['score']),ai,reason,snap['setup_id'],time.time()))
        return out
    def format_signal(self,c):
        q='STRONG' if c.score>=settings.DELTA_STRONG_SCORE else 'VALID'
        return (f"🔥 *ROBO STAFF — DELTA SIGNAL*\n\n*{c.action}* — `{c.option_symbol}`\nDirection: *{c.direction}* | Quality: *{q}* | Python: `{c.score}/100`\n" f"Premium: `{c.premium:.6g}`\nSL: `{c.sl:.6g}`\nT1: `{c.t1:.6g}` | T2: `{c.t2:.6g}` | T3: `{c.t3:.6g}`\nR:R T1: `1:{c.rr:.2f}`\n" f"🤖 AI: *{c.ai_status}*\n⚙️ {c.reason}\n\n📡 Signal only — *NO ORDER EXECUTED*")
    async def _monitor_pending(self):
        for key,c in list(self.pending.items()):
            try:
                und='GOLD' if c.underlying=='GOLD' else c.underlying;snap=await (delta_options_service.get_gold_strike_snapshot(c.strike,c.expiry) if und=='GOLD' else delta_options_service.get_strike_snapshot(und,c.strike,c.expiry));side='ce' if c.option_symbol.startswith('C-') else 'pe';o=snap.get(side);px=float(o['premium']) if o and o.get('premium') is not None else None
                if px is None:continue
                success=(px>=c.t1) if c.action=='OPTION BUY' else (px<=c.t1);failed=(px<=c.sl) if c.action=='OPTION BUY' else (px>=c.sl)
                if success or failed:
                    elapsed=time.time()-c.created;performance_store.resolve(c.action,success,c.underlying,c.ai_status,elapsed);research_store.resolve(key,'T1' if success else 'SL',elapsed,px);self.pending.pop(key,None)
                    if failed:
                        if len(self.post_sl)>=50:oldest=min(self.post_sl,key=lambda k:self.post_sl[k]['failed_at']);self.post_sl.pop(oldest,None)
                        self.post_sl[key]={'candidate':c,'failed_at':time.time(),'t1_seen':False,'t2_seen':False}
                    await self._alert(f"{'✅ T1 SUCCESS' if success else '🛑 SL / FAILED'} — `{c.option_symbol}` | {c.action} | Premium `{px:.6g}`")
            except Exception as e:logger.debug('[DELTA_MONITOR] %s: %s',key,e)
    async def _monitor_post_sl(self):
        now=time.time()
        for key,item in list(self.post_sl.items()):
            c=item['candidate']
            if now-item['failed_at']>7200:self.post_sl.pop(key,None);continue
            try:
                und='GOLD' if c.underlying=='GOLD' else c.underlying;snap=await (delta_options_service.get_gold_strike_snapshot(c.strike,c.expiry) if und=='GOLD' else delta_options_service.get_strike_snapshot(und,c.strike,c.expiry));side='ce' if c.option_symbol.startswith('C-') else 'pe';o=snap.get(side);px=float(o['premium']) if o and o.get('premium') is not None else None
                if px is None:continue
                t1=(px>=c.t1) if c.action=='OPTION BUY' else (px<=c.t1);t2=(px>=c.t2) if c.action=='OPTION BUY' else (px<=c.t2)
                if t1 and not item['t1_seen']:item['t1_seen']=True;performance_store.mark_sl_recovery('t1');research_store.mark_recovery(key)
                if t2 and not item['t2_seen']:item['t2_seen']=True;performance_store.mark_sl_recovery('t2')
                if item['t2_seen']:self.post_sl.pop(key,None)
            except Exception as e:logger.debug('[DELTA_POST_SL] %s: %s',key,e)
    async def scan_once(self):
        self.last_scan_at=time.time();results={}
        for symbol in settings.delta_symbols():
            try:
                candidates=await self.analyze_symbol(symbol);results[symbol]={'status':'SIGNAL' if candidates else 'NO_TRADE','count':len(candidates)}
                for c in candidates:
                    key=f'{POLISH_VERSION}:{c.underlying}:{c.option_symbol}:{c.action}:{c.direction}:{c.setup_id}';now=time.time()
                    if now-self.last_alert.get(key,0)<settings.DELTA_SIGNAL_COOLDOWN_MINUTES*60:continue
                    self.last_alert[key]=now;self.last_signal=c
                    if len(self.pending)>=50:oldest=min(self.pending,key=lambda k:self.pending[k].created);self.pending.pop(oldest,None)
                    snap=self.last_scan.get({'BTC':'BTCUSD','ETH':'ETHUSD','GOLD':'XAUTUSD'}.get(c.underlying,''),{});tf5=(snap.get('tf') or {}).get('5m') or {};dp=snap.get('daily_pivots') or {};fp=snap.get('five_pivots') or {}
                    features={'research_epoch':POLISH_VERSION,'structure':snap.get('structure'),'score':snap.get('score'),'direction':snap.get('direction'),'ema_cross_5m':snap.get('ema_cross_5m'),'price_ema_aligned':snap.get('price_ema_aligned'),'ema5_5m':tf5.get('ema5'),'ema9_5m':tf5.get('ema9'),'ema20_5m':tf5.get('ema20'),'price_5m':tf5.get('price'),'adx5':tf5.get('adx'),'plus_di5':tf5.get('plus_di'),'minus_di5':tf5.get('minus_di'),'rvol5':tf5.get('rel_volume'),'atr5':tf5.get('atr'),'rsi5':tf5.get('rsi'),'wr5':tf5.get('williams_r'),'daily_pivot':dp.get('pivot'),'daily_s1':dp.get('s1'),'daily_r1':dp.get('r1'),'daily_zone':snap.get('daily_zone'),'five_pivot':fp.get('pivot'),'five_s1':fp.get('s1'),'five_r1':fp.get('r1'),'five_zone':snap.get('five_zone'),'polish_version':POLISH_VERSION}
                    research_store.add(key,c,features);self.pending[key]=c;performance_store.new_signal(c.action,c.ai_status,c.underlying);await self._alert(self.format_signal(c))
            except Exception as e:
                self.scan_errors+=1;results[symbol]={'status':'ERROR','error':str(e)[:160]};logger.warning('[DELTA_AUTO] %s failed: %s',symbol,e)
        await self._monitor_pending();await self._monitor_post_sl();return results
    async def loop(self):
        while True:
            self.loop_heartbeat=time.time()
            try:
                if self.running and settings.DELTA_AUTO_SIGNAL_ENGINE:await self.scan_once()
            except asyncio.CancelledError:raise
            except Exception as e:self.scan_errors+=1;logger.exception('[DELTA_AUTO] loop error: %s',e)
            await asyncio.sleep(max(15,settings.DELTA_SIGNAL_SCAN_SECONDS))

delta_auto_engine=DeltaAutoSignalEngine()