import os
import pytest
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


@pytest.mark.asyncio
async def test_live_hls_playlist_and_segment_routes(tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from orchestrator import StreamClipperOrchestrator, StreamSession
    from services.ingest.stream_buffer import StreamRingBuffer

    orch = StreamClipperOrchestrator()
    buf = StreamRingBuffer(channel="teststream", shm_dir=str(tmp_path), simulate=True)
    os.makedirs(buf.shm_dir, exist_ok=True)
    seg1 = os.path.join(buf.shm_dir, "seg_00.ts")
    with open(seg1, "wb") as f:
        f.write(b"dummy ts content 1")
    seg2 = os.path.join(buf.shm_dir, "seg_01.ts")
    with open(seg2, "wb") as f:
        f.write(b"dummy ts content 2")

    session = StreamSession(channel="teststream", orchestrator=orch)
    session.buffer = buf
    orch.sessions["teststream"] = session

    app = web.Application()

    async def get_live_playlist_handler(request):
        channel = request.match_info.get("channel", "").lower()
        if channel not in orch.sessions:
            return web.Response(text="#EXTM3U\n", status=404, content_type="application/vnd.apple.mpegurl")
        s = orch.sessions[channel]
        segments = s.buffer.get_active_segments()
        usable = segments[:-1] if len(segments) > 1 else segments
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{s.buffer.segment_time}"]
        for p in usable:
            lines.append(f"/api/sessions/{channel}/segments/{os.path.basename(p)}")
        return web.Response(text="\n".join(lines), content_type="application/vnd.apple.mpegurl")

    async def get_live_segment_handler(request):
        channel = request.match_info.get("channel", "").lower()
        segment = request.match_info.get("segment", "")
        if ".." in segment or "/" in segment or not segment.endswith(".ts"):
            return web.Response(text="Invalid segment", status=400)
        s = orch.sessions[channel]
        seg_path = os.path.join(s.buffer.shm_dir, segment)
        if not os.path.exists(seg_path):
            return web.Response(text="Not found", status=404)
        return web.FileResponse(seg_path, headers={"Content-Type": "video/MP2T"})

    app.router.add_get("/api/sessions/{channel}/live.m3u8", get_live_playlist_handler)
    app.router.add_get("/api/sessions/{channel}/segments/{segment}", get_live_segment_handler)

    client = TestClient(TestServer(app))
    await client.start_server()

    # Test playlist response
    resp = await client.get("/api/sessions/teststream/live.m3u8")
    assert resp.status == 200
    text = await resp.text()
    assert "#EXTM3U" in text
    assert "/api/sessions/teststream/segments/seg_00.ts" in text

    # Test segment response
    seg_resp = await client.get("/api/sessions/teststream/segments/seg_00.ts")
    assert seg_resp.status == 200
    content = await seg_resp.read()
    assert content == b"dummy ts content 1"

    # Test non-existent session
    bad_sess_resp = await client.get("/api/sessions/nonexistent/live.m3u8")
    await client.close()


def test_clean_channel_name_normalization():
    from services.ingest.stream_buffer import clean_channel_name

    assert clean_channel_name("https://www.twitch.tv/ponden") == "ponden"
    assert clean_channel_name("https://www.twitch.tv/ponden/") == "ponden"
    assert clean_channel_name("http://twitch.tv/ponden") == "ponden"
    assert clean_channel_name("twitch.tv/ponden") == "ponden"
    assert clean_channel_name("www.twitch.tv/ponden") == "ponden"
    assert clean_channel_name("https://twitch.tv/tarik/clip/123") == "tarik"
    assert clean_channel_name("#marlon") == "marlon"
    assert clean_channel_name("@marlon") == "marlon"
    assert clean_channel_name("zarbex") == "zarbex"
    assert clean_channel_name("  https://twitch.tv/tarik/?ref=test  ") == "tarik"
    assert clean_channel_name("") == ""


@pytest.mark.asyncio
async def test_watch_party_discovery_endpoints():
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from orchestrator import StreamClipperOrchestrator, StreamSession

    orch = StreamClipperOrchestrator()
    orch.sessions["tarik_marlon_reacts"] = StreamSession(channel="tarik_marlon_reacts", orchestrator=orch)

    app = web.Application()

    async def post_discover_watchers_handler(request):
        channel = request.match_info.get("channel") or request.query.get("channel")
        force_simulation = request.query.get("simulate", "false").lower() in ("true", "1")
        include_simulation = request.query.get("include_simulation", "true").lower() in ("true", "1")
        if not channel and request.can_read_body:
            try:
                body = await request.json()
                channel = body.get("channel")
                if "force_simulation" in body:
                    force_simulation = bool(body.get("force_simulation"))
            except Exception:
                pass
        clean = channel or "marlon"
        res = await orch.watch_party_finder.discover_and_evaluate(
            target_channel=clean,
            include_simulation_if_empty=include_simulation,
            force_simulation=force_simulation,
        )
        for cand in res.get("candidates", []):
            cand["is_active_session"] = cand.get("login") in orch.sessions
        return web.json_response(res)

    async def get_watchers_handler(request):
        channel = request.match_info.get("channel") or "marlon"
        cached = orch.watch_party_finder.get_cached_results(channel)
        if not cached:
            cached = await orch.watch_party_finder.discover_and_evaluate(channel, force_simulation=True)
        for cand in cached.get("candidates", []):
            cand["is_active_session"] = cand.get("login") in orch.sessions
        return web.json_response(cached)

    app.router.add_post("/api/sessions/{channel}/discover-watchers", post_discover_watchers_handler)
    app.router.add_post("/api/discover-watchers", post_discover_watchers_handler)
    app.router.add_get("/api/sessions/{channel}/watchers", get_watchers_handler)

    client = TestClient(TestServer(app))
    await client.start_server()

    # Test POST with simulate=true query param
    resp = await client.post("/api/sessions/marlon/discover-watchers?simulate=true")
    assert resp.status == 200
    data = await resp.json()
    assert data["target_channel"] == "marlon"
    assert data["candidates_count"] > 0
    assert data["hook_recommendations"] >= 1
    # Check that is_active_session correctly identified active session
    active_cand = next((c for c in data["candidates"] if c["login"] == "tarik_marlon_reacts"), None)
    assert active_cand is not None
    assert active_cand["is_active_session"] is True

    # Test GET cached results
    get_resp = await client.get("/api/sessions/marlon/watchers")
    assert get_resp.status == 200
    get_data = await get_resp.json()
    assert get_data["target_channel"] == "marlon"

    await client.close()


