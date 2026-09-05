from pathlib import Path
from app.services.journal import JournalStore

def test_journal_persists_and_filters(tmp_path: Path):
    j=JournalStore(str(tmp_path/'j.sqlite3'))
    a=j.add('execution','confirm',{'ok':True},'i1')
    j.add('order','cancel',{'ok':True},'o1')
    rows=j.list(10)
    assert len(rows)==2 and rows[0]['category']=='order'
    ex=j.list(10,'execution')
    assert len(ex)==1 and ex[0]['ref_id']=='i1' and ex[0]['payload']['ok'] is True
    assert a['id']>0
