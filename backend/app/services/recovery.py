from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class RecoveryStore:
    def __init__(self, path: str = "data/recovery_state.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state: dict[str, Any] = {"core_indices": [], "verified_instruments": {}, "updated_at": None}
        self.load()

    def load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.state.update(raw)
            except Exception:
                pass
        return self.snapshot()

    def save(self) -> dict[str, Any]:
        self.state["updated_at"] = time.time()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.path)
        return self.snapshot()

    def set_core_indices(self, items: list[dict[str, Any]]) -> None:
        self.state["core_indices"] = items
        self.save()

    def remember_instrument(self, key: str, row: dict[str, Any]) -> None:
        self.state.setdefault("verified_instruments", {})[key] = row
        self.save()

    def snapshot(self) -> dict[str, Any]:
        return {
            "core_indices": list(self.state.get("core_indices", [])),
            "verified_instruments": dict(self.state.get("verified_instruments", {})),
            "updated_at": self.state.get("updated_at"),
        }


recovery_store = RecoveryStore()
