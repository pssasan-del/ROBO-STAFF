from pathlib import Path
from app.services.recovery import RecoveryStore


def test_recovery_store_roundtrip(tmp_path: Path):
    p = tmp_path / "state.json"
    s = RecoveryStore(str(p))
    s.set_core_indices([{"label":"NIFTY 50","ok":True,"exchange_segment":"NSE","instrument_token":"26000"}])
    s.remember_instrument("NSE|26000", {"symbol":"NIFTY 50","token":"26000"})
    r = RecoveryStore(str(p)).snapshot()
    assert r["core_indices"][0]["label"] == "NIFTY 50"
    assert "NSE|26000" in r["verified_instruments"]
