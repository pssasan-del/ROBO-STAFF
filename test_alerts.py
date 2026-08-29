import time
import pytest
from models import ScanMatch, ConditionMatchDetail
from alerts import AlertManager
from storage import storage

def test_alert_formatting():
    match = ScanMatch(
        strategy_id="s1",
        strategy_name="EMA + RSI Breakout",
        symbol="NSE:RELIANCE-EQ",
        company_name="RELIANCE",
        ltp=2950.40,
        timeframe="5",
        matched_conditions=[
            ConditionMatchDetail(condition_index=0, condition_desc="EMA20 > EMA50", actual_value="EMA20=2940, EMA50=2920", passed=True),
            ConditionMatchDetail(condition_index=1, condition_desc="RSI(14) > 55", actual_value="61.4", passed=True)
        ],
        signature="s1_RELIANCE_ema_rsi_1035",
        is_mock=False
    )
    alert_text = AlertManager.format_telegram_alert(match)
    assert "RELIANCE" in alert_text
    assert "₹2,950.40" in alert_text
    assert "EMA20 > EMA50" in alert_text
    assert "RSI(14) > 55" in alert_text
    assert "ACTIVE SCANNER" in alert_text

def test_alert_cooldown_deduplication():
    unique_sig = f"test_cooldown_{time.time()}"
    match = ScanMatch(
        strategy_id="s_cool",
        strategy_name="Cooldown Test",
        symbol="NSE:TCS-EQ",
        ltp=3800.0,
        timeframe="5",
        signature=unique_sig
    )

    # First attempt should succeed and record
    assert AlertManager.should_send_alert(match) is True

    # Immediate second attempt with same signature should be suppressed by cooldown
    assert AlertManager.should_send_alert(match) is False
