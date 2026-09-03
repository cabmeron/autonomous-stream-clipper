import json
import os
import subprocess
import tempfile
import pytest
from services.processor.render_engine import HardwareRenderEngine, format_ass_time
from services.processor.slicer import SegmentSlicer
from services.storage.db import DatabaseRepository


def test_format_ass_time():
    assert format_ass_time(0.0) == "0:00:00.00"
    assert format_ass_time(65.45) == "0:01:05.45"
    assert format_ass_time(3661.5) == "1:01:01.50"


def test_ass_subtitle_generation():
    words = [
        {"word": "HELLO", "start": 1.0, "end": 1.5},
        {"word": "WORLD", "start": 1.6, "end": 2.0},
        {"word": "TWITCH", "start": 2.1, "end": 2.5},
        {"word": "CLIPPER", "start": 2.6, "end": 3.0},
    ]
    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
        ass_path = f.name

    try:
        HardwareRenderEngine.generate_ass_subtitles(words, 0.5, 3.5, ass_path)
        assert os.path.exists(ass_path)
        with open(ass_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "[Script Info]" in content
        assert "PlayResX: 1080" in content
        assert "PlayResY: 1920" in content
        assert "Dialogue: 0," in content
        assert "HELLO WORLD TWITCH CLIPPER" in content
    finally:
        if os.path.exists(ass_path):
            os.remove(ass_path)


def test_db_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = DatabaseRepository()
        db._sqlite_path = db_path
        db._init_db()

        clip_data = {
            "channel_name": "testchannel",
            "video_url": "https://cdn.example.com/clip1.mp4",
            "thumbnail_url": "https://cdn.example.com/thumb1.jpg",
            "duration_seconds": 32.5,
            "cut_start": 5.0,
            "cut_end": 37.5,
            "chat_velocity_peak": 18.2,
            "spike_ratio": 4.5,
            "ocr_pnl_delta": 2500.0,
            "ocr_multiplier": 150.0,
            "heuristic_score": 9,
            "suggested_title": "CRAZY 150X HIT!",
            "suggested_caption": "Chat went crazy!",
            "transcript_json": [{"word": "INSANE", "start": 1.0, "end": 1.5}],
            "status": "pending_triage",
        }

        clip_id = db.save_clip(clip_data)
        assert clip_id is not None

        recent = db.get_recent_clips(limit=5)
        assert len(recent) == 1
        assert recent[0]["id"] == clip_id
        assert recent[0]["channel_name"] == "testchannel"
        assert recent[0]["heuristic_score"] == 9


def test_ffmpeg_vertical_render():
    """Generates a synthetic 16:9 test video and renders it to vertical 9:16 (1080x1920)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = os.path.join(tmpdir, "src.mp4")
        out_path = os.path.join(tmpdir, "out_9_16.mp4")

        # 1. Create a 3-second 1280x720 video with test audio
        cmd_synth = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=1280x720:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
            "-c:v", "libx264", "-c:a", "aac",
            "-y", src_path,
        ]
        subprocess.run(cmd_synth, check=True)
        assert os.path.exists(src_path)

        # 2. Render vertical 9:16
        words = [
            {"word": "UNREAL", "start": 0.5, "end": 1.0},
            {"word": "REACTION", "start": 1.1, "end": 1.8},
        ]
        HardwareRenderEngine.render_vertical(
            source_path=src_path,
            cut_start=0.2,
            cut_end=2.2,
            output_path=out_path,
            words=words,
            pnl_text="+100x WIN",
            enable_subs=True,
        )

        assert os.path.exists(out_path)

        # 3. Verify dimensions via ffprobe
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            out_path,
        ]
        res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, check=True, text=True)
        probe_data = json.loads(res.stdout)
        stream_info = probe_data["streams"][0]

        assert stream_info["width"] == 1080
        assert stream_info["height"] == 1920
