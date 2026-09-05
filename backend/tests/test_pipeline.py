from app.services.market_pipeline import CandleBuilder
from app.services.signal_engine import BaselineSignalEngine
from app.services.risk import RiskEngine


def test_candle_builder_closes_bucket():
    b = CandleBuilder((60,))
    assert b.ingest("NSECM|1", 100, 120, 1000) == []
    b.ingest("NSECM|1", 102, 130, 1010)
    closed = b.ingest("NSECM|1", 101, 180, 1020)
    assert len(closed) == 1
    assert closed[0].open == 100 and closed[0].high == 102 and closed[0].close == 102
    assert closed[0].volume == 10


def test_signal_engine_insufficient_history():
    e = BaselineSignalEngine()
    r = e.evaluate("x", [], 300)
    assert r["reason"] == "INSUFFICIENT_HISTORY"


def test_signal_engine_breakout_buy():
    rows=[]
    for i in range(22):
        p=100 + i*0.05
        rows.append({"open":p,"high":p+0.2,"low":p-0.2,"close":p})
    rows[-1] = {"open":102,"high":103.2,"low":101.9,"close":103.1}
    r=BaselineSignalEngine().evaluate("x", rows, 300)
    assert r["status"] == "SIGNAL" and r["signal"]["side"] == "BUY"


def test_risk_is_locked_by_default_and_duplicate_protected():
    r=RiskEngine()
    first=r.preflight(symbol="ABC",side="BUY",quantity=1,reference_price=100,live_price=100)
    assert not first["ok"] and "TRADING_DISABLED" in first["reasons"]
    r.set_enabled(True)
    ok=r.preflight(symbol="ABC",side="BUY",quantity=1,reference_price=100,live_price=100)
    assert ok["ok"]
    dup=r.preflight(symbol="ABC",side="BUY",quantity=1,reference_price=100,live_price=100)
    assert "DUPLICATE_ORDER" in dup["reasons"]

from app.services.options import OptionSelector, flatten_records
from app.services.lifecycle import SignalLifecycle


def test_option_selector_accepts_tight_spread_atm():
    s=OptionSelector(max_spread_pct=2.0)
    rows=[{"instrument_token":"101","trading_symbol":"NIFTYCE","option_type":"CE","strike_price":25000,
           "last_traded_price":100,"best_bid_price":99.5,"best_ask_price":100.5,"volume":10000,"oi":50000}]
    r=s.rank(rows,underlying_ltp=25020,option_type="CE")
    assert r and r[0]["accepted"] is True and r[0]["spread_pct"] < 2


def test_option_selector_rejects_wide_spread():
    s=OptionSelector(max_spread_pct=2.0)
    rows=[{"instrument_token":"101","trading_symbol":"NIFTYCE","option_type":"CE","strike_price":25000,
           "last_traded_price":100,"best_bid_price":90,"best_ask_price":110}]
    r=s.rank(rows,underlying_ltp=25020,option_type="CE")
    assert r[0]["accepted"] is False and "SPREAD_TOO_WIDE" in r[0]["reasons"]


def test_flatten_records_handles_envelope():
    p={"data":{"quotes":[{"instrument_token":"7","ltp":42.0}]}}
    r=flatten_records(p)
    assert len(r)==1 and r[0]["instrument_token"]=="7"


def test_signal_lifecycle_buy_path_and_terminal_state():
    l=SignalLifecycle()
    s=l.create(symbol_key="NSEFO|1",side="BUY",entry=100,stop=95,target1=110,target2=120,ttl_sec=1000)
    sid=s["id"]
    assert l.update_price(sid,100)["state"]=="ENTRY"
    assert l.update_price(sid,111)["state"]=="T1"
    assert l.update_price(sid,121)["state"]=="T2"
    assert l.update_price(sid,90)["state"]=="T2"


def test_signal_lifecycle_sell_sl():
    l=SignalLifecycle()
    s=l.create(symbol_key="NSEFO|2",side="SELL",entry=100,stop=105,target1=90,target2=80,ttl_sec=1000)
    assert l.update_price(s["id"],106)["state"]=="SL"
