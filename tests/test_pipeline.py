import os
import subprocess
from services.processor.render_engine import HardwareRenderEngine
from services.storage.db import DatabaseRepository


def test_format_ass_time():
    assert HardwareRenderEngine.format_ass_time(0.0) == "0:00:00.00"
    assert HardwareRenderEngine.format_ass_time(65.5) == "0:01:05.50"
    assert HardwareRenderEngine.format_ass_time(3661.25) == "1:01:01.25"


def test_ass_subtitle_generation(tmp_path):
    out_ass = str(tmp_path / "subs.ass")
    words = [
        {"word": "Hello", "start": 1.0, "end": 1.5},
        {"word": "world!", "start": 1.6, "end": 2.0},
    ]
    HardwareRenderEngine.generate_ass_subtitles(words, cut_start=0.5, output_path=out_ass)
    assert os.path.exists(out_ass)
    content = open(out_ass).read()
    assert "Karaoke" in content
    assert "HELLO WORLD!" in content


def test_db_persistence():
    db = DatabaseRepository()
    clip_id = db.save_clip({
        "channel_name": "tarik",
        "video_url": "/clips/tarik_clip.mp4",
        "duration_seconds": 25.0,
        "cut_start": 5.0,
        "cut_end": 30.0,
        "heuristic_score": 9,
        "suggested_title": "Huge Clutch",
    })
    assert clip_id is not None
    recent = db.get_recent_clips(limit=1)
    assert len(recent) > 0


def test_ffmpeg_vertical_render(tmp_path):
    source_mp4 = str(tmp_path / "source.mp4")
    out_mp4 = str(tmp_path / "out_916.mp4")

    # Generate synthetic 1920x1080 3-second test video
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=3",
        "-c:v", "libx264", "-c:a", "aac", "-y", source_mp4,
    ]
    subprocess.run(cmd, check=True)

    success = HardwareRenderEngine.render_vertical(
        source_path=source_mp4,
        cut_start=0.5,
        cut_end=2.5,
        output_path=out_mp4,
        pnl_text="TEST BADGE",
        enable_subs=False,
    )
    assert success is True
    assert os.path.exists(out_mp4)


def test_render_clean_raw_video(tmp_path):
    source_mp4 = str(tmp_path / "raw_source.mp4")
    out_mp4 = str(tmp_path / "clean_raw_clip.mp4")

    # Generate synthetic 1920x1080 3-second test video
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=3",
        "-c:v", "libx264", "-c:a", "aac", "-y", source_mp4,
    ]
    subprocess.run(cmd, check=True)

    # Render 100% clean raw video
    success = HardwareRenderEngine.render_clip(
        source_path=source_mp4,
        cut_start=0.5,
        cut_end=2.5,
        output_path=out_mp4,
        words=None,
        pnl_text="",
        enable_subs=False,
        crop_vertical=False,
    )
    assert success is True
    assert os.path.exists(out_mp4)
    assert os.path.getsize(out_mp4) > 0


def test_segment_slicer_extract_window(tmp_path):
    from services.processor.slicer import SegmentSlicer

    shm_base = tmp_path / "shm"
    stream_dir = shm_base / "streamer"
    stream_dir.mkdir(parents=True)
    out_dir = tmp_path / "candidates"

    # Create 3 synthetic TS segments
    for i in range(3):
        ts_path = str(stream_dir / f"seg_{i:03d}.ts")
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=1",
            "-c:v", "libx264", "-c:a", "aac", "-y", ts_path,
        ]
        subprocess.run(cmd, check=True)

    result_file = SegmentSlicer.extract_window(
        channel="streamer",
        duration_seconds=20,
        output_dir=str(out_dir),
        shm_base=str(shm_base),
    )

    assert result_file is not None
    assert os.path.exists(result_file)
    assert os.path.getsize(result_file) > 0

