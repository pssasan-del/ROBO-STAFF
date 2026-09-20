import asyncio, json, math, time
from dataclasses import dataclass, asdict
from typing import Dict, Optional
from config import settings, logger
from delta_market_service import delta_market_service
from delta_options_service import delta_options_service
from ai_router import ai_router
from performance_store import performance_store
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
        self.last_scan:Dict[str,dict]={};self.last_alert:Dict[str,float]={};self.pending:Dict[str,Candidate]={};self.loop_heartbeat=0.0
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
        # bounded/simple swing context using recent completed windows
        a=rows[-12:-6];b=rows[-6:]
        if not a or not b:return 'UNKNOWN'
        ah,al=max(x['high'] for x in a),min(x['low'] for x in a);bh,bl=max(x['high'] for x in b),min(x['low'] for x in b)
        if bh>ah and bl>al:return 'HH/HL'
        if bh<ah and bl<al:return 'LH/LL'
        return 'RANGE'
    async def _snapshot(self,symbol):
        lim=settings.DELTA_CANDLE_LIMIT
        tfs={}
        for tf in ('1m','5m','15m','1h','1d'):
            rows=await delta_market_service.get_candles(symbol,tf,lim if tf!='1d' else 40)
            if len(rows)<30:raise RuntimeError(f'{symbol} {tf} insufficient candles={len(rows)}')
            tfs[tf]={'rows':rows,'state':self._tf_state(rows)}
        day=tfs['1d']['rows'];daily_piv=fibonacci_pivots(day[-2]);five=tfs['5m']['rows'];five_piv=fibonacci_pivots(five[-2])
        st=self._structure(five);s1=tfs['1m']['state'];s5=tfs['5m']['state'];s15=tfs['15m']['state'];s1h=tfs['1h']['state'];sd=tfs['1d']['state']
        bull=sum(x['trend']=='BULLISH' for x in (sd,s1h,s15,s5));bear=sum(x['trend']=='BEARISH' for x in (sd,s1h,s15,s5))
        direction='BULLISH' if bull>=3 else ('BEARISH' if bear>=3 else 'MIXED')
        # 1m trigger cannot override HTF. Require aligned trigger for executable candidate.
        trigger=(direction=='BULLISH' and s1['trend']=='BULLISH') or (direction=='BEARISH' and s1['trend']=='BEARISH')
        chop=s5['adx']<16 or (abs(s5['ema5']-s5['ema20'])/max(s5['price'],1)<0.00035 and s5['rel_volume']<0.9) or st=='RANGE'
        over=abs(s5['price']-s5['vwap'])>max(2.5*s5['atr'],s5['price']*.01)
        score=50
        score+=10 if direction!='MIXED' else -20;score+=8 if trigger else -10;score+=7 if s5['adx']>=20 else -5;score+=6 if s5['rel_volume']>=1.0 else -3
        score+=7 if (direction=='BULLISH' and st=='HH/HL') or (direction=='BEARISH' and st=='LH/LL') else 0
        score+=5 if (direction=='BULLISH' and s5['price']>=daily_piv['pivot']) or (direction=='BEARISH' and s5['price']<=daily_piv['pivot']) else 0
        if chop:score-=18
        if over:score-=12
        # Setup identity is tied to the active 5m setup candle. This suppresses only
        # duplicate alerts from repeated scans of the same setup; a new 5m setup can alert.
        last5=five[-1]
        setup_stamp=str(last5.get('time') or last5.get('timestamp') or last5.get('start') or last5.get('close_time') or len(five))
        setup_id=f"{symbol}:{direction}:{st}:{setup_stamp}"
        return {'symbol':symbol,'direction':direction,'trigger':trigger,'choppy':chop,'overextended':over,'score':max(0,min(100,score)),'structure':st,'setup_id':setup_id,'daily_pivots':daily_piv,'five_pivots':five_piv,'tf':{k:v['state'] for k,v in tfs.items()}}
    @staticmethod
    def _underlying(symbol):return 'BTC' if symbol=='BTCUSD' else ('ETH' if symbol=='ETHUSD' else 'GOLD')
    async def _option_candidates(self,symbol,direction):
        und=self._underlying(symbol)
        rows=await (delta_options_service.get_chain('XAUT') if und=='GOLD' else delta_options_service.get_chain(und))
        parsed=[]
        for row in rows:
            snap=delta_options_service._snapshot(row)
            if snap.get('strike') and snap.get('premium') and snap.get('expiry'):parsed.append(snap)
        if not parsed and und=='GOLD':
            rows=await delta_options_service.get_chain('PAXG');parsed=[delta_options_service._snapshot(r) for r in rows if delta_options_service._snapshot(r).get('premium')]
        if not parsed:return []
        expiry=min(x['expiry'] for x in parsed if x.get('expiry'));parsed=[x for x in parsed if x.get('expiry')==expiry]
        spot=next((x.get('spot_price') for x in parsed if x.get('spot_price')),None)
        if not spot:return []
        strikes=sorted({x['strike'] for x in parsed});atm=min(range(len(strikes)),key=lambda i:abs(strikes[i]-spot));
        def pick(side,otm_steps=3):
            # CALL OTM above spot, PUT OTM below spot
            idx=min(len(strikes)-1,atm+otm_steps) if side=='CE' else max(0,atm-otm_steps);target=strikes[idx]
            pool=[x for x in parsed if x.get('side')==side and x.get('strike')==target]
            if not pool:return None
            x=pool[0];bid=x.get('best_bid');ask=x.get('best_ask');prem=x.get('premium')
            spread=((ask-bid)/prem) if bid is not None and ask is not None and prem else None
            x=dict(x);x['spread_pct']=spread*100 if spread is not None else None;return x
        # both BUY and SELL signal families are supported.
        if direction=='BULLISH':return [('OPTION BUY','CE',pick('CE')),('OPTION SELL','PE',pick('PE'))]
        if direction=='BEARISH':return [('OPTION BUY','PE',pick('PE')),('OPTION SELL','CE',pick('CE'))]
        return []
    async def _ai_review(self,snap,option):
        if not settings.DELTA_AI_CONFIRMATION:return 'NO AI CONFIRMATION (disabled)'
        payload={'direction':snap['direction'],'score':snap['score'],'structure':snap['structure'],'daily_pivots':snap['daily_pivots'],'five_pivots':snap['five_pivots'],'timeframes':snap['tf'],'option':{k:option.get(k) for k in ('symbol','side','strike','premium','best_bid','best_ask','oi','volume','delta','bid_iv','ask_iv','spread_pct')}}
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
        out=[]
        for action,side,opt in await self._option_candidates(symbol,snap['direction']):
            if not opt:continue
            spread=opt.get('spread_pct')
            if spread is not None and spread>8:continue
            if (opt.get('volume') or 0)<=0 and (opt.get('oi') or 0)<=0:continue
            p=float(opt['premium']);risk=max(p*.12,0.01)
            if action=='OPTION BUY':sl=max(.000001,p-risk);t1=p+risk*settings.RR_T1;t2=p+risk*settings.RR_T2;t3=p+risk*settings.RR_T3
            else:sl=p+risk;t1=max(.000001,p-risk*settings.RR_T1);t2=max(.000001,p-risk*settings.RR_T2);t3=max(.000001,p-risk*settings.RR_T3)
            ai=await self._ai_review(snap,opt) if snap['score']>=settings.DELTA_AI_MIN_SCORE else 'NO AI CONFIRMATION (not required)'
            # AI is non-blocking by locked requirement: valid Python signal still alerts on REJECT/WAIT/unavailable.
            reason=f"Python valid | {snap['direction']} | {snap['structure']} | 1m trigger | 5m ADX {snap['tf']['5m']['adx']:.1f} | RVOL {snap['tf']['5m']['rel_volume']:.2f}"
            out.append(Candidate(self._underlying(symbol),snap['direction'],action,opt['symbol'],float(opt['strike']),opt['expiry'],p,sl,t1,t2,t3,settings.RR_T1,int(snap['score']),ai,reason,snap['setup_id'],time.time()))
        return out
    def format_signal(self,c):
        q='STRONG' if c.score>=settings.DELTA_STRONG_SCORE else 'VALID'
        return (f"🔥 *ROBO STAFF — DELTA SIGNAL*\n\n*{c.action}* — `{c.option_symbol}`\nDirection: *{c.direction}* | Quality: *{q}* | Python: `{c.score}/100`\n"
                f"Premium: `{c.premium:.6g}`\nSL: `{c.sl:.6g}`\nT1: `{c.t1:.6g}` | T2: `{c.t2:.6g}` | T3: `{c.t3:.6g}`\nR:R T1: `1:{c.rr:.2f}`\n"
                f"🤖 AI: *{c.ai_status}*\n⚙️ {c.reason}\n\n📡 Signal only — *NO ORDER EXECUTED*")
    async def _monitor_pending(self):
        # Minimal in-RAM outcome monitoring; only aggregate counts persist.
        for key,c in list(self.pending.items()):
            try:
                und='GOLD' if c.underlying=='GOLD' else c.underlying
                snap=await (delta_options_service.get_gold_strike_snapshot(c.strike,c.expiry) if und=='GOLD' else delta_options_service.get_strike_snapshot(und,c.strike,c.expiry))
                side='ce' if c.option_symbol.startswith('C-') else 'pe';o=snap.get(side);px=float(o['premium']) if o and o.get('premium') is not None else None
                if px is None:continue
                success=(px>=c.t1) if c.action=='OPTION BUY' else (px<=c.t1);failed=(px<=c.sl) if c.action=='OPTION BUY' else (px>=c.sl)
                if success or failed:
                    performance_store.resolve(c.action,success);self.pending.pop(key,None);await self._alert(f"{'✅ T1 SUCCESS' if success else '🛑 SL / FAILED'} — `{c.option_symbol}` | {c.action} | Premium `{px:.6g}`")
            except Exception as e:logger.debug('[DELTA_MONITOR] %s: %s',key,e)
    async def scan_once(self):
        self.last_scan_at=time.time();results={}
        for symbol in settings.delta_symbols():
            try:
                candidates=await self.analyze_symbol(symbol);results[symbol]={'status':'SIGNAL' if candidates else 'NO_TRADE','count':len(candidates)}
                for c in candidates:
                    # Duplicate suppression is strictly per symbol/instrument + action + direction + setup.
                    # There is NO global cooldown: BTC, ETH and GOLD remain independent and simultaneous
                    # valid signals are all allowed. A fresh 5m setup gets a new setup_id and may alert.
                    key=f'{c.underlying}:{c.option_symbol}:{c.action}:{c.direction}:{c.setup_id}';now=time.time()
                    if now-self.last_alert.get(key,0)<settings.DELTA_SIGNAL_COOLDOWN_MINUTES*60:continue
                    self.last_alert[key]=now;self.last_signal=c
                    # Hard bound transient unresolved signals to protect RAM on long runtimes.
                    if len(self.pending)>=50:
                        oldest=min(self.pending,key=lambda k:self.pending[k].created);self.pending.pop(oldest,None)
                    self.pending[key]=c;performance_store.new_signal(c.action,c.ai_status.startswith('CONFIRM'));await self._alert(self.format_signal(c))
            except Exception as e:
                self.scan_errors+=1;results[symbol]={'status':'ERROR','error':str(e)[:160]};logger.warning('[DELTA_AUTO] %s failed: %s',symbol,e)
        await self._monitor_pending();return results
    async def loop(self):
        while True:
            self.loop_heartbeat=time.time()
            try:
                if self.running and settings.DELTA_AUTO_SIGNAL_ENGINE:await self.scan_once()
            except asyncio.CancelledError:raise
            except Exception as e:self.scan_errors+=1;logger.exception('[DELTA_AUTO] loop error: %s',e)
            await asyncio.sleep(max(15,settings.DELTA_SIGNAL_SCAN_SECONDS))

delta_auto_engine=DeltaAutoSignalEngine()
