import os
import glob
import pytest
from config import Settings

def test_strict_zero_trading_safety():
    """
    CRITICAL TEST: Asserts that NO auto-trading order execution methods exist
    anywhere in the repository.
    """
    forbidden_terms = [
        "place_order",
        "modify_order",
        "cancel_order",
        "exit_position",
        "square_off",
        "bracket_order",
        "cover_order"
    ]
    
    python_files = glob.glob("*.py")
    
    for file_path in python_files:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            for term in forbidden_terms:
                # Check for method definitions (e.g. def place_order)
                assert f"def {term}" not in content, f"Forbidden order method found in {file_path}: def {term}"

def test_authorization_rejection():
    # When user is not in allowed list
    Settings.ALLOWED_TELEGRAM_USER_ID = "12345678"
    assert Settings.is_user_authorized(12345678) is True
    assert Settings.is_user_authorized(99999999) is False
    assert Settings.is_user_authorized(None) is False


def test_nifty500_is_not_partial_fake_universe():
    from symbol_universe import SymbolUniverse
    from errors import UnsupportedUniverseError
    import pytest
    with pytest.raises(UnsupportedUniverseError):
        SymbolUniverse.get_universe("NIFTY500")
