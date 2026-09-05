import asyncio
from app.services.execution import ExecutionEngine, ExecutionState
from app.services.risk import risk_engine


def _reset_risk():
    risk_engine._recent.clear()
    risk_engine.set_enabled(True)


def test_execution_requires_arm():
    _reset_risk()
    e=ExecutionEngine()
    r=e.create_intent(order={},symbol="ABC",side="BUY",quantity=1,reference_price=100,live_price=100)
    assert not r["ok"] and "EXECUTION_NOT_ARMED" in r["reasons"]


def test_confirmation_is_single_use_and_tracks_fill():
    _reset_risk()
    e=ExecutionEngine(confirmation_ttl_sec=30)
    e.arm(True)
    order={"exchange_segment":"NSECM","product":"MIS","price":"0","order_type":"MARKET","quantity":"1",
           "validity":"DAY","trading_symbol":"ABC-EQ","transaction_type":"B","trigger_price":"0","amo":"NO"}
    r=e.create_intent(order=order,symbol="ABC-EQ",side="BUY",quantity=1,reference_price=100,live_price=100)
    async def submitter(**kwargs):
        return {"nOrdNo":"12345", "stat":"Ok"}
    c=asyncio.run(e.confirm(intent_id=r["intent_id"],confirmation_token=r["confirmation_token"],live_price=100,
                          open_positions=0,day_pnl=0,submitter=submitter))
    assert c["ok"] and c["execution"]["state"] == ExecutionState.ACKNOWLEDGED.value
    again=asyncio.run(e.confirm(intent_id=r["intent_id"],confirmation_token=r["confirmation_token"],live_price=100,
                              open_positions=0,day_pnl=0,submitter=submitter))
    assert not again["ok"] and "INTENT_ALREADY_USED" in again["reasons"]
    u=e.on_order_update({"type":"order","data":{"order_id":"12345","order_status":"complete","average_price":"101.25","filled_quantity":1}})
    assert u["state"] == "FILLED" and u["average_price"] == 101.25


def test_confirm_rechecks_price_slippage():
    _reset_risk()
    e=ExecutionEngine(); e.arm(True)
    order={"exchange_segment":"NSECM","product":"MIS","price":"0","order_type":"MARKET","quantity":"1",
           "validity":"DAY","trading_symbol":"ABC-EQ","transaction_type":"B","trigger_price":"0","amo":"NO"}
    r=e.create_intent(order=order,symbol="ABC-EQ",side="BUY",quantity=1,reference_price=100,live_price=100)
    async def submitter(**kwargs):
        raise AssertionError("must not submit")
    c=asyncio.run(e.confirm(intent_id=r["intent_id"],confirmation_token=r["confirmation_token"],live_price=103,
                          open_positions=0,day_pnl=0,submitter=submitter))
    assert not c["ok"] and "STALE_OR_MOVED_PRICE" in c["reasons"]


def test_disarm_invalidates_pending_confirmation():
    _reset_risk()
    e=ExecutionEngine(); e.arm(True)
    r=e.create_intent(order={},symbol="ABC",side="BUY",quantity=1,reference_price=100,live_price=100)
    e.arm(False)
    assert e.get(r["intent_id"])["state"] == "CANCELLED"
