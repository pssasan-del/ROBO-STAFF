from datetime import date
from delta_options_service import DeltaOptionsService
from market_agent import is_option_question, extract_strike, extract_expiry


def test_delta_symbol_parser():
    x=DeltaOptionsService.parse_symbol('C-BTC-77500-290826')
    assert x['side']=='CE' and x['underlying']=='BTC' and x['strike']==77500
    assert x['expiry']==date(2026,8,29)
    y=DeltaOptionsService.parse_symbol('P-ETH-2500-300826')
    assert y['side']=='PE' and y['strike']==2500


def test_option_intent_and_strike():
    assert is_option_question('bit coin 77500 ce and pe rate par')
    assert extract_strike('bit coin 77500 ce and pe rate par') == 77500
    assert extract_strike('ETH 2500 call put premium') == 2500


def test_explicit_expiry_parser():
    assert extract_expiry('BTC 77500 CE 30-08-2026') == '30-08-2026'
    assert extract_expiry('BTC 77500 CE 2026-08-30') == '30-08-2026'
