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
                    first_notified_at TEXT,
                    last_notified_at TEXT,
                    last_seen_at TEXT
                )
                """
            )
            existing_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(seen_ads)").fetchall()
            }
            for column_name, column_type in [
                ("first_notified_at", "TEXT"),
                ("last_notified_at", "TEXT"),
                ("last_seen_at", "TEXT"),
            ]:
                if column_name not in existing_columns:
                    conn.execute(f"ALTER TABLE seen_ads ADD COLUMN {column_name} {column_type}")

            if "notified_at" in existing_columns:
                conn.execute(
                    """
                    UPDATE seen_ads
                    SET first_notified_at = COALESCE(first_notified_at, notified_at),
                        last_notified_at = COALESCE(last_notified_at, notified_at),
                        last_seen_at = COALESCE(last_seen_at, notified_at)
                    """
                )
            conn.commit()

    def get_entry(self, storage_id: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT storage_id, source, ad_id, title, price, mileage, label, score,
                       first_notified_at, last_notified_at, last_seen_at
                FROM seen_ads
                WHERE storage_id = ?
                LIMIT 1
                """,
                (storage_id,),
            ).fetchone()

    def should_notify(self, ad: Ad, storage_id: str) -> tuple[bool, str]:
        existing = self.get_entry(storage_id)
        if existing is None:
            return True, "new"

        previous_price = existing["price"]
        if previous_price != ad.price:
            return True, "price_changed"

        return False, "already_sent_same_price"

    def upsert_ad(self, ad: Ad, storage_id: str, notified: bool) -> None:
        timestamp = datetime.utcnow().isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT first_notified_at FROM seen_ads WHERE storage_id = ? LIMIT 1",
                (storage_id,),
            ).fetchone()
            first_notified_at = existing["first_notified_at"] if existing else None
            if notified and not first_notified_at:
                first_notified_at = timestamp

            last_notified_at = timestamp if notified else None
            conn.execute(
                """
                INSERT INTO seen_ads (
                    storage_id, source, ad_id, title, price, mileage, label, score,
                    first_notified_at, last_notified_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(storage_id) DO UPDATE SET
                    source = excluded.source,
                    ad_id = excluded.ad_id,
                    title = excluded.title,
                    price = excluded.price,
                    mileage = excluded.mileage,
                    label = excluded.label,
                    score = excluded.score,
                    first_notified_at = COALESCE(seen_ads.first_notified_at, excluded.first_notified_at),
                    last_notified_at = COALESCE(excluded.last_notified_at, seen_ads.last_notified_at),
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    storage_id,
                    ad.source,
                    ad.ad_id,
                    ad.title,
                    ad.price,
                    ad.mileage,
                    ad.label,
                    ad.score,
                    first_notified_at,
                    last_notified_at,
                    timestamp,
                ),
            )
            conn.commit()
