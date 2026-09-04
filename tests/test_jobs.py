import pytest
from orchestrator import StreamClipperOrchestrator
from services.heuristics.gate_evaluator import GateEvaluator


def test_clipping_job_lifecycle():
    orch = StreamClipperOrchestrator()
    context = {
        "trigger_source": "audio_spike",
        "score": 8,
        "post_event_delay": 15.0,
    }

    # 1. Test job creation
    job_id = orch.create_job("shroud", context)
    assert job_id in orch.active_jobs
    job = orch.active_jobs[job_id]
    assert job["channel"] == "shroud"
    assert job["status"] == "processing"
    assert job["score"] == 8
    assert job["progress_pct"] == 12
    assert len(job["steps"]) == 7
    assert job["steps"][0]["status"] == "done"
    assert job["steps"][1]["status"] == "running"
    assert len(job["logs"]) >= 2

    # 2. Test step update
    orch.update_job_step(
        job_id,
        step_id="slicing",
        step_status="running",
        progress_pct=30,
        log_msg="Extracting RAM slice",
        detail="6 segments",
    )
    assert job["steps"][2]["status"] == "running"
    assert job["steps"][2]["detail"] == "6 segments"
    assert job["progress_pct"] == 30
    assert any("Extracting RAM slice" in l for l in job["logs"])

    # 3. Test job completion
    clip_summary = {
        "id": "clip_123",
        "channel": "shroud",
        "duration_seconds": 24.5,
        "video_url": "/clips/clip_123.mp4",
    }
    orch.complete_job(job_id, clip_summary)
    assert job["status"] == "completed"
    assert job["progress_pct"] == 100
    assert job["clip"]["id"] == "clip_123"
    assert all(s["status"] == "done" for s in job["steps"])


def test_gate_evaluator_triggers_job_activation():
    activated_contexts = []

    def on_activated(ctx):
        activated_contexts.append(ctx)

    evaluator = GateEvaluator(
        on_trigger_dispatch=lambda ctx: None,
        on_trigger_activated=on_activated,
        debounce_seconds=10.0,
        post_event_delay_seconds=0.0,
    )

    # Trigger excitement spike
    evaluator.evaluate_signals("chat_spike", chat_instant=40.0, chat_ratio=6.0)

    assert len(activated_contexts) == 1
    assert activated_contexts[0]["trigger_source"] == "chat_spike"
    assert activated_contexts[0]["score"] >= 4


@pytest.mark.asyncio
async def test_orchestrator_trigger_manual_clip(monkeypatch):
    orch = StreamClipperOrchestrator()

    # 1. Error if channel does not exist
    with pytest.raises(ValueError) as exc:
        await orch.trigger_manual_clip("nonexistent")
    assert "not active" in str(exc.value)

    # 2. Add session
    await orch.add_session("testclip")

    # Mock process_clip_trigger so test doesn't run full ffmpeg pipeline
    triggered_context = []
    async def mock_process(session, ctx):
        triggered_context.append(ctx)

    monkeypatch.setattr(orch, "process_clip_trigger", mock_process)

    # 3. Trigger manual clip
    res = await orch.trigger_manual_clip("testclip")
    assert res["success"] is True
    assert res["channel"] == "testclip"
    assert res["job_id"] in orch.active_jobs

    job = orch.active_jobs[res["job_id"]]
    assert job["channel"] == "testclip"
    assert job["score"] == 10
    assert job["status"] == "processing"

    # Cleanup session
    await orch.remove_session("testclip")


def test_orchestrator_job_failure_updates_step_and_status():
    orch = StreamClipperOrchestrator()
    job_id = orch.create_job("marlon", {"trigger_source": "manual_trigger", "score": 10})

    orch.update_job_step(job_id, "slicing", "running", 28, log_msg="Concatenating candidate stream slice...")
    job = orch.active_jobs[job_id]
    assert job["steps"][2]["status"] == "running"

    orch.fail_job(job_id, "Failed to concatenate segments: missing stream data")
    assert job["status"] == "failed"
    assert "Failed to concatenate segments" in job["current_step"]
    assert job["steps"][2]["status"] == "failed"
    assert "missing stream data" in job["steps"][2]["detail"]
    assert any("ERROR:" in l for l in job["logs"])


