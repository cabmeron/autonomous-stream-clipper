import os
import subprocess
import pytest
from services.processor.boundary_ai import BoundaryOptimizer
from services.processor.render_engine import HardwareRenderEngine
from services.storage.local_storage import LocalStorageManager
from services.storage.db import DatabaseRepository


def test_e2e_local_clipping_dag(tmp_path):
    # 1. Setup local storage & DB
    storage_dir = tmp_path / "storage"
    local_storage = LocalStorageManager(storage_dir=str(storage_dir), base_url="/clips")
    db = DatabaseRepository()

    # 2. Synthetic 60-second video
    raw_video = str(tmp_path / "candidate_slice.mp4")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=5",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=5",
        "-c:v", "libx264", "-c:a", "aac", "-y", raw_video,
    ]
    subprocess.run(cmd, check=True)

    # 3. Simulate boundary optimization
    optimizer = BoundaryOptimizer()
    context = {"win_multiplier": 200.0, "pnl_delta": 5000.0, "score": 9, "trigger_source": "ocr_multiplier"}
    cut_info = optimizer.find_optimal_cut(words=[], event_context=context, total_duration=5.0)

    # 4. Render 9:16 vertical video
    out_video = str(tmp_path / "clip_vertical.mp4")
    out_thumb = str(tmp_path / "thumb.jpg")
    HardwareRenderEngine.render_vertical(
        source_path=raw_video,
        cut_start=0.5,
        cut_end=3.5,
        output_path=out_video,
        pnl_text="200X MULTIPLIER",
        enable_subs=False,
    )
    HardwareRenderEngine.extract_thumbnail(out_video, out_thumb, offset_seconds=0.5)

    assert os.path.exists(out_video)
    assert os.path.exists(out_thumb)

    # 5. Local storage bundle
    v_url, t_url = local_storage.store_clip_bundle(out_video, out_thumb)
    assert v_url.startswith("/clips/")
    assert t_url.startswith("/clips/")

    # 6. Database record
    clip_id = db.save_clip({
        "channel_name": "testchannel",
        "video_url": v_url,
        "thumbnail_url": t_url,
        "duration_seconds": 3.0,
        "cut_start": 0.5,
        "cut_end": 3.5,
        "heuristic_score": 9,
        "suggested_title": cut_info["title"],
    })
    assert clip_id is not None
