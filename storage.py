import sqlite3
import json
import time
from typing import List, Optional, Dict, Any
from config import settings, logger
from models import StrategyDefinition, StrategyCondition, ScannerState, ScanMatch

class Storage:
    def __init__(self, db_path: str = settings.DATABASE_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # Strategies table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategies (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    universe TEXT NOT NULL,
                    logic TEXT NOT NULL,
                    conditions_json TEXT NOT NULL,
                    description TEXT,
                    created_at REAL NOT NULL
                )
            """)

            # Active scanners state table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scanners (
                    strategy_id TEXT PRIMARY KEY,
                    strategy_name TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    universe TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    last_scan_at REAL,
                    alert_count INTEGER DEFAULT 0,
                    total_scans INTEGER DEFAULT 0
                )
            """)

            # Alert history table for cooldown and audit
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    price REAL NOT NULL,
                    timestamp REAL NOT NULL,
                    alert_payload TEXT
                )
            """)

            # User conversation state (last mentioned symbol, context)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_context (
                    user_id TEXT PRIMARY KEY,
                    last_symbol TEXT,
                    last_strategy_id TEXT,
                    recent_messages_json TEXT,
                    updated_at REAL NOT NULL
                )
            """)
            conn.commit()

    # --- Strategy CRUD ---
    def save_strategy(self, strategy: StrategyDefinition) -> str:
        strat_id = strategy.id or f"strat_{int(time.time()*1000)}"
        conditions_json = json.dumps([c.model_dump() for c in strategy.conditions])
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO strategies (id, name, timeframe, universe, logic, conditions_json, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                strat_id,
                strategy.name,
                strategy.timeframe,
                strategy.universe,
                strategy.logic,
                conditions_json,
                strategy.description or "",
                strategy.created_at or time.time()
            ))
            conn.commit()
        return strat_id

    def get_strategy(self, strategy_id_or_name: str) -> Optional[StrategyDefinition]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM strategies 
                WHERE id = ? OR LOWER(name) = LOWER(?)
            """, (strategy_id_or_name, strategy_id_or_name))
            row = cursor.fetchone()
            if not row:
                return None
            
            raw_conditions = json.loads(row["conditions_json"])
            conditions = [StrategyCondition(**c) for c in raw_conditions]
            
            return StrategyDefinition(
                id=row["id"],
                name=row["name"],
                timeframe=row["timeframe"],
                universe=row["universe"],
                logic=row["logic"],
                conditions=conditions,
                description=row["description"],
                created_at=row["created_at"]
            )

    def list_strategies(self) -> List[StrategyDefinition]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM strategies ORDER BY created_at DESC")
            rows = cursor.fetchall()
            results = []
            for row in rows:
                raw_conditions = json.loads(row["conditions_json"])
                conditions = [StrategyCondition(**c) for c in raw_conditions]
                results.append(StrategyDefinition(
                    id=row["id"],
                    name=row["name"],
                    timeframe=row["timeframe"],
                    universe=row["universe"],
                    logic=row["logic"],
                    conditions=conditions,
                    description=row["description"],
                    created_at=row["created_at"]
                ))
            return results

    def delete_strategy(self, strategy_id_or_name: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM strategies 
                WHERE id = ? OR LOWER(name) = LOWER(?)
            """, (strategy_id_or_name, strategy_id_or_name))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted

    # --- Scanner State ---
    def update_scanner_state(self, state: ScannerState):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO scanners 
                (strategy_id, strategy_name, timeframe, universe, status, created_at, started_at, last_scan_at, alert_count, total_scans)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                state.strategy_id,
                state.strategy_name,
                state.timeframe,
                state.universe,
                state.status,
                state.created_at,
                state.started_at,
                state.last_scan_at,
                state.alert_count,
                state.total_scans
            ))
            conn.commit()

    def get_all_scanners(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scanners")
            return [dict(row) for row in cursor.fetchall()]

    # --- Alerts & Cooldown ---
    def record_alert(self, match: ScanMatch):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alert_history (strategy_id, symbol, signature, price, timestamp, alert_payload)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                match.strategy_id,
                match.symbol,
                match.signature,
                match.ltp,
                match.timestamp,
                json.dumps(match.model_dump())
            ))
            conn.commit()

    def is_alert_on_cooldown(self, signature: str, cooldown_minutes: int = settings.ALERT_COOLDOWN_MINUTES) -> bool:
        cooldown_seconds = cooldown_minutes * 60
        threshold_time = time.time() - cooldown_seconds
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp FROM alert_history
                WHERE signature = ? AND timestamp >= ?
                ORDER BY timestamp DESC LIMIT 1
            """, (signature, threshold_time))
            row = cursor.fetchone()
            return row is not None

    def get_recent_alerts(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM alert_history ORDER BY timestamp DESC LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # --- Context Memory ---
    def get_user_context(self, user_id: str) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_context WHERE user_id = ?", (str(user_id),))
            row = cursor.fetchone()
            if not row:
                return {"last_symbol": None, "last_strategy_id": None, "recent_messages": []}
            return {
                "last_symbol": row["last_symbol"],
                "last_strategy_id": row["last_strategy_id"],
                "recent_messages": json.loads(row["recent_messages_json"] or "[]")
            }

    def update_user_context(self, user_id: str, last_symbol: Optional[str] = None, last_strategy_id: Optional[str] = None, new_message: Optional[Dict[str, str]] = None):
        curr = self.get_user_context(user_id)
        sym = last_symbol or curr.get("last_symbol")
        strat = last_strategy_id or curr.get("last_strategy_id")
        msgs = curr.get("recent_messages", [])
        
        if new_message:
            msgs.append(new_message)
            # Keep last 8 messages for context
            msgs = msgs[-8:]

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO user_context (user_id, last_symbol, last_strategy_id, recent_messages_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (str(user_id), sym, strat, json.dumps(msgs), time.time()))
            conn.commit()

storage = Storage()
