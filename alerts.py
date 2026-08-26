import time
import datetime
from typing import Optional, List
from config import settings, logger
from models import ScanMatch
from storage import storage

class AlertManager:
    """
    Telegram Alert Formatter and Spam Prevention / Deduplication Manager.
    """

    @staticmethod
    def format_telegram_alert(match: ScanMatch) -> str:
        ist_now = datetime.datetime.now().strftime("%I:%M %p")
        mock_tag = "\n⚠️ *TEST / MOCK DATA*" if match.is_mock or settings.MOCK_MARKET_DATA else ""
        
        conditions_text = ""
        for cond in match.matched_conditions:
            if cond.passed:
                val_note = f" ({cond.actual_value})" if cond.actual_value and cond.actual_value != "Passed" else ""
                conditions_text += f"✅ *{cond.condition_desc}*{val_note}\n"

        if not conditions_text:
            conditions_text = "✅ *All strategy rules matched*\n"

        msg = (
            f"🔔 *STRATEGY MATCH FOUND*{mock_tag}\n\n"
            f"🏢 *{match.company_name or match.symbol}*\n"
            f"💰 *Price:* ₹{match.ltp:,.2f}\n"
            f"⏱ *Timeframe:* {match.timeframe}M | *Time:* {ist_now}\n"
            f"🎯 *Strategy:* {match.strategy_name}\n\n"
            f"📊 *CONDITIONS MET:*\n"
            f"{conditions_text}\n"
            f"📡 *Data Source:* {'FYERS LIVE' if not (match.is_mock or settings.MOCK_MARKET_DATA) else 'MOCK ENGINE'}\n"
            f"⚡ *Status:* ACTIVE SCANNER"
        )
        return msg

    @classmethod
    def should_send_alert(cls, match: ScanMatch) -> bool:
        """
        Checks if alert should be sent based on cooldown rules.
        """
        if storage.is_alert_on_cooldown(match.signature, settings.ALERT_COOLDOWN_MINUTES):
            logger.debug(f"[ALERT] Suppressed duplicate alert for {match.symbol} ({match.strategy_name})")
            return False
        
        # Record alert in storage
        storage.record_alert(match)
        return True
