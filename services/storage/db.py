import json
import logging
import os
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DatabaseRepository:
    """Manages clip records in local embedded SQLite."""

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.getenv("DATABASE_URL", "")
        self.use_sqlite = True
        self._sqlite_path = os.path.abspath("./storage/clipper.db")
        os.makedirs(os.path.dirname(self._sqlite_path), exist_ok=True)
        self._init_sqlite()

    def _get_connection(self) -> sqlite3.Connection:
        """Creates an SQLite connection with 5.0s busy timeout and WAL support."""
        return sqlite3.connect(self._sqlite_path, timeout=5.0)

    def _init_sqlite(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clips (
                    id TEXT PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    video_url TEXT NOT NULL,
                    thumbnail_url TEXT,
                    duration_seconds REAL NOT NULL,
                    cut_start REAL NOT NULL,
                    cut_end REAL NOT NULL,
                    chat_velocity_peak REAL DEFAULT 0.0,
                    spike_ratio REAL DEFAULT 1.0,
                    ocr_pnl_delta REAL DEFAULT 0.0,
                    ocr_multiplier REAL DEFAULT 1.0,
                    heuristic_score INTEGER NOT NULL,
                    suggested_title TEXT NOT NULL,
                    suggested_caption TEXT,
                    transcript_json TEXT,
                    status TEXT DEFAULT 'pending_triage',
                    folder_id TEXT,
                    folder_name TEXT,
                    folder_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clips_channel ON clips(channel_name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clips_created_at ON clips(created_at DESC);")

            # Dynamic migration for existing SQLite databases
            cursor.execute("PRAGMA table_info(clips);")
            existing_cols = {row[1] for row in cursor.fetchall()}
            if "folder_id" not in existing_cols:
                cursor.execute("ALTER TABLE clips ADD COLUMN folder_id TEXT;")
            if "folder_name" not in existing_cols:
                cursor.execute("ALTER TABLE clips ADD COLUMN folder_name TEXT;")
            if "folder_date" not in existing_cols:
                cursor.execute("ALTER TABLE clips ADD COLUMN folder_date TEXT;")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clips_folder ON clips(folder_id);")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_descriptors (
                    id TEXT PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    window_start REAL NOT NULL,
                    window_end REAL NOT NULL,
                    message_count INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_descriptors_channel ON chat_descriptors(channel_name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_descriptors_created ON chat_descriptors(created_at DESC);")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS screen_summaries (
                    id TEXT PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    image_b64 TEXT,
                    message_count INTEGER NOT NULL,
                    model_name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_summaries_channel ON screen_summaries(channel_name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_summaries_created ON screen_summaries(created_at DESC);")
            conn.commit()
        logger.info("[Database] Local SQLite database ready at: %s (WAL mode enabled)", self._sqlite_path)

    def save_clip(self, clip_data: dict) -> str:
        """Saves a new clip into the SQLite database."""
        clip_id = str(uuid.uuid4())
        words_json = (
            json.dumps(clip_data.get("transcript_json"))
            if isinstance(clip_data.get("transcript_json"), (list, dict))
            else clip_data.get("transcript_json", "[]")
        )

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO clips (
                    id, channel_name, video_url, thumbnail_url, duration_seconds,
                    cut_start, cut_end, chat_velocity_peak, spike_ratio,
                    ocr_pnl_delta, ocr_multiplier, heuristic_score,
                    suggested_title, suggested_caption, transcript_json, status,
                    folder_id, folder_name, folder_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                clip_id,
                clip_data.get("channel_name", "").lower(),
                clip_data.get("video_url", ""),
                clip_data.get("thumbnail_url", ""),
                clip_data.get("duration_seconds", 0.0),
                clip_data.get("cut_start", 0.0),
                clip_data.get("cut_end", 0.0),
                clip_data.get("chat_velocity_peak", 0.0),
                clip_data.get("spike_ratio", 1.0),
                clip_data.get("ocr_pnl_delta", 0.0),
                clip_data.get("ocr_multiplier", 1.0),
                clip_data.get("heuristic_score", 1),
                clip_data.get("suggested_title", "Stream Highlight"),
                clip_data.get("suggested_caption", ""),
                words_json,
                clip_data.get("status", "pending_triage"),
                clip_data.get("folder_id"),
                clip_data.get("folder_name"),
                clip_data.get("folder_date"),
            ))
            conn.commit()

        logger.info("[Database] Clip %s persisted locally (folder=%s).", clip_id, clip_data.get("folder_id"))
        return clip_id

    def get_clip(self, clip_id: str) -> Optional[Dict]:
        """Retrieves a single clip record by ID."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM clips WHERE id = ?", (clip_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_clip(self, clip_id: str) -> bool:
        """Deletes a clip record from the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
            conn.commit()
            return cursor.rowcount > 0

    def update_clip_status(self, clip_id: str, new_status: str) -> bool:
        """Updates the status of a clip (e.g. 'approved', 'rejected')."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE clips SET status = ? WHERE id = ?", (new_status, clip_id))
            conn.commit()
            return cursor.rowcount > 0

    def update_clip_folder(
        self,
        clip_id: str,
        folder_id: Optional[str],
        folder_name: Optional[str] = None,
        folder_date: Optional[str] = None,
    ) -> bool:
        """Updates the folder association of a clip."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE clips SET folder_id = ?, folder_name = ?, folder_date = ? WHERE id = ?",
                (folder_id, folder_name, folder_date, clip_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_clips_by_folder(self, folder_id: str, limit: int = 100) -> List[Dict]:
        """Retrieves clips belonging to a specific folder."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM clips WHERE folder_id = ? ORDER BY created_at DESC LIMIT ?",
                (folder_id, limit),
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_recent_clips(
        self,
        limit: int = 50,
        channel: Optional[str] = None,
        folder_id: Optional[str] = None,
    ) -> List[Dict]:
        """Retrieves recent clips, optionally filtered by channel name and/or folder ID."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = "SELECT * FROM clips"
            params: List[Any] = []
            conditions: List[str] = []

            if channel:
                conditions.append("LOWER(channel_name) = ?")
                params.append(channel.lower())
            if folder_id:
                conditions.append("folder_id = ?")
                params.append(folder_id)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def save_chat_descriptor(self, data: dict) -> str:
        """Persists a chat state description window into SQLite."""
        record_id = data.get("id") or str(uuid.uuid4())
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO chat_descriptors (
                    id, channel_name, window_start, window_end,
                    message_count, description, model_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                record_id,
                data.get("channel_name", "").lower(),
                data.get("window_start", 0.0),
                data.get("window_end", 0.0),
                data.get("message_count", 0),
                data.get("description", ""),
                data.get("model_name", "local_llm"),
            ))
            conn.commit()
        logger.info("[Database] Saved chat descriptor %s for #%s", record_id, data.get("channel_name"))
        return record_id

    def get_recent_descriptors(self, channel: Optional[str] = None, limit: int = 20) -> List[Dict]:
        """Retrieves recent chat state descriptions, optionally filtered by channel."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if channel:
                cursor.execute(
                    "SELECT * FROM chat_descriptors WHERE LOWER(channel_name) = ? ORDER BY created_at DESC LIMIT ?",
                    (channel.lower(), limit),
                )
            else:
                cursor.execute("SELECT * FROM chat_descriptors ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def save_screen_summary(self, data: dict) -> str:
        """Saves an on-demand screen state summary into SQLite."""
        record_id = data.get("id") or str(uuid.uuid4())
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO screen_summaries (
                    id, channel_name, summary, image_b64, message_count, model_name
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                record_id,
                data.get("channel_name", "").lower(),
                data.get("summary", ""),
                data.get("image_b64"),
                data.get("message_count", 0),
                data.get("model_name", "gemini-3.6-flash"),
            ))
            conn.commit()
        logger.info("[Database] Saved screen summary %s for #%s", record_id, data.get("channel_name"))
        return record_id

    def get_recent_screen_summaries(self, channel: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """Retrieves recent screen summaries, optionally filtered by channel."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if channel:
                cursor.execute(
                    "SELECT * FROM screen_summaries WHERE LOWER(channel_name) = ? ORDER BY created_at DESC LIMIT ?",
                    (channel.lower(), limit),
                )
            else:
                cursor.execute("SELECT * FROM screen_summaries ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def close(self):
        """Flushes SQLite WAL log and executes checkpoint to cleanly close the database."""
        try:
            with self._get_connection() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            logger.info("[Database] SQLite WAL checkpointed and closed cleanly.")
        except Exception as e:
            logger.debug("[Database] Error during WAL checkpoint: %s", e)

