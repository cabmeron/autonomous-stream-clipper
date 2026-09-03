import json
import os
import tempfile
import pytest
from services.storage.local_storage import LocalStorageManager
from services.storage.db import DatabaseRepository
from services.processor.boundary_ai import BoundaryOptimizer


def test_local_storage_manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorageManager(storage_dir=tmpdir, public_prefix="/clips")
        dummy_video = os.path.join(tmpdir, "test.mp4")
        dummy_thumb = os.path.join(tmpdir, "test.jpg")
        with open(dummy_video, "w") as f:
            f.write("video")
        with open(dummy_thumb, "w") as f:
            f.write("thumb")

        v_url, t_url = storage.store_clip_bundle(dummy_video, dummy_thumb, clip_id="123")
        assert v_url == "/clips/123_test.mp4"
        assert t_url == "/clips/123_test.jpg"
        assert os.path.exists(os.path.join(tmpdir, "123_test.mp4"))
        assert os.path.exists(os.path.join(tmpdir, "123_test.jpg"))


def test_local_db_status_update():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "test.db")
        db = DatabaseRepository(sqlite_path=db_file)

        clip_id = db.save_clip({
            "id": "clip-999",
            "channel_name": "shroud",
            "video_url": "/clips/test.mp4",
            "duration_seconds": 35.0,
            "cut_start": 5.0,
            "cut_end": 40.0,
            "heuristic_score": 9,
            "suggested_title": "Local Highlight",
            "suggested_caption": "#local",
            "status": "pending_triage",
        })

        assert clip_id == "clip-999"
        clips = db.get_recent_clips(limit=5)
        assert len(clips) == 1
        assert clips[0]["status"] == "pending_triage"

        # Update status
        updated = db.update_clip_status("clip-999", "approved")
        assert updated is True

        clips_after = db.get_recent_clips(limit=5)
        assert clips_after[0]["status"] == "approved"


def test_local_boundary_optimizer_speech_pause():
    optimizer = BoundaryOptimizer()
    words = [
        {"word": "WE", "start": 18.0, "end": 18.5},
        {"word": "ARE", "start": 18.6, "end": 19.0},
        # Speech pause here (19.0 to 20.5 = 1.5s pause)
        {"word": "HOOK", "start": 20.5, "end": 21.0},
        {"word": "MOMENT", "start": 21.1, "end": 21.8},
        {"word": "EVENT", "start": 44.5, "end": 45.2},
        {"word": "REACTION", "start": 52.0, "end": 53.0},
        # Speech pause here
        {"word": "AFTERMATH", "start": 57.0, "end": 58.0},
    ]
    context = {
        "trigger_source": "audio_spike",
        "audio_delta": 16.5,
        "chat_instant": 28.0,
        "win_multiplier": 1.0,
    }

    res = optimizer.find_optimal_cut(words, context, total_duration=60.0)

    assert 20.0 <= (res["cut_end"] - res["cut_start"]) <= 58.0
    assert "STREAMER COMPLETELY LOST IT" in res["title"]
    assert res["score"] >= 7
