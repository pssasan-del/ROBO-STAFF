import json, re
from ai_router import ai_router
from config import logger

SUPPORTED_INDICATORS=['close','open','high','low','ema','sma','rsi','vwap','volume','volume_sma','atr','highest','lowest','previous_high','previous_low']
SUPPORTED_OPS=['>','>=','<','<=','==','cross_above','cross_below']

SCHEMA_SYSTEM='''You convert human trading strategies into STRICT JSON for a deterministic crypto scanner. No prose, markdown or code fences.
Allowed symbols: BTCUSD, ETHUSD. Allowed timeframes: 1m,3m,5m,15m,30m,1h,2h,4h,6h,12h,1d.
Output exactly: {"name":"...","symbol":"BTCUSD","timeframe":"5m","side":"LONG|SHORT|SIGNAL","rules":[...]}
Each rule: {"left":{"indicator":"ema|sma|rsi|vwap|close|open|high|low|volume|volume_sma|atr|highest|lowest|previous_high|previous_low","period":20},"op":">|>=|<|<=|==|cross_above|cross_below","right":{"type":"value|indicator","value":55,"indicator":"...","period":50,"multiplier":1.0}}
Omit period where not needed. For phrases like volume > 1.5x average volume 20, use left volume and right indicator volume_sma period20 multiplier1.5. For 20-candle breakout use close > highest period20. Never create unsupported indicators. Keep 1-12 rules.''' 


def _extract_json(raw:str):
    raw=raw.strip(); raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw,flags=re.I|re.S)
    a=raw.find('{'); b=raw.rfind('}')
    if a<0 or b<a: raise ValueError('AI did not return strategy JSON')
    return json.loads(raw[a:b+1])

def validate_strategy(d):
    if not isinstance(d,dict): raise ValueError('Strategy must be object')
    name=str(d.get('name') or 'Custom Strategy').strip()[:60]
    symbol=str(d.get('symbol') or '').upper().replace('/','').replace('USDT','USD')
    if symbol not in {'BTCUSD','ETHUSD'}: raise ValueError('Only BTCUSD/ETHUSD supported in V5')
    tf=str(d.get('timeframe') or '').lower()
    if tf not in {'1m','3m','5m','15m','30m','1h','2h','4h','6h','12h','1d'}: raise ValueError('Unsupported timeframe')
    side=str(d.get('side') or 'SIGNAL').upper()
    if side not in {'LONG','SHORT','SIGNAL'}: side='SIGNAL'
    rules=d.get('rules')
    if not isinstance(rules,list) or not 1<=len(rules)<=12: raise ValueError('Strategy needs 1-12 rules')
    cleaned=[]
    for rule in rules:
        if not isinstance(rule,dict): raise ValueError('Invalid rule')
        left=rule.get('left') or {}; right=rule.get('right') or {}; op=rule.get('op')
        li=left.get('indicator'); rt=right.get('type')
        if li not in SUPPORTED_INDICATORS or op not in SUPPORTED_OPS or rt not in {'value','indicator'}: raise ValueError(f'Unsupported rule: {rule}')
        if rt=='indicator' and right.get('indicator') not in SUPPORTED_INDICATORS: raise ValueError('Unsupported right indicator')
        for obj in (left,right):
            if 'period' in obj:
                p=int(obj['period']);
                if not 1<=p<=500: raise ValueError('Indicator period out of range')
                obj['period']=p
            if 'multiplier' in obj: obj['multiplier']=float(obj['multiplier'])
        if rt=='value': right['value']=float(right['value'])
        cleaned.append({'left':left,'op':op,'right':right})
    return {'name':name,'symbol':symbol,'timeframe':tf,'side':side,'rules':cleaned}

async def parse_strategy_text(text:str):
    raw=await ai_router.answer('Convert this strategy:\n'+text,SCHEMA_SYSTEM)
    try:return validate_strategy(_extract_json(raw))
    except Exception as exc:
        logger.warning('[STRATEGY_AI] invalid parse: %s raw=%s',exc,raw[:500]); raise

async def parse_strategy_file(data:bytes,mime_type:str,caption=''):
    raw=await ai_router.answer_file(data,mime_type,'Extract the trading strategy from this uploaded file/image/PDF. '+caption+'\nReturn only the strict JSON requested.',SCHEMA_SYSTEM)
    return validate_strategy(_extract_json(raw))

def format_preview(d):
    def spec(x):
        ind=x.get('indicator')
        if ind:
            p=x.get('period'); base=f'{ind.upper()}({p})' if p else ind.upper(); mult=x.get('multiplier')
            if mult and float(mult)!=1: base+=f' × {mult:g}'
            return base
        return str(x.get('value'))
    lines=[f'🧠 *Strategy Preview*',f'Name: *{d["name"]}*',f'Symbol: `{d["symbol"]}` | TF: `{d["timeframe"]}` | Signal: `{d["side"]}`','', '*Rules:*']
    for i,r in enumerate(d['rules'],1):
        right=str(r['right'].get('value')) if r['right']['type']=='value' else spec(r['right'])
        lines.append(f'{i}. {spec(r["left"])} `{r["op"]}` {right}')
    lines.append('\nSave only after checking every rule.')
    return '\n'.join(lines)
