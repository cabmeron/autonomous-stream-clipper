import os
from services.storage.local_storage import LocalStorageManager
from services.storage.db import DatabaseRepository
from services.processor.boundary_ai import BoundaryOptimizer


def test_local_storage_manager_and_deletion(tmp_path):
    storage_dir = tmp_path / "clips"
    mgr = LocalStorageManager(storage_dir=str(storage_dir), base_url="/clips")

    video = tmp_path / "test.mp4"
    video.write_text("video content")
    thumb = tmp_path / "test.jpg"
    thumb.write_text("thumb content")

    v_url, t_url = mgr.store_clip_bundle(str(video), str(thumb))
    assert v_url == "/clips/test.mp4"
    assert t_url == "/clips/test.jpg"
    assert os.path.exists(os.path.join(str(storage_dir), "test.mp4"))
    assert os.path.exists(os.path.join(str(storage_dir), "test.jpg"))

    # Test file deletion
    deleted = mgr.delete_clip_bundle(v_url, t_url)
    assert deleted is True
    assert not os.path.exists(os.path.join(str(storage_dir), "test.mp4"))
    assert not os.path.exists(os.path.join(str(storage_dir), "test.jpg"))


def test_local_db_per_stream_clips_and_deletion():
    db = DatabaseRepository()

    # Create clips for two separate streams
    c1 = db.save_clip({
        "channel_name": "zarbex",
        "video_url": "/clips/zarbex_1.mp4",
        "duration_seconds": 30.0,
        "cut_start": 0.0,
        "cut_end": 30.0,
        "heuristic_score": 8,
        "suggested_title": "Zarbex Moment",
    })
    c2 = db.save_clip({
        "channel_name": "tarik",
        "video_url": "/clips/tarik_1.mp4",
        "duration_seconds": 25.0,
        "cut_start": 0.0,
        "cut_end": 25.0,
        "heuristic_score": 9,
        "suggested_title": "Tarik Ace",
    })

    # Query filtered by stream
    zarbex_clips = db.get_recent_clips(channel="zarbex")
    tarik_clips = db.get_recent_clips(channel="tarik")

    assert any(c["id"] == c1 for c in zarbex_clips)
    assert not any(c["id"] == c2 for c in zarbex_clips)

    assert any(c["id"] == c2 for c in tarik_clips)
    assert not any(c["id"] == c1 for c in tarik_clips)

    # Test clip deletion
    assert db.get_clip(c1) is not None
    deleted = db.delete_clip(c1)
    assert deleted is True
    assert db.get_clip(c1) is None


def test_local_boundary_optimizer_speech_pause():
    opt = BoundaryOptimizer()
    words = [
        {"word": "Let's", "start": 10.0, "end": 10.4},
        {"word": "go!", "start": 10.5, "end": 11.0},
        {"word": "Wait", "start": 18.0, "end": 18.4},
        {"word": "for", "start": 18.4, "end": 18.6},
        {"word": "it", "start": 18.6, "end": 19.0},
        {"word": "OH", "start": 44.5, "end": 45.0},
        {"word": "MY", "start": 45.0, "end": 45.3},
        {"word": "GOD", "start": 45.3, "end": 46.0},
        {"word": "GG", "start": 48.0, "end": 48.5},
    ]
    context = {"win_multiplier": 50.0, "pnl_delta": 500.0, "score": 7, "trigger_source": "chat"}
    res = opt.find_optimal_cut(words, context, total_duration=60.0)

    assert 20.0 <= (res["cut_end"] - res["cut_start"]) <= 58.0
