from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


LOG_DIR = Path("logs")
JSONL_PATH = LOG_DIR / "events.jsonl"
SQLITE_PATH = LOG_DIR / "claims.sqlite"


def init_db() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(SQLITE_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    JSONL_PATH.touch(exist_ok=True)


def log_event(claim_id: str, event_type: str, payload: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "claim_id": claim_id,
        "event_type": event_type,
        "payload": payload,
        "created_at": now,
    }

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with JSONL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=True) + "\n")

    with sqlite3.connect(SQLITE_PATH) as conn:
        conn.execute(
            "INSERT INTO events (claim_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (claim_id, event_type, json.dumps(payload, ensure_ascii=True), now),
        )
        conn.commit()

