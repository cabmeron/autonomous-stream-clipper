import asyncio
import pytest
from orchestrator import StreamClipperOrchestrator
import telemetry_server


@pytest.mark.asyncio
async def test_orchestrator_channel_lifecycle():
    orchestrator = StreamClipperOrchestrator()

    # 1. Startup should be completely empty / idle
    assert orchestrator.channel is None
    status = orchestrator.get_status()
    assert status["channel"] is None
    assert status["status"] == "idle"
    assert status["is_buffering"] is False
    assert telemetry_server.engine is None

    # 2. Dynamically bind a channel (using test simulation channel)
    bind_status = await orchestrator.set_channel("test")
    assert bind_status["channel"] == "test"
    assert bind_status["status"] == "monitoring"
    assert orchestrator.channel == "test"
    assert orchestrator.buffer is not None
    assert orchestrator.chat_engine is not None
    assert telemetry_server.engine is not None
    assert telemetry_server.engine.channel == "test"

    # 3. Cleanly unbind / clear the channel
    unbind_status = await orchestrator.set_channel("")
    assert unbind_status["channel"] is None
    assert unbind_status["status"] == "idle"
    assert orchestrator.channel is None
    assert orchestrator.buffer is None
    assert orchestrator.chat_engine is None
    assert telemetry_server.engine is None
