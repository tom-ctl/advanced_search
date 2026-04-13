import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import Ad


class Database:
    def __init__(self, db_path: str = "car_alerts.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_ads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    storage_id TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    ad_id TEXT NOT NULL,
                    title TEXT,
                    price INTEGER,
                    mileage INTEGER,
                    label TEXT,
                    score REAL,
                    notified_at TEXT
                )
                """
            )
            conn.commit()

    def has_seen(self, storage_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_ads WHERE storage_id = ? LIMIT 1",
                (storage_id,),
            ).fetchone()
            return row is not None

    def mark_seen(self, ad: Ad, storage_id: str) -> None:
        timestamp = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seen_ads (storage_id, source, ad_id, title, price, mileage, label, score, notified_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    storage_id,
                    ad.source,
                    ad.ad_id,
                    ad.title,
                    ad.price,
                    ad.mileage,
                    ad.label,
                    ad.score,
                    timestamp,
                ),
            )
            conn.commit()
