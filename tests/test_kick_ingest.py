"""Unit test suite for Kick.com stream ingestion, Pusher chat velocity, and platform routing."""

import json
import pytest
from unittest.mock import MagicMock

from services.ingest.stream_buffer import clean_channel_name, detect_channel_and_platform, StreamRingBuffer
from services.ingest.kick_chat import KickChatVelocityEngine, parse_kick_chat_event
from services.orchestrator_dag import GraphDAGManager
from orchestrator import StreamSession


# ==========================================
# 1. Kick Channel & Platform URL Parsing
# ==========================================

def test_kick_channel_name_cleaning():
    assert clean_channel_name("https://kick.com/xqc") == "xqc"
    assert clean_channel_name("kick.com/trainwreckstv/") == "trainwreckstv"
    assert clean_channel_name("http://kick.com/roshtein?ref=123") == "roshtein"
    assert clean_channel_name("kick:adinross") == "adinross"
    assert clean_channel_name("#xqc") == "xqc"
    assert clean_channel_name("@xqc") == "xqc"


def test_detect_channel_and_platform():
    # Kick variations
    ch, plat = detect_channel_and_platform("https://kick.com/trainwreckstv")
    assert ch == "trainwreckstv"
    assert plat == "kick"

    ch, plat = detect_channel_and_platform("kick.com/xqc")
    assert ch == "xqc"
    assert plat == "kick"

    ch, plat = detect_channel_and_platform("kick:roshtein")
    assert ch == "roshtein"
    assert plat == "kick"

    # Twitch variations
    ch, plat = detect_channel_and_platform("https://twitch.tv/zarbex")
    assert ch == "zarbex"
    assert plat == "twitch"

    ch, plat = detect_channel_and_platform("twitch:marlon")
    assert ch == "marlon"
    assert plat == "twitch"

    # Plain handles fallback to default platform
    ch, plat = detect_channel_and_platform("tarik", default_platform="twitch")
    assert ch == "tarik"
    assert plat == "twitch"

    ch, plat = detect_channel_and_platform("trainwreckstv", default_platform="kick")
    assert ch == "trainwreckstv"
    assert plat == "kick"


# ==========================================
# 2. Kick Chat Event Parsing & Velocity
# ==========================================

def test_kick_chat_event_parsing():
    raw_payload = json.dumps({
        "id": "msg_98765",
        "chatroom_id": 668,
        "content": "MASSIVE WIN 2500x !!",
        "type": "message",
        "created_at": "2026-09-08 17:35:00",
        "sender": {
            "id": 1024,
            "username": "slot_king",
            "slug": "slot_king",
        }
    })

    parsed = parse_kick_chat_event(raw_payload)
    assert parsed is not None
    assert parsed["user"] == "slot_king"
    assert parsed["text"] == "MASSIVE WIN 2500x !!"
    assert "time" in parsed

    # Invalid JSON string
    assert parse_kick_chat_event("not_valid_json") is None


def test_kick_chat_velocity_and_spikes():
    spikes = []

    engine = KickChatVelocityEngine(
        channel="xqc",
        on_spike_callback=lambda inst, rat: spikes.append((inst, rat)),
        spike_ratio_threshold=2.0,
        instant_min_threshold=2.0,
        chatroom_id=668,
    )

    # Initial state
    stats = engine.recalculate()
    assert stats["v_instant"] == 0.0
    assert stats["v_baseline"] == 0.0
    assert stats["is_spiking"] is False

    # Simulate rapid burst of 15 chat messages
    for i in range(15):
        engine._record_message(f"user_{i}", f"Gamble spin #{i}")

    stats = engine.recalculate()
    assert stats["total_messages"] == 15
    assert stats["v_instant"] >= 2.0
    assert len(stats["recent_messages"]) == 15

    # Draining window messages
    drained = engine.drain_window_messages()
    assert len(drained) == 15
    assert len(engine.window_messages) == 0


# ==========================================
# 3. StreamSession Multi-Platform Lifecycle
# ==========================================

def test_stream_session_kick_initialization():
    mock_orch = MagicMock()
    mock_orch.sessions = {}

    session = StreamSession(
        channel="kick.com/trainwreckstv",
        orchestrator=mock_orch,
        simulate=True,
    )

    assert session.channel == "trainwreckstv"
    assert session.platform == "kick"
    assert isinstance(session.chat_engine, KickChatVelocityEngine)
    assert session.buffer.platform == "kick"

    telemetry = session.get_telemetry()
    assert telemetry["channel"] == "trainwreckstv"
    assert telemetry["platform"] == "kick"
    assert "player.kick.com/trainwreckstv" in telemetry["playback_embed_url"]


def test_stream_session_explicit_platform_override():
    mock_orch = MagicMock()
    mock_orch.sessions = {}

    session = StreamSession(
        channel="xqc",
        orchestrator=mock_orch,
        simulate=True,
        platform="kick",
    )

    assert session.channel == "xqc"
    assert session.platform == "kick"
    assert isinstance(session.chat_engine, KickChatVelocityEngine)
    assert session.buffer.platform == "kick"


# ==========================================
# 4. DAG Node Platform Hot-Reloading
# ==========================================

def test_dag_stream_source_kick_platform():
    mgr = GraphDAGManager()
    stream_node = mgr.nodes.get("node_stream")
    assert stream_node is not None

    # Switch to Kick
    assert mgr.update_node_param("node_stream", "platform", "kick") is True
    assert mgr.nodes["node_stream"]["properties"]["platform"] == "kick"
    assert "Kick Source:" in mgr.nodes["node_stream"]["title"]

    # Switch channel on Kick
    assert mgr.update_node_param("node_stream", "channel", "trainwreckstv") is True
    assert mgr.nodes["node_stream"]["title"] == "Kick Source: #trainwreckstv"
