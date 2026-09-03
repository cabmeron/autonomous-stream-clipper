import json
import logging
import os
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DatabaseRepository:
    """Embedded SQLite database repository for local clip metadata persistence."""

    def __init__(self, db_url: Optional[str] = None, sqlite_path: str = "./storage/clipper.db"):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self.is_postgres = False
        self._sqlite_path = os.path.abspath(sqlite_path)
        self._init_db()

    def _init_db(self):
        """Initializes database, defaulting to local SQLite."""
        if self.db_url and self.db_url.startswith("postgres"):
            try:
                import psycopg2
                conn = psycopg2.connect(self.db_url)
                conn.close()
                self.is_postgres = True
                logger.info("[Database] Connected to external PostgreSQL: %s", self.db_url.split("@")[-1])
                return
            except Exception as e:
                logger.warning("[Database] PostgreSQL connection failed (%s); falling back to local SQLite.", e)

        # Default: 100% Local SQLite
        os.makedirs(os.path.dirname(self._sqlite_path), exist_ok=True)
        with sqlite3.connect(self._sqlite_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS triage_clips (
                    id TEXT PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    video_url TEXT NOT NULL,
                    thumbnail_url TEXT,
                    duration_seconds REAL NOT NULL,
                    cut_start REAL NOT NULL,
                    cut_end REAL NOT NULL,
                    chat_velocity_peak REAL,
                    spike_ratio REAL,
                    ocr_pnl_delta REAL,
                    ocr_multiplier REAL,
                    heuristic_score INTEGER NOT NULL,
                    suggested_title TEXT NOT NULL,
                    suggested_caption TEXT NOT NULL,
                    transcript_json TEXT,
                    status TEXT DEFAULT 'pending_triage',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_triage_clips_status ON triage_clips(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_triage_clips_created ON triage_clips(created_at DESC);")
            conn.commit()
        logger.info("[Database] Local SQLite database ready at: %s", self._sqlite_path)

    def save_clip(self, clip_data: Dict[str, Any]) -> str:
        """Saves a new clip to the local database and returns its UUID."""
        clip_id = clip_data.get("id") or str(uuid.uuid4())
        transcript_str = (
            json.dumps(clip_data.get("transcript_json"))
            if isinstance(clip_data.get("transcript_json"), (list, dict))
            else clip_data.get("transcript_json", "[]")
        )

        params = (
            clip_id,
            clip_data.get("channel_name", "unknown"),
            clip_data.get("video_url", ""),
            clip_data.get("thumbnail_url"),
            float(clip_data.get("duration_seconds", 0.0)),
            float(clip_data.get("cut_start", 0.0)),
            float(clip_data.get("cut_end", 0.0)),
            float(clip_data.get("chat_velocity_peak") or 0.0),
            float(clip_data.get("spike_ratio") or 1.0),
            float(clip_data.get("ocr_pnl_delta") or 0.0),
            float(clip_data.get("ocr_multiplier") or 1.0),
            int(clip_data.get("heuristic_score", 7)),
            clip_data.get("suggested_title", "Stream Highlight"),
            clip_data.get("suggested_caption", ""),
            transcript_str,
            clip_data.get("status", "pending_triage"),
        )

        if self.is_postgres:
            try:
                import psycopg2
                with psycopg2.connect(self.db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO triage_clips (
                                id, channel_name, video_url, thumbnail_url,
                                duration_seconds, cut_start, cut_end,
                                chat_velocity_peak, spike_ratio, ocr_pnl_delta,
                                ocr_multiplier, heuristic_score, suggested_title,
                                suggested_caption, transcript_json, status
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, params)
                    conn.commit()
                return clip_id
            except Exception as err:
                logger.error("[Database] PostgreSQL write failed: %s", err)

        # SQLite write
        with sqlite3.connect(self._sqlite_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO triage_clips (
                    id, channel_name, video_url, thumbnail_url,
                    duration_seconds, cut_start, cut_end,
                    chat_velocity_peak, spike_ratio, ocr_pnl_delta,
                    ocr_multiplier, heuristic_score, suggested_title,
                    suggested_caption, transcript_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, params)
            conn.commit()
        logger.info("[Database] Saved clip %s locally in SQLite", clip_id)
        return clip_id

    def get_recent_clips(self, limit: int = 20, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves clips sorted by creation time."""
        clips = []
        query = "SELECT * FROM triage_clips"
        params: list = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self._sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(query, params)
            for row in cur.fetchall():
                item = dict(row)
                try:
                    item["transcript_json"] = json.loads(item["transcript_json"])
                except Exception:
                    pass
                clips.append(item)
        return clips

    def update_clip_status(self, clip_id: str, new_status: str) -> bool:
        """Updates the triage status of a clip (e.g. 'approved', 'rejected')."""
        with sqlite3.connect(self._sqlite_path) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE triage_clips SET status = ? WHERE id = ?", (new_status, clip_id))
            conn.commit()
            return cur.rowcount > 0
