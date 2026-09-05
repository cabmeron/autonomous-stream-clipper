import asyncio
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from services.heuristics.chat_descriptor import LocalChatDescriptorService
from services.ingest.twitch_irc import TwitchChatVelocityEngine, parse_irc_privmsg
from services.storage.db import DatabaseRepository


@pytest.mark.asyncio
async def test_chat_descriptor_quiet_zero_messages():
    service = LocalChatDescriptorService(interval_seconds=60)
    result = await service.describe_chat_window([], channel="marlon")

    assert result is not None
    assert result["channel_name"] == "marlon"
    assert result["message_count"] == 0
    assert result["model_name"] == "rule_based_fallback"
    assert "quiet" in result["description"].lower()


@pytest.mark.asyncio
async def test_chat_descriptor_quiet_few_messages():
    service = LocalChatDescriptorService(interval_seconds=60)
    messages = [
        {"user": "viewer1", "text": "hey everyone", "time": 100.0},
        {"user": "viewer2", "text": "hello", "time": 105.0},
    ]
    result = await service.describe_chat_window(messages, channel="marlon")

    assert result is not None
    assert result["message_count"] == 2
    assert result["model_name"] == "rule_based_fallback"
    assert "@viewer1" in result["description"]
    assert "@viewer2" in result["description"]


def test_chat_descriptor_format_prompts():
    service = LocalChatDescriptorService(interval_seconds=60)
    messages = [
        {"user": "alex", "text": "clutch or kick", "time": 100.0},
        {"user": "sam", "text": "OMG HE DID IT Pog", "time": 102.0},
    ]
    system_inst, user_content = service.format_prompts(messages, channel="tarik", interval=60)

    assert "Twitch chat" in system_inst
    assert "2 to 3 natural sentences" in system_inst
    assert "Stream: #tarik" in user_content
    assert "- alex: clutch or kick" in user_content
    assert "- sam: OMG HE DID IT Pog" in user_content


@pytest.mark.asyncio
async def test_chat_descriptor_gemini_api_call():
    service = LocalChatDescriptorService(
        interval_seconds=60,
        gemini_api_key="fake-test-gemini-key",
        gemini_model="gemini-3.6-flash",
    )
    messages = [
        {"user": f"user{i}", "text": f"LUL {i}", "time": 100.0 + i}
        for i in range(10)
    ]

    mock_gemini_resp = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                "Chat exploded in laughter as the streamer accidentally threw their weapon off the ledge. "
                                "The dominant vibe was comedic schadenfreude with heavy LUL and OMEGALUL spam. "
                                "Viewers are now jokingly questioning the streamer's game awareness."
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
        result = await service.describe_chat_window(messages, channel="marlon")

    assert result is not None
    assert result["channel_name"] == "marlon"
    assert result["message_count"] == 10
    assert result["model_name"] == "gemini-3.6-flash"
    assert "Chat exploded in laughter" in result["description"]


@pytest.mark.asyncio
async def test_chat_descriptor_local_llm_call():
    service = LocalChatDescriptorService(
        interval_seconds=60,
        gemini_api_key="",  # No Gemini key -> falls back to local
        local_model_name="llama3.2:1b",
    )
    messages = [
        {"user": f"user{i}", "text": f"W clutch {i}", "time": 100.0 + i}
        for i in range(10)
    ]

    mock_local_resp = {
        "choices": [
            {
                "message": {
                    "content": "Viewers are hyped celebrating the 1v3 round win. The chat is flooding with W and Pog emotes. Energy is at an all-time high for the match."
                }
            }
        ]
    }

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_local_resp)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp)))

    with patch("aiohttp.ClientSession", return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session))):
        result = await service.describe_chat_window(messages, channel="marlon")

    assert result is not None
    assert result["channel_name"] == "marlon"
    assert result["model_name"] == "llama3.2:1b"
    assert "Viewers are hyped" in result["description"]


def test_db_save_and_retrieve_chat_descriptor(tmp_path):
    db_file = str(tmp_path / "test_clipper.db")
    db = DatabaseRepository(db_url=f"sqlite:///{db_file}")
    db._sqlite_path = db_file
    db._init_sqlite()

    record = {
        "id": "desc-12345",
        "channel_name": "tarik",
        "window_start": 1000.0,
        "window_end": 1060.0,
        "message_count": 45,
        "description": "Chat is thoroughly engaged in the tactical debate. Viewers are actively analyzing crosshair placement.",
        "model_name": "gemini-3.6-flash",
    }

    saved_id = db.save_chat_descriptor(record)
    assert saved_id == "desc-12345"

    retrieved = db.get_recent_descriptors(channel="tarik", limit=10)
    assert len(retrieved) == 1
    assert retrieved[0]["id"] == "desc-12345"
    assert retrieved[0]["channel_name"] == "tarik"
    assert retrieved[0]["message_count"] == 45
    assert retrieved[0]["model_name"] == "gemini-3.6-flash"
    assert "tactical debate" in retrieved[0]["description"]


def test_twitch_irc_drain_window_messages():
    engine = TwitchChatVelocityEngine(channel="shroud")
    line1 = ":user1!user1@user1.tmi.twitch.tv PRIVMSG #shroud :insane flick shot!"
    line2 = ":user2!user2@user2.tmi.twitch.tv PRIVMSG #shroud :POGGERS"

    p1 = parse_irc_privmsg(line1)
    p2 = parse_irc_privmsg(line2)

    engine.window_messages.append(p1)
    engine.window_messages.append(p2)

    drained = engine.drain_window_messages()
    assert len(drained) == 2
    assert drained[0]["user"] == "user1"
    assert drained[1]["user"] == "user2"

    # Ensure queue is now empty
    drained_again = engine.drain_window_messages()
    assert len(drained_again) == 0
