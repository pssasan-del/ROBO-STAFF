from pathlib import Path

def test_no_order_code():
    text='\n'.join(p.read_text(errors='ignore').lower() for p in Path('.').glob('*.py'))
    for forbidden in ['place_order','cancel_order','modify_order','x-authentication']:
        assert forbidden not in text
