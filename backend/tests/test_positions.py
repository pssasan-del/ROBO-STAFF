import asyncio
from app.services.positions import PositionManager


def _sample():
    return {"stat":"ok","data":[{"exSeg":"nse_fo","tok":"61304","trdSym":"ABC26AUGFUT","prod":"NRML",
        "cfBuyQty":"0","cfSellQty":"0","flBuyQty":"10","flSellQty":"0","cfBuyAmt":"0","cfSellAmt":"0",
        "buyAmt":"1000","sellAmt":"0","lotSz":"5","multiplier":"1","genNum":"1","genDen":"1","prcNum":"1","prcDen":"1"}]}


def test_position_normalization_and_mtm():
    p=PositionManager(); rows=p.sync_rest(_sample()); assert len(rows)==1
    x=rows[0]; assert x["net_quantity"]==10 and x["average_price"]==100
    changed=p.on_tick("nse_fo","61304",110); assert round(changed[0]["pnl"],2)==100
    assert p.summary()["day_mtm"]==100


def test_partial_exit_order_reverses_side():
    p=PositionManager(); p.sync_rest(_sample()); key=next(iter(p.items))
    o=p.build_exit_order(key,4); assert o["transaction_type"]=="S" and o["quantity"]=="4"


def test_short_exit_reverses_to_buy():
    p=PositionManager(); d=_sample(); row=d["data"][0]; row["flBuyQty"]="0"; row["flSellQty"]="7"; row["buyAmt"]="0"; row["sellAmt"]="700"
    p.sync_rest(d); key=next(iter(p.items)); o=p.build_exit_order(key); assert o["transaction_type"]=="B" and o["quantity"]=="7"


def test_manual_exit_plan_triggers_without_order():
    p=PositionManager(); p.sync_rest(_sample()); key=next(iter(p.items)); plan=p.create_exit_plan(key,stop_loss=95,target1=110,auto_exit=False)
    ev=asyncio.run(p.evaluate_exit_plans(key,111)); assert ev and ev[0]["state"]=="TRIGGERED_MANUAL" and ev[0]["triggered_level"]=="TARGET1"


def test_auto_exit_plan_submits_partial_t1():
    p=PositionManager(); p.sync_rest(_sample()); key=next(iter(p.items)); p.create_exit_plan(key,stop_loss=95,target1=110,target2=120,target1_fraction=.5,auto_exit=True)
    seen={}
    async def submitter(**kwargs): seen.update(kwargs); return {"nOrdNo":"X1","stat":"Ok"}
    ev=asyncio.run(p.evaluate_exit_plans(key,111,submitter=submitter))
    assert ev[0]["state"]=="EXIT_SUBMITTED" and seen["quantity"]=="5" and seen["transaction_type"]=="S"
