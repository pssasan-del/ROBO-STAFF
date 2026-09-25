from config import settings, logger
from delta_market_service import delta_market_service
from strategy_engine import ema, atr, vwap, directional_values

class EntryBacktester:
    """Read-only entry-timing diagnostic using Delta 5m underlying candles.
    It deliberately does NOT claim to be an exact historical option-premium backtest.
    """
    @staticmethod
    def _structure(rows):
        a=rows[-12:-6];b=rows[-6:]
        if not a or not b:return 'UNKNOWN'
        ah,al=max(x['high'] for x in a),min(x['low'] for x in a);bh,bl=max(x['high'] for x in b),min(x['low'] for x in b)
        if bh>ah and bl>al:return 'HH/HL'
        if bh<ah and bl<al:return 'LH/LL'
        return 'RANGE'

    @staticmethod
    def _entry_ok(rows):
        cl=[x['close'] for x in rows];px=cl[-1];e5,e9,e20=ema(cl,5),ema(cl,9),ema(cl,20);vw=vwap(rows,30);adx,pdi,mdi=directional_values(rows,14);a=atr(rows,14)
        avg=sum(x['volume'] for x in rows[-21:-1])/max(1,len(rows[-21:-1]));rel=(rows[-1]['volume']/avg) if avg else 0;st=EntryBacktester._structure(rows)
        bull=e5>e9>e20 and px>vw and pdi>=mdi and st=='HH/HL';bear=e5<e9<e20 and px<vw and mdi>=pdi and st=='LH/LL'
        chop=adx<16 or (abs(e5-e20)/max(px,1)<0.00035 and rel<0.9) or st=='RANGE';over=abs(px-vw)>max(2.5*a,px*.01)
        if chop or over:return None
        return 'LONG' if bull else ('SHORT' if bear else None)

    async def run(self,symbol,limit=600):
        rows=await delta_market_service.get_candles(symbol,'5m',max(120,min(limit,600))); trades=[]
        # Diagnostic: same 12% risk geometry converted to underlying percentage only for entry-timing comparison.
        for i in range(40,len(rows)-5):
            side=self._entry_ok(rows[:i+1])
            if not side:continue
            base=rows[i]['close']
            for delay in (0,1,2,3):
                j=i+delay
                if j>=len(rows)-1:continue
                entry=rows[j]['close'];window=rows[max(0,j-14):j+1];risk=max(atr(window,14),entry*.0005);sl=entry-risk if side=='LONG' else entry+risk;t1=entry+risk*settings.RR_T1 if side=='LONG' else entry-risk*settings.RR_T1
                outcome='OPEN';bars=0
                for k in range(j+1,min(len(rows),j+25)):
                    bars=k-j;hi,lo=rows[k]['high'],rows[k]['low']
                    # Conservative same-candle collision: SL wins when both levels are touched.
                    if side=='LONG':
                        if lo<=sl:outcome='SL';break
                        if hi>=t1:outcome='T1';break
                    else:
                        if hi>=sl:outcome='SL';break
                        if lo<=t1:outcome='T1';break
                trades.append((delay,outcome,bars))
            i+=3
        summary={}
        for delay in (0,1,2,3):
            x=[t for t in trades if t[0]==delay and t[1] in {'T1','SL'}];w=sum(t[1]=='T1' for t in x);l=sum(t[1]=='SL' for t in x);summary[delay]={'w':w,'l':l,'rate':round(100*w/(w+l),1) if w+l else 0.0}
        return summary

entry_backtester=EntryBacktester()
