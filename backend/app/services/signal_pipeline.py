from __future__ import annotations
from typing import Any
from app.services.signal_engine import signal_engine
from app.services.options import option_selector, flatten_records
from app.services.lifecycle import signal_lifecycle

class SignalPipeline:
    """Combines underlying strategy output with deterministic option candidate selection."""
    def choose_option_from_payload(self, *, signal:dict[str,Any], underlying_ltp:float,
                                   option_payload:Any, option_type:str, exchange_segment:str="NSEFO") -> dict[str,Any]:
        records=flatten_records(option_payload)
        ranked=option_selector.rank(records,underlying_ltp=underlying_ltp,option_type=option_type,fallback_segment=exchange_segment)
        accepted=[x for x in ranked if x["accepted"]]
        if not accepted:
            return {"status":"REJECTED","reason":"NO_QUALITY_OPTION","candidates":ranked[:10]}
        chosen=accepted[0]
        premium=chosen.get("ltp")
        result={"status":"READY","underlying_signal":signal,"option":chosen}
        if premium and premium > 0:
            # Option SL/targets are deliberately not fabricated from underlying RR.
            # Lifecycle tracks the option only when explicit premium levels are supplied later.
            result["premium_live"]=premium
        return result

    def track_underlying_signal(self, signal:dict[str,Any], ttl_sec:int=1800)->dict[str,Any]:
        return signal_lifecycle.create(symbol_key=signal["symbol_key"],side=signal["side"],entry=float(signal["entry"]),
            stop=float(signal["stop"]),target1=float(signal["target1"]),target2=float(signal["target2"]),ttl_sec=ttl_sec)

signal_pipeline=SignalPipeline()
