"""Journal em SQLite."""
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .clock import utc_now_iso


class Journal:
    """Journal thread-safe para entries e estado de perfis."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,
                check_same_thread=False,
            )
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entries (
                    profile       TEXT NOT NULL,
                    video_id      TEXT NOT NULL,
                    title         TEXT,
                    url           TEXT NOT NULL,
                    thumbnail     TEXT,
                    published_at  TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    PRIMARY KEY (profile, video_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS profile_state (
                    profile              TEXT PRIMARY KEY,
                    last_attempt_at      TEXT,
                    last_success_at      TEXT,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    last_error           TEXT
                )
            """)
            # Índice usado pela ordenação do feed.
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_entries_profile_published
                ON entries(profile, published_at DESC)
            """)

    def add_entries(self, profile: str, entries: list[dict[str, Any]]) -> int:
        """Insere entries novas. Retorna quantas foram realmente novas."""
        if not entries:
            return 0

        now = utc_now_iso()
        added = 0
        with self._get_conn() as conn:
            for entry in entries:
                cursor = conn.execute("""
                    INSERT OR IGNORE INTO entries (
                        profile, video_id, title, url, thumbnail,
                        published_at, first_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    profile,
                    entry["id"],
                    entry.get("title") or entry.get("description", ""),
                    entry["url"],
                    entry.get("thumbnail"),
                    entry["published_at"],
                    now,
                ))
                if cursor.rowcount > 0:
                    added += 1
        return added

    def get_feed_entries(self, profile: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT video_id, title, url, thumbnail, published_at, first_seen_at
                FROM entries
                WHERE profile = ?
                ORDER BY published_at DESC
                LIMIT ?
            """, (profile, limit))
            return [dict(row) for row in cursor.fetchall()]

    def update_profile_state(
        self,
        profile: str,
        *,
        success: bool,
        error: str | None = None,
    ):
        now = utc_now_iso()
        with self._get_conn() as conn:
            if success:
                conn.execute("""
                    INSERT OR REPLACE INTO profile_state (
                        profile, last_attempt_at, last_success_at,
                        consecutive_failures, last_error
                    ) VALUES (?, ?, ?, 0, NULL)
                """, (profile, now, now))
            else:
                conn.execute("""
                    INSERT INTO profile_state (
                        profile, last_attempt_at, last_success_at,
                        consecutive_failures, last_error
                    ) VALUES (?, ?, NULL, 1, ?)
                    ON CONFLICT(profile) DO UPDATE SET
                        last_attempt_at = excluded.last_attempt_at,
                        consecutive_failures = consecutive_failures + 1,
                        last_error = excluded.last_error
                """, (profile, now, error))

    def get_profile_state(self, profile: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM profile_state WHERE profile = ?",
                (profile,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_profile_states(self) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT
                    profile,
                    last_attempt_at,
                    last_success_at,
                    consecutive_failures,
                    last_error,
                    (SELECT COUNT(*) FROM entries WHERE entries.profile = profile_state.profile) as entries_total
                FROM profile_state
                ORDER BY profile
            """)
            return [dict(row) for row in cursor.fetchall()]

    def close(self):
        if hasattr(self._local, "conn"):
            self._local.conn.close()
            del self._local.conn
