import json, os, sqlite3, threading
from datetime import datetime, timezone
from config import settings, logger

class StrategyStore:
    def __init__(self):
        self.lock=threading.RLock(); self.pg=False; self.conn=None

    def init(self):
        if settings.DATABASE_URL:
            try:
                import psycopg
                self.conn=psycopg.connect(settings.DATABASE_URL,autocommit=True); self.pg=True
                logger.info('[DB] PostgreSQL connected; strategies are persistent')
            except Exception as e:
                logger.error('[DB] PostgreSQL unavailable: %s; falling back to SQLite',e)
        if not self.conn:
            path=settings.SQLITE_PATH; os.makedirs(os.path.dirname(path) or '.',exist_ok=True)
            self.conn=sqlite3.connect(path,check_same_thread=False); self.conn.row_factory=sqlite3.Row
            logger.warning('[DB] SQLite active at %s. On Render free ephemeral disk, set DATABASE_URL for persistence across redeploys.',path)
        self._execute('''CREATE TABLE IF NOT EXISTS strategies (
            id %s,
            owner_id BIGINT NOT NULL,
            name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            side TEXT NOT NULL,
            rules_json TEXT NOT NULL,
            source_text TEXT,
            active INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )''' % ('BIGSERIAL PRIMARY KEY' if self.pg else 'INTEGER PRIMARY KEY AUTOINCREMENT'))

    def _execute(self,sql,args=(),fetch=False):
        with self.lock:
            if self.pg:
                sql=sql.replace('?','%s')
                with self.conn.cursor() as cur:
                    cur.execute(sql,args)
                    if fetch:
                        cols=[d.name for d in cur.description] if cur.description else []
                        return [dict(zip(cols,r)) for r in cur.fetchall()]
                    return getattr(cur,'lastrowid',None)
            cur=self.conn.cursor(); cur.execute(sql,args); self.conn.commit()
            if fetch:return [dict(r) for r in cur.fetchall()]
            return cur.lastrowid

    def count(self,owner): return self._execute('SELECT COUNT(*) n FROM strategies WHERE owner_id=?',(owner,),True)[0]['n']
    def active_count(self,owner): return self._execute('SELECT COUNT(*) n FROM strategies WHERE owner_id=? AND active=1',(owner,),True)[0]['n']
    def list(self,owner): return self._execute('SELECT * FROM strategies WHERE owner_id=? ORDER BY id DESC',(owner,),True)
    def list_active(self): return self._execute('SELECT * FROM strategies WHERE active=1 ORDER BY id',(),True)
    def get(self,owner,sid):
        rows=self._execute('SELECT * FROM strategies WHERE owner_id=? AND id=?',(owner,sid),True); return rows[0] if rows else None
    def create(self,owner,data,source=''):
        if self.count(owner)>=settings.MAX_SAVED_STRATEGIES: raise ValueError(f'Maximum {settings.MAX_SAVED_STRATEGIES} saved strategies reached')
        now=datetime.now(timezone.utc).isoformat()
        args=(owner,data['name'],data['symbol'],data['timeframe'],data.get('side','SIGNAL'),json.dumps(data),source,now,now)
        if self.pg:
            rows=self._execute('INSERT INTO strategies(owner_id,name,symbol,timeframe,side,rules_json,source_text,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,0,?,?) RETURNING id',args,True)
            return rows[0]['id']
        return self._execute('INSERT INTO strategies(owner_id,name,symbol,timeframe,side,rules_json,source_text,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,0,?,?)',args)
    def replace(self,owner,sid,data,source=''):
        now=datetime.now(timezone.utc).isoformat(); self._execute('UPDATE strategies SET name=?,symbol=?,timeframe=?,side=?,rules_json=?,source_text=?,updated_at=? WHERE owner_id=? AND id=?',
            (data['name'],data['symbol'],data['timeframe'],data.get('side','SIGNAL'),json.dumps(data),source,now,owner,sid))
    def set_active(self,owner,sid,active):
        if active and self.active_count(owner)>=settings.MAX_ACTIVE_STRATEGIES: raise ValueError(f'Maximum {settings.MAX_ACTIVE_STRATEGIES} active scanners allowed')
        self._execute('UPDATE strategies SET active=?,updated_at=? WHERE owner_id=? AND id=?',(1 if active else 0,datetime.now(timezone.utc).isoformat(),owner,sid))
    def delete(self,owner,sid): self._execute('DELETE FROM strategies WHERE owner_id=? AND id=?',(owner,sid))

strategy_store=StrategyStore()
