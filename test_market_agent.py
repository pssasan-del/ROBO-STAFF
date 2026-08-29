from market_agent import MarketAgent
from bot import TelegramBot


def test_extract_historical_date_formats():
    assert MarketAgent._extract_date("ITC 2024 Oct 5 price") == "2024-10-05"
    assert MarketAgent._extract_date("ITC 5 October 2024 price") == "2024-10-05"


def test_option_request():
    assert MarketAgent._option_request("Nifty 24000 PE current price") == (24000, "PE")
    assert MarketAgent._option_request("Nifty 24000 call price") == (24000, "CE")


def test_sensex_symbol_resolution():
    assert MarketAgent._resolve_symbol("Sensex current price") == "BSE:SENSEX-INDEX"


def test_saved_keyboard_has_five_stock_start_buttons():
    kb = TelegramBot().get_saved_strategy_keyboard()
    starts = [b["text"] for row in kb["keyboard"] for b in row if b["text"].startswith("▶")]
    assert starts == ["▶ 200% CALL", "▶ 200% PUT", "▶ ORB CALL", "▶ ORB PUT", "▶ MIXED 44"]


def test_option_followup_context():
    recent = [{"role":"user","content":"Nifty 24000 PE September expiry"}]
    assert MarketAgent._inherit_option_from_context("current price ethra?", recent) == (24000, "PE", "NSE:NIFTY50-INDEX")
