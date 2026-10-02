import json, os, threading
from datetime import datetime, timedelta, timezone
from config import settings, logger

IST = timezone(timedelta(hours=5, minutes=30))
BASE_KEYS = (
    "total", "success", "failed", "unresolved", "stale", "invalidated",
    "buy_success", "buy_failed", "sell_success", "sell_failed",
    "ai_confirmed", "no_ai_confirmation", "sl_later_t1", "sl_later_t2",
)
EDGE_KEYS = (
    "edge_samples", "edge_gross_r_sum", "edge_net_r_sum",
    "edge_break_even_pct_sum", "edge_gross_cost_multiple_sum",
)
STATS_TABLE = "delta_signal_stats_v7_1_scalp_opportunity"
EPOCH = "FRESH_V7_1_SCALP_OPPORTUNITY_2026-10-02"


class PerformanceStore:
    """Fresh V7.1 option-outcome + 10-minute underlying-direction statistics."""
    def __init__(self, path=None):
        self.path = (path or settings.DELTA_STATS_PATH) + ".v7_1_scalp_opportunity"
        self.lock = threading.RLock(); self.data = {"days": {}}
        self.pg = False; self.conn = None
        self._init_persistent(); self._load(); self._prune()

    def _init_persistent(self):
        try:
            if settings.DATABASE_URL:
                import psycopg
                self.conn = psycopg.connect(settings.DATABASE_URL, autocommit=True); self.pg = True
                with self.conn.cursor() as cur:
                    cur.execute(f"""CREATE TABLE IF NOT EXISTS {STATS_TABLE}(day TEXT PRIMARY KEY,payload_json TEXT NOT NULL,updated_at TEXT NOT NULL)""")
                logger.info("[DELTA_STATS] Fresh V7.1 scalp-opportunity PostgreSQL persistence enabled")
        except Exception as e:
            logger.warning("[DELTA_STATS] PostgreSQL unavailable; file fallback: %s", e); self.conn=None; self.pg=False

    def _load(self):
        try:
            if self.pg:
                with self.conn.cursor() as cur:
                    cur.execute(f"SELECT day,payload_json FROM {STATS_TABLE} WHERE day >= %s",((datetime.now(IST).date()-timedelta(days=35)).isoformat(),))
                    self.data={"days":{str(day):json.loads(payload) for day,payload in cur.fetchall()}}
            elif os.path.exists(self.path):
                with open(self.path,"r",encoding="utf-8") as f:self.data=json.load(f)
        except Exception as e:
            logger.warning("[DELTA_STATS] load failed safely: %s",e);self.data={"days":{}}

    def _prune(self):
        days=self.data.setdefault("days",{});keep=sorted(days)[-35:];self.data["days"]={k:days[k] for k in keep}

    def _save_day(self,key):
        self._prune();payload=json.dumps(self.data["days"][key],separators=(",",":"))
        if self.pg:
            with self.conn.cursor() as cur:
                cur.execute(f"""INSERT INTO {STATS_TABLE}(day,payload_json,updated_at) VALUES(%s,%s,%s) ON CONFLICT(day) DO UPDATE SET payload_json=EXCLUDED.payload_json,updated_at=EXCLUDED.updated_at""",(key,payload,datetime.now(timezone.utc).isoformat()))
            return
        os.makedirs(os.path.dirname(self.path) or ".",exist_ok=True);tmp=self.path+".tmp"
        with open(tmp,"w",encoding="utf-8") as f:json.dump(self.data,f,separators=(",",":"))
        os.replace(tmp,self.path)

    @staticmethod
    def _ai_group(ai_status):
        s=(ai_status or "").upper()
        if s.startswith("CONFIRM"):return "confirm"
        if s.startswith("REJECT"):return "reject"
        if s.startswith("WAIT"):return "wait"
        return "no_ai"

    @staticmethod
    def _pair(container,key):
        return container.setdefault(key,{"signals":0,"success":0,"failed":0,"stale":0,"invalidated":0})

    @staticmethod
    def _dir_pair(container,key):
        return container.setdefault(key,{"total":0,"wins":0,"losses":0,"move_sum":0.0,"taker_sum":0.0,"rvol_sum":0.0})

    def _bucket(self,day=None):
        key=day or datetime.now(IST).date().isoformat();d=self.data.setdefault("days",{}).setdefault(key,{})
        for k in BASE_KEYS:d.setdefault(k,0)
        for k in EDGE_KEYS:d.setdefault(k,0.0)
        d.setdefault("assets",{});d.setdefault("ai",{});d.setdefault("actions",{})
        d.setdefault("direction_10m",{"total":0,"wins":0,"losses":0,"move_sum":0.0,"taker_sum":0.0,"rvol_sum":0.0,"assets":{},"sides":{}})
        d.setdefault("timing",{"sl_under_5m":0,"sl_5_15m":0,"sl_over_15m":0,"t1_under_5m":0,"t1_5_15m":0,"t1_over_15m":0})
        return key,d

    def new_signal(self,action,ai_status="",underlying="UNKNOWN"):
        with self.lock:
            key,d=self._bucket();d["total"]+=1;d["unresolved"]+=1
            d["ai_confirmed" if self._ai_group(ai_status)=="confirm" else "no_ai_confirmation"]+=1
            self._pair(d["actions"],action)["signals"]+=1;self._pair(d["assets"],underlying)["signals"]+=1;self._pair(d["ai"],self._ai_group(ai_status))["signals"]+=1
            self._save_day(key)

    def record_edge_estimate(self,gross_r,net_r,break_even_pct,gross_cost_multiple):
        with self.lock:
            key,d=self._bucket();d["edge_samples"]+=1;d["edge_gross_r_sum"]+=float(gross_r or 0);d["edge_net_r_sum"]+=float(net_r or 0);d["edge_break_even_pct_sum"]+=float(break_even_pct or 0);d["edge_gross_cost_multiple_sum"]+=float(gross_cost_multiple or 0);self._save_day(key)

    def record_direction_10m(self,underlying,direction,win,move_pct=0.0,taker_ratio=0.0,rvol=0.0):
        with self.lock:
            key,d=self._bucket();q=d["direction_10m"]
            q["total"]+=1;q["wins"]+=int(bool(win));q["losses"]+=int(not bool(win));q["move_sum"]+=float(move_pct or 0);q["taker_sum"]+=float(taker_ratio or 0);q["rvol_sum"]+=float(rvol or 0)
            for group,name in ((q["assets"],str(underlying)),(q["sides"],str(direction))):
                z=self._dir_pair(group,name);z["total"]+=1;z["wins"]+=int(bool(win));z["losses"]+=int(not bool(win));z["move_sum"]+=float(move_pct or 0);z["taker_sum"]+=float(taker_ratio or 0);z["rvol_sum"]+=float(rvol or 0)
            self._save_day(key)

    def resolve(self,action,success,underlying="UNKNOWN",ai_status="",elapsed_seconds=None):
        with self.lock:
            key,d=self._bucket();d["unresolved"]=max(0,d["unresolved"]-1);d["success" if success else "failed"]+=1
            side="buy" if "BUY" in action.upper() else "sell";d[f"{side}_{'success' if success else 'failed'}"]+=1;result="success" if success else "failed"
            self._pair(d["actions"],action)[result]+=1;self._pair(d["assets"],underlying)[result]+=1;self._pair(d["ai"],self._ai_group(ai_status))[result]+=1
            if elapsed_seconds is not None:
                prefix="t1" if success else "sl";mins=max(0,float(elapsed_seconds))/60;band="under_5m" if mins<5 else ("5_15m" if mins<=15 else "over_15m");d["timing"][f"{prefix}_{band}"]+=1
            self._save_day(key)

    def resolve_special(self,action,outcome,underlying="UNKNOWN",ai_status="",elapsed_seconds=None):
        outcome=str(outcome or "").lower()
        if outcome not in {"stale","invalidated"}:return
        with self.lock:
            key,d=self._bucket();d["unresolved"]=max(0,d["unresolved"]-1);d[outcome]+=1;self._pair(d["actions"],action)[outcome]+=1;self._pair(d["assets"],underlying)[outcome]+=1;self._pair(d["ai"],self._ai_group(ai_status))[outcome]+=1;self._save_day(key)

    def mark_sl_recovery(self,target="t1"):
        with self.lock:
            key,d=self._bucket();d["sl_later_t2" if str(target).lower()=="t2" else "sl_later_t1"]+=1;self._save_day(key)

    def signal_count_today(self,underlying):
        with self.lock:
            _,d=self._bucket();return int(self._pair(d["assets"],underlying).get("signals",0))

    def report(self,days=1):
        with self.lock:
            today=datetime.now(IST).date();keys=[(today-timedelta(days=i)).isoformat() for i in range(days)]
            out={k:0 for k in BASE_KEYS};out.update({k:0.0 for k in EDGE_KEYS});out.update({"assets":{},"ai":{},"actions":{},"timing":{},"epoch":EPOCH,"direction_10m":{"total":0,"wins":0,"losses":0,"move_sum":0.0,"taker_sum":0.0,"rvol_sum":0.0,"assets":{},"sides":{}}})
            for day in keys:
                src=self.data.get("days",{}).get(day,{})
                for k in BASE_KEYS:out[k]+=int(src.get(k,0))
                for k in EDGE_KEYS:out[k]+=float(src.get(k,0) or 0)
                for group in ("assets","ai","actions"):
                    for name,p in src.get(group,{}).items():
                        q=self._pair(out[group],name)
                        for metric in ("signals","success","failed","stale","invalidated"):q[metric]+=int(p.get(metric,0))
                for k,v in src.get("timing",{}).items():out["timing"][k]=out["timing"].get(k,0)+int(v)
                sd=src.get("direction_10m",{}) or {};od=out["direction_10m"]
                for k in ("total","wins","losses"):od[k]+=int(sd.get(k,0))
                for k in ("move_sum","taker_sum","rvol_sum"):od[k]+=float(sd.get(k,0) or 0)
                for group in ("assets","sides"):
                    for name,p in (sd.get(group,{}) or {}).items():
                        q=self._dir_pair(od[group],name)
                        for k in ("total","wins","losses"):q[k]+=int(p.get(k,0))
                        for k in ("move_sum","taker_sum","rvol_sum"):q[k]+=float(p.get(k,0) or 0)
            resolved=out["success"]+out["failed"];out["resolved"]=resolved;out["success_rate"]=round(out["success"]*100/resolved,1) if resolved else 0.0;out["loss_rate"]=round(out["failed"]*100/resolved,1) if resolved else 0.0;out["break_even_win_rate_1_85r"]=35.1
            d=out["direction_10m"];n=d["total"];d["win_rate"]=round(d["wins"]*100/n,1) if n else 0.0;d["avg_move_pct"]=round(d["move_sum"]/n,4) if n else 0.0;d["avg_taker_buy_ratio"]=round(d["taker_sum"]/n,3) if n else 0.0;d["avg_rvol"]=round(d["rvol_sum"]/n,2) if n else 0.0
            nedge=max(0.0,out["edge_samples"]);out["avg_est_gross_r"]=round(out["edge_gross_r_sum"]/nedge,2) if nedge else 0.0;out["avg_est_net_r"]=round(out["edge_net_r_sum"]/nedge,2) if nedge else 0.0;out["avg_est_break_even_pct"]=round(out["edge_break_even_pct_sum"]/nedge,2) if nedge else 0.0;out["avg_gross_cost_multiple"]=round(out["edge_gross_cost_multiple_sum"]/nedge,2) if nedge else 0.0
            return out


performance_store=PerformanceStore()
