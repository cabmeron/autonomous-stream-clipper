import json
import logging
import os
import sqlite3
import uuid
from typing import Dict, List, Optional

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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clips_channel ON clips(channel_name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clips_created_at ON clips(created_at DESC);")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_sentiments (
                    id TEXT PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    window_start REAL NOT NULL,
                    window_end REAL NOT NULL,
                    timestamp_str TEXT NOT NULL,
                    vibe TEXT NOT NULL,
                    emoji TEXT NOT NULL,
                    descriptor TEXT NOT NULL,
                    score REAL DEFAULT 0.0,
                    velocity REAL DEFAULT 0.0,
                    message_count INTEGER DEFAULT 0,
                    top_emotes TEXT DEFAULT '[]',
                    color TEXT DEFAULT '#64748b',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sentiments_channel ON chat_sentiments(channel_name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sentiments_created_at ON chat_sentiments(created_at DESC);")
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
                    suggested_title, suggested_caption, transcript_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ))
            conn.commit()

        logger.info("[Database] Clip %s persisted locally.", clip_id)
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

    def get_recent_clips(self, limit: int = 50, channel: Optional[str] = None) -> List[Dict]:
        """Retrieves recent clips, optionally filtered by channel name."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if channel:
                cursor.execute(
                    "SELECT * FROM clips WHERE LOWER(channel_name) = ? ORDER BY created_at DESC LIMIT ?",
                    (channel.lower(), limit),
                )
            else:
                cursor.execute("SELECT * FROM clips ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def save_chat_sentiment(self, sentiment_data: dict) -> str:
        """Persists a 60-second chat sentiment record."""
        sentiment_id = sentiment_data.get("id") or str(uuid.uuid4())
        emotes_json = (
            json.dumps(sentiment_data.get("top_emotes"))
            if isinstance(sentiment_data.get("top_emotes"), (list, dict))
            else sentiment_data.get("top_emotes", "[]")
        )
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO chat_sentiments (
                    id, channel_name, window_start, window_end, timestamp_str,
                    vibe, emoji, descriptor, score, velocity, message_count,
                    top_emotes, color
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sentiment_id,
                sentiment_data.get("channel", "").lower(),
                sentiment_data.get("window_start", 0.0),
                sentiment_data.get("window_end", 0.0),
                sentiment_data.get("timestamp_str", ""),
                sentiment_data.get("vibe", "CHATTING"),
                sentiment_data.get("emoji", "💬"),
                sentiment_data.get("descriptor", ""),
                sentiment_data.get("score", 0.0),
                sentiment_data.get("velocity", 0.0),
                sentiment_data.get("message_count", 0),
                emotes_json,
                sentiment_data.get("color", "#64748b"),
            ))
            conn.commit()
        return sentiment_id

    def get_recent_sentiments(self, limit: int = 50, channel: Optional[str] = None) -> List[Dict]:
        """Retrieves recent chat sentiment descriptors, optionally filtered by channel."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if channel:
                cursor.execute(
                    "SELECT * FROM chat_sentiments WHERE LOWER(channel_name) = ? ORDER BY window_end DESC LIMIT ?",
                    (channel.lower(), limit),
                )
            else:
                cursor.execute("SELECT * FROM chat_sentiments ORDER BY window_end DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                if isinstance(d.get("top_emotes"), str):
                    try:
                        d["top_emotes"] = json.loads(d["top_emotes"])
                    except Exception:
                        d["top_emotes"] = []
                results.append(d)
            return results
