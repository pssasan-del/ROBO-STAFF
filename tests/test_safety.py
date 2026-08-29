from pathlib import Path

def test_no_order_execution_methods():
    txt='\n'.join(p.read_text(errors='ignore') for p in Path('.').glob('*.py')).lower()
    for bad in ['place_order(', 'modify_order(', 'cancel_order(', 'square_off(', 'exit_position(']:
        assert bad not in txt

def test_no_mudrex_runtime_code():
    names={p.name for p in Path('.').glob('*.py')}
    assert 'mudrex_service.py' not in names
