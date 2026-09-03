import asyncio
import pytest
from orchestrator import StreamClipperOrchestrator
import telemetry_server


@pytest.mark.asyncio
async def test_orchestrator_multi_session_lifecycle():
    orchestrator = StreamClipperOrchestrator()

    # 1. Startup should have 0 sessions
    assert len(orchestrator.sessions) == 0
    status = orchestrator.get_status()
    assert status["channel"] is None
    assert status["status"] == "idle"

    # 2. Add first stream session (using simulation test channel)
    res1 = await orchestrator.add_session("test1")
    assert res1["channel"] == "test1"
    assert res1["status"] == "monitoring"
    assert "test1" in orchestrator.sessions
    assert len(orchestrator.sessions) == 1

    # 3. Add second stream session concurrently
    res2 = await orchestrator.add_session("test2")
    assert res2["channel"] == "test2"
    assert res2["status"] == "monitoring"
    assert "test2" in orchestrator.sessions
    assert len(orchestrator.sessions) == 2

    # Verify telemetry provider returns both
    all_telemetry = orchestrator.get_all_telemetry()
    assert "test1" in all_telemetry
    assert "test2" in all_telemetry

    all_statuses = orchestrator.get_all_sessions_status()
    assert len(all_statuses) == 2

    # 4. Remove first session
    removed = await orchestrator.remove_session("test1")
    assert removed is True
    assert "test1" not in orchestrator.sessions
    assert "test2" in orchestrator.sessions
    assert len(orchestrator.sessions) == 1

    # 5. Remove second session
    removed2 = await orchestrator.remove_session("test2")
    assert removed2 is True
    assert len(orchestrator.sessions) == 0
    assert orchestrator.get_status()["channel"] is None
