import json, os, threading
from datetime import datetime, timedelta, timezone
from config import settings, logger

IST = timezone(timedelta(hours=5, minutes=30))
EPOCH = "TBR_V1_ADAPTIVE_FRESH_2026-10-06"
TABLE = "tbr_v1_signal_stats_adaptive_20261006"


class TBRStats:
    def __init__(self):
        self.lock = threading.RLock()
        self.path = settings.DELTA_STATS_PATH + ".tbr_v1_adaptive_20261006"
        self.data = {"days": {}}
        self.pg = False
        self.conn = None
        self._init_persistent()
        self._load()

    def _init_persistent(self):
        try:
            if settings.DATABASE_URL:
                import psycopg
                self.conn = psycopg.connect(settings.DATABASE_URL, autocommit=True)
                self.pg = True
                with self.conn.cursor() as cur:
                    cur.execute(f"CREATE TABLE IF NOT EXISTS {TABLE}(day TEXT PRIMARY KEY,payload_json TEXT NOT NULL,updated_at TEXT NOT NULL)")
        except Exception as exc:
            logger.warning("[TBR_STATS] PostgreSQL unavailable: %s", exc)
            self.conn = None
            self.pg = False

    def _load(self):
        try:
            if self.pg:
                start = (datetime.now(IST).date() - timedelta(days=35)).isoformat()
                with self.conn.cursor() as cur:
                    cur.execute(f"SELECT day,payload_json FROM {TABLE} WHERE day >= %s", (start,))
                    self.data = {"days": {str(day): json.loads(payload) for day, payload in cur.fetchall()}}
            elif os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
        except Exception as exc:
            logger.warning("[TBR_STATS] load failed: %s", exc)
            self.data = {"days": {}}

    def _bucket(self, day=None):
        key = day or datetime.now(IST).date().isoformat()
        d = self.data.setdefault("days", {}).setdefault(key, {})
        for k in ("signals","resolved","wins","losses","t1_hits","t2_hits","sl_exits","time_exits","cancelled","expired"):
            d.setdefault(k, 0)
        for k in ("net_r_sum","gross_r_sum","cost_r_sum"):
            d.setdefault(k, 0.0)
        d.setdefault("assets", {})
        d.setdefault("directions", {})
        return key, d

    @staticmethod
    def _pair(container, key):
        return container.setdefault(key, {"signals":0,"resolved":0,"wins":0,"losses":0,"t1_hits":0,"sl_exits":0,"time_exits":0,"net_r_sum":0.0})

    def _save(self, key):
        days = self.data.setdefault("days", {})
        keep = sorted(days)[-35:]
        self.data["days"] = {k: days[k] for k in keep}
        payload = json.dumps(self.data["days"][key], separators=(",", ":"))
        if self.pg:
            with self.conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {TABLE}(day,payload_json,updated_at) VALUES(%s,%s,%s) ON CONFLICT(day) DO UPDATE SET payload_json=EXCLUDED.payload_json,updated_at=EXCLUDED.updated_at",
                    (key, payload, datetime.now(timezone.utc).isoformat()),
                )
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, separators=(",", ":"))
        os.replace(tmp, self.path)

    def new_signal(self, symbol, direction):
        with self.lock:
            key, d = self._bucket()
            d["signals"] += 1
            self._pair(d["assets"], symbol)["signals"] += 1
            self._pair(d["directions"], direction)["signals"] += 1
            self._save(key)

    def mark_t1(self, symbol, direction):
        with self.lock:
            key, d = self._bucket()
            d["t1_hits"] += 1
            self._pair(d["assets"], symbol)["t1_hits"] += 1
            self._pair(d["directions"], direction)["t1_hits"] += 1
            self._save(key)

    def mark_t2(self):
        with self.lock:
            key, d = self._bucket(); d["t2_hits"] += 1; self._save(key)

    def resolve(self, symbol, direction, outcome, net_r, gross_r=0.0, cost_r=0.0):
        with self.lock:
            key, d = self._bucket()
            win = float(net_r) > 0
            d["resolved"] += 1
            d["wins" if win else "losses"] += 1
            d["net_r_sum"] += float(net_r)
            d["gross_r_sum"] += float(gross_r)
            d["cost_r_sum"] += float(cost_r)
            if outcome == "SL": d["sl_exits"] += 1
            if outcome == "TIME": d["time_exits"] += 1
            for group, name in ((d["assets"], symbol), (d["directions"], direction)):
                p = self._pair(group, name)
                p["resolved"] += 1; p["wins" if win else "losses"] += 1; p["net_r_sum"] += float(net_r)
                if outcome == "SL": p["sl_exits"] += 1
                if outcome == "TIME": p["time_exits"] += 1
            self._save(key)

    def record_state(self, kind):
        if kind not in {"cancelled","expired"}: return
        with self.lock:
            key, d = self._bucket(); d[kind] += 1; self._save(key)

    def daily_loss_limit_hit(self):
        with self.lock:
            _, d = self._bucket()
            # Each full -1R paper loss is 0.25% of equity by strategy design.
            realised_equity_pct = float(d.get("net_r_sum", 0.0)) * 0.25
            return realised_equity_pct <= -1.0, realised_equity_pct

    def report(self, days=1):
        with self.lock:
            today = datetime.now(IST).date()
            out = {"epoch":EPOCH,"signals":0,"resolved":0,"wins":0,"losses":0,"t1_hits":0,"t2_hits":0,"sl_exits":0,"time_exits":0,"cancelled":0,"expired":0,"net_r_sum":0.0,"gross_r_sum":0.0,"cost_r_sum":0.0,"assets":{},"directions":{}}
            for i in range(days):
                src = self.data.get("days", {}).get((today - timedelta(days=i)).isoformat(), {})
                for k in ("signals","resolved","wins","losses","t1_hits","t2_hits","sl_exits","time_exits","cancelled","expired"):
                    out[k] += int(src.get(k,0))
                for k in ("net_r_sum","gross_r_sum","cost_r_sum"):
                    out[k] += float(src.get(k,0.0))
                for g in ("assets","directions"):
                    for name, p in (src.get(g,{}) or {}).items():
                        q = self._pair(out[g], name)
                        for k in ("signals","resolved","wins","losses","t1_hits","sl_exits","time_exits"):
                            q[k] += int(p.get(k,0))
                        q["net_r_sum"] += float(p.get("net_r_sum",0.0))
            n = out["resolved"]
            out["success_rate"] = round(100*out["wins"]/n,1) if n else 0.0
            out["t1_hit_rate"] = round(100*out["t1_hits"]/n,1) if n else 0.0
            out["avg_net_r"] = round(out["net_r_sum"]/n,2) if n else 0.0
            out["realised_equity_pct"] = round(out["net_r_sum"]*0.25,3)
            return out


tbr_stats = TBRStats()
