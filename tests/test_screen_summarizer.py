import asyncio
import os
import subprocess
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from services.heuristics.screen_summarizer import ScreenStateSummarizerService
from services.storage.db import DatabaseRepository


def test_screen_summarizer_format_payload():
    service = ScreenStateSummarizerService(
        gemini_api_key="fake-key",
        gemini_model="gemini-3.6-flash",
    )
    messages = [
        {"user": "alex", "text": "nice headshot!", "time": 100.0},
        {"user": "sam", "text": "CLUTCH GOD", "time": 102.0},
    ]
    frame_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"  # fake JPEG header

    payload = service.format_payload(channel="tarik", messages=messages, frame_bytes=frame_bytes)

    assert "system_instruction" in payload
    assert "contents" in payload
    parts = payload["contents"][0]["parts"]
    assert len(parts) == 2
    assert "inline_data" in parts[0]
    assert parts[0]["inline_data"]["mime_type"] == "image/jpeg"
    assert "nice headshot!" in parts[1]["text"]
    assert "CLUTCH GOD" in parts[1]["text"]


def test_screen_summarizer_extract_latest_frame(tmp_path):
    shm_base = tmp_path / "shm"
    channel_dir = shm_base / "marlon"
    channel_dir.mkdir(parents=True)

    # Generate synthetic 1-second TS video segment
    seg1 = str(channel_dir / "seg_00.ts")
    seg2 = str(channel_dir / "seg_01.ts")

    cmd1 = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=1",
        "-c:v", "libx264", "-y", seg1,
    ]
    subprocess.run(cmd1, check=True)

    cmd2 = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=1",
        "-c:v", "libx264", "-y", seg2,
    ]
    subprocess.run(cmd2, check=True)

    service = ScreenStateSummarizerService(shm_base=str(shm_base))
    frame_bytes = service.extract_latest_frame("marlon")

    assert frame_bytes is not None
    assert len(frame_bytes) > 500
    # Check JPEG SOI marker (0xFFD8)
    assert frame_bytes[:2] == b"\xff\xd8"


def test_screen_summarizer_gemini_multimodal_call():
    service = ScreenStateSummarizerService(
        gemini_api_key="fake-gemini-key",
        gemini_model="gemini-3.6-flash",
    )
    messages = [{"user": "chat1", "text": "WHAT A SHOT", "time": 100.0}]
    fake_frame = b"\xff\xd8\xff\xe0"

    mock_gemini_resp = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                "The streamer is in a 1v2 post-plant clutch situation on Haven A site. "
                                "Chat is flooding with hype emotes reacting to the operator flick shot. "
                                "Overall momentum is tense as the defuse timer ticks down."
                            )
                        }
                    ]
                }
            }
        ]
    }

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_gemini_resp)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp)))

    with patch("aiohttp.ClientSession", return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session))):
        result = asyncio.run(service.summarize_screen(channel="tarik", messages=messages, frame_bytes=fake_frame))

    assert result is not None
    assert result["channel_name"] == "tarik"
    assert result["has_image"] is True
    assert result["image_b64"].startswith("data:image/jpeg;base64,")
    assert "Haven A site" in result["summary"]


def test_screen_summarizer_no_key_fallback():
    service = ScreenStateSummarizerService(gemini_api_key="")
    messages = [{"user": "chat1", "text": "hello", "time": 100.0}]

    result = asyncio.run(service.summarize_screen(channel="shroud", messages=messages, frame_bytes=None))

    assert result is not None
    assert result["channel_name"] == "shroud"
    assert result["model_name"] == "no_key_fallback"
    assert "Configure GEMINI_API_KEY" in result["summary"]


def test_db_save_and_retrieve_screen_summary(tmp_path):
    db_file = str(tmp_path / "test_screen.db")
    db = DatabaseRepository(db_url=f"sqlite:///{db_file}")
    db._sqlite_path = db_file
    db._init_sqlite()

    record = {
        "id": "summary-12345",
        "channel_name": "marlon",
        "summary": "Streamer is opening case rewards on stream while chat spams gold.",
        "image_b64": "data:image/jpeg;base64,xyz",
        "message_count": 55,
        "model_name": "gemini-3.6-flash",
    }

    saved_id = db.save_screen_summary(record)
    assert saved_id == "summary-12345"

    retrieved = db.get_recent_screen_summaries(channel="marlon", limit=5)
    assert len(retrieved) == 1
    assert retrieved[0]["id"] == "summary-12345"
    assert retrieved[0]["channel_name"] == "marlon"
    assert retrieved[0]["message_count"] == 55
    assert "case rewards" in retrieved[0]["summary"]
