import json
import os
import subprocess
import tempfile
import pytest
from services.processor.render_engine import HardwareRenderEngine
from services.processor.boundary_ai import BoundaryOptimizer
from services.storage.local_storage import LocalStorageManager
from services.storage.db import DatabaseRepository


def test_e2e_local_clipping_dag():
    """End-to-end test of the entire local DAG pipeline from candidate video to 9:16 vertical clip, storage, and SQLite."""
    with tempfile.TemporaryDirectory() as tmpdir:
        candidate_mp4 = os.path.join(tmpdir, "candidate_raw.mp4")
        out_vertical = os.path.join(tmpdir, "clip_vertical.mp4")
        out_thumb = os.path.join(tmpdir, "thumb.jpg")
        clips_storage_dir = os.path.join(tmpdir, "clips")
        db_path = os.path.join(tmpdir, "test_e2e.db")

        # 1. Synthesize candidate 16:9 video (5 seconds)
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=duration=5:size=1920x1080:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
            "-c:v", "libx264", "-c:a", "aac",
            "-y", candidate_mp4,
        ]
        subprocess.run(cmd, check=True)

        # 2. Local word timestamps
        words = [
            {"word": "WATCH", "start": 0.5, "end": 0.9},
            {"word": "THIS", "start": 1.0, "end": 1.4},
            {"word": "INSANE", "start": 2.0, "end": 2.5},
            {"word": "HIT", "start": 2.6, "end": 3.0},
        ]

        # 3. Local boundary optimization
        optimizer = BoundaryOptimizer()
        cut_info = optimizer.find_optimal_cut(
            words=words,
            telemetry_context={"trigger_source": "ocr_multiplier", "win_multiplier": 500.0, "score": 9},
            total_duration=5.0,
        )
        assert "500X" in cut_info["title"]

        # 4. Render vertical 9:16 with badge and subtitles
        HardwareRenderEngine.render_vertical(
            source_path=candidate_mp4,
            cut_start=0.5,
            cut_end=3.5,
            output_path=out_vertical,
            words=words,
            pnl_text="500x MULTIPLIER",
            enable_subs=True,
        )
        assert os.path.exists(out_vertical)

        # 5. Extract poster thumbnail
        HardwareRenderEngine.extract_thumbnail(out_vertical, out_thumb, offset_seconds=0.5)
        assert os.path.exists(out_thumb)

        # 6. Store locally
        storage = LocalStorageManager(storage_dir=clips_storage_dir)
        v_url, t_url = storage.store_clip_bundle(out_vertical, out_thumb, clip_id="e2e-clip-1")

        assert v_url == "/clips/e2e-clip-1_clip_vertical.mp4"
        assert t_url == "/clips/e2e-clip-1_thumb.jpg"
        assert os.path.exists(os.path.join(clips_storage_dir, "e2e-clip-1_clip_vertical.mp4"))

        # 7. Persist to local SQLite
        db = DatabaseRepository(sqlite_path=db_path)
        clip_id = db.save_clip({
            "id": "e2e-clip-1",
            "channel_name": "shroud",
            "video_url": v_url,
            "thumbnail_url": t_url,
            "duration_seconds": 3.0,
            "cut_start": 0.5,
            "cut_end": 3.5,
            "chat_velocity_peak": 25.0,
            "spike_ratio": 5.2,
            "ocr_pnl_delta": 15000.0,
            "ocr_multiplier": 500.0,
            "heuristic_score": 9,
            "suggested_title": cut_info["title"],
            "suggested_caption": cut_info["caption"],
            "transcript_json": words,
            "status": "pending_triage",
        })

        recent = db.get_recent_clips(limit=5)
        assert len(recent) == 1
        assert recent[0]["id"] == "e2e-clip-1"
        assert recent[0]["status"] == "pending_triage"

        # 8. Verify video resolution is 1080x1920
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            os.path.join(clips_storage_dir, "e2e-clip-1_clip_vertical.mp4"),
        ]
        probe_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, text=True, check=True)
        probe_data = json.loads(probe_res.stdout)
        assert probe_data["streams"][0]["width"] == 1080
        assert probe_data["streams"][0]["height"] == 1920
