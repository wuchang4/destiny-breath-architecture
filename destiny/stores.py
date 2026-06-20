"""Storage primitives used by the public runtime API."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


class JsonlAuditLog:
    """Append-only JSONL audit log for runtime events."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event_type: str, payload: dict[str, Any]) -> None:
        record = {
            "type": event_type,
            "timestamp": time.time(),
            "payload": _jsonable(payload),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


class FileRunStore:
    """Store normalized run results as JSON files."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, run_id: str, result: Any) -> Path:
        path = self.root / f"{run_id}.json"
        tmp_path = path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(_jsonable(result), handle, ensure_ascii=False, indent=2)
        tmp_path.replace(path)
        return path


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "value"):
        return value.value
    return value
