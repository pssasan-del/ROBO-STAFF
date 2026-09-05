from __future__ import annotations
import json, sqlite3, threading, time
from pathlib import Path
from typing import Any

class JournalStore:
    def __init__(self, path: str = 'data/neo_signal_journal.sqlite3') -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init()

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _init(self):
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS journal_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                category TEXT NOT NULL,
                event TEXT NOT NULL,
                ref_id TEXT,
                payload TEXT NOT NULL
            )''')
            db.execute('CREATE INDEX IF NOT EXISTS idx_journal_ts ON journal_events(ts DESC)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_journal_ref ON journal_events(ref_id)')

    def add(self, category: str, event: str, payload: Any, ref_id: str | None = None) -> dict:
        ts = time.time()
        blob = json.dumps(payload, default=str, separators=(',', ':'))
        with self._lock, self._connect() as db:
            cur = db.execute('INSERT INTO journal_events(ts,category,event,ref_id,payload) VALUES(?,?,?,?,?)',
                             (ts, category, event, ref_id, blob))
            row_id = cur.lastrowid
        return {'id': row_id, 'ts': ts, 'category': category, 'event': event, 'ref_id': ref_id, 'payload': payload}

    def list(self, limit: int = 100, category: str | None = None) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        sql = 'SELECT * FROM journal_events'
        args: list[Any] = []
        if category:
            sql += ' WHERE category=?'; args.append(category)
        sql += ' ORDER BY id DESC LIMIT ?'; args.append(limit)
        with self._connect() as db:
            rows = db.execute(sql, args).fetchall()
        out=[]
        for r in rows:
            d=dict(r)
            try: d['payload']=json.loads(d['payload'])
            except Exception: pass
            out.append(d)
        return out

journal = JournalStore()
