"""Unit and integration tests for ClipFolderNode, multi-renderer routing,
database folder persistence, and REST APIs.
"""

import os
import shutil
import tempfile
import time
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from services.storage.db import DatabaseRepository
from services.orchestrator_dag import GraphDAGManager


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_clipper.db")
    
    class TestDB(DatabaseRepository):
        def __init__(self):
            self._sqlite_path = db_path
            self.use_sqlite = True
            os.makedirs(os.path.dirname(self._sqlite_path), exist_ok=True)
            self._init_sqlite()

    db = TestDB()
    yield db
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_db_folder_schema_and_queries(temp_db):
    """Verifies that clips can be persisted with folder metadata and queried by folder."""
    clip_data_1 = {
        "channel_name": "marlon",
        "video_url": "/storage/clips/clip_1.mp4",
        "thumbnail_url": "/storage/clips/thumb_1.jpg",
        "duration_seconds": 25.4,
        "cut_start": 10.0,
        "cut_end": 35.4,
        "heuristic_score": 8,
        "suggested_title": "Huge Slot Win 500x",
        "folder_id": "folder_slots_2026",
        "folder_name": "Slots Big Wins",
        "folder_date": "2026-09-09",
    }
    clip_id_1 = temp_db.save_clip(clip_data_1)
    assert clip_id_1 is not None

    clip_data_2 = {
        "channel_name": "trainwreckstv",
        "video_url": "/storage/clips/clip_2.mp4",
        "thumbnail_url": "/storage/clips/thumb_2.jpg",
        "duration_seconds": 40.0,
        "cut_start": 5.0,
        "cut_end": 45.0,
        "heuristic_score": 9,
        "suggested_title": "Trainwrecks Insane Bonus",
        "folder_id": "folder_slots_2026",
        "folder_name": "Slots Big Wins",
        "folder_date": "2026-09-09",
    }
    clip_id_2 = temp_db.save_clip(clip_data_2)
    assert clip_id_2 is not None

    # Uncategorized clip without folder
    clip_data_3 = {
        "channel_name": "xqc",
        "video_url": "/storage/clips/clip_3.mp4",
        "thumbnail_url": "/storage/clips/thumb_3.jpg",
        "duration_seconds": 15.0,
        "cut_start": 0.0,
        "cut_end": 15.0,
        "heuristic_score": 5,
        "suggested_title": "Random Clip",
    }
    clip_id_3 = temp_db.save_clip(clip_data_3)

    # 1. Query by folder
    folder_clips = temp_db.get_clips_by_folder("folder_slots_2026")
    assert len(folder_clips) == 2
    titles = [c["suggested_title"] for c in folder_clips]
    assert "Huge Slot Win 500x" in titles
    assert "Trainwrecks Insane Bonus" in titles
    assert folder_clips[0]["folder_name"] == "Slots Big Wins"
    assert folder_clips[0]["folder_date"] == "2026-09-09"

    # 2. Filter recent clips by folder
    filtered = temp_db.get_recent_clips(folder_id="folder_slots_2026")
    assert len(filtered) == 2
    assert all(c["folder_id"] == "folder_slots_2026" for c in filtered)

    # 3. Move uncategorized clip into the folder
    success = temp_db.update_clip_folder(clip_id_3, "folder_slots_2026", "Slots Big Wins", "2026-09-09")
    assert success is True

    updated_folder_clips = temp_db.get_clips_by_folder("folder_slots_2026")
    assert len(updated_folder_clips) == 3


def test_dag_default_template_has_clip_folder():
    """Verifies that default template connects HardwareRenderNode -> ClipFolderNode."""
    dag = GraphDAGManager()
    
    assert "node_folder" in dag.nodes
    folder_node = dag.nodes["node_folder"]
    assert folder_node["type"] == "ClipFolderNode"
    assert folder_node["properties"]["folder_name"] == "Highlight Reels"
    assert "date" in folder_node["properties"]

    # Verify wire exists
    render_to_folder = next(
        (w for w in dag.wires if w["from"] == "node_render:clip_asset" and w["to"] == "node_folder:clip_in"),
        None,
    )
    assert render_to_folder is not None
    assert render_to_folder["type"] == "clip"

    # Validate DAG
    valid, msg = dag.validate_dag(dag.nodes, dag.wires)
    assert valid is True, msg


def test_multi_renderer_routing_to_single_folder():
    """Verifies multiple hardware renderers (e.g. 1080p Horizontal + 9:16 Vertical)

    can both route their finished clips to a single shared ClipFolderNode.
    """
    dag = GraphDAGManager()

    # Add second hardware renderer (e.g. vertical shorts)
    dag.nodes["node_render_vert"] = {
        "id": "node_render_vert",
        "type": "HardwareRenderNode",
        "title": "Hardware Video Renderer (9:16 Shorts)",
        "category": "render",
        "position": [1520, 480],
        "properties": {"crop_vertical": True, "enable_subs": True},
        "inputs": [{"id": "candidate_in", "name": "Candidate Video", "type": "video"}],
        "outputs": [{"id": "clip_asset", "name": "Finished MP4 Clip", "type": "clip"}],
    }

    # Connect second renderer to the same folder node
    dag.wires.append({
        "id": "w_vert_to_folder",
        "from": "node_render_vert:clip_asset",
        "to": "node_folder:clip_in",
        "type": "clip",
    })

    # Validate graph with two incoming wires into node_folder:clip_in
    valid, msg = dag.validate_dag(dag.nodes, dag.wires)
    assert valid is True, msg

    # Resolve downstream folder
    downstream = dag.get_downstream_folder_for_session("marlon")
    assert downstream is not None
    assert downstream["folder_id"] == "node_folder"
    assert downstream["folder_name"] == "Highlight Reels"


def test_clip_folder_telemetry_payload(temp_db):
    """Verifies that get_node_telemetry_payload computes clip metrics for ClipFolderNode."""
    class DummyOrchestrator:
        def __init__(self, db):
            self.db = db
            self.sessions = {}

    orchestrator = DummyOrchestrator(temp_db)
    dag = GraphDAGManager(orchestrator=orchestrator)

    # Save a clip under node_folder
    temp_db.save_clip({
        "channel_name": "marlon",
        "video_url": "/storage/clips/test_clip.mp4",
        "thumbnail_url": "/storage/clips/test_thumb.jpg",
        "duration_seconds": 32.5,
        "cut_start": 0.0,
        "cut_end": 32.5,
        "heuristic_score": 7,
        "suggested_title": "Great Gameplay Moment",
        "folder_id": "node_folder",
        "folder_name": "Highlight Reels",
        "folder_date": "2026-09-09",
    })

    payload = dag.get_node_telemetry_payload()
    assert "node_folder" in payload
    folder_data = payload["node_folder"]

    assert folder_data["folder_id"] == "node_folder"
    assert folder_data["clip_count"] == 1
    assert folder_data["total_duration"] == 32.5
    assert len(folder_data["wired_renderers"]) >= 1
    assert folder_data["recent_clips"][0]["title"] == "Great Gameplay Moment"


def test_update_node_param_folder_name():
    """Verifies that updating folder_name mutates node properties and title."""
    dag = GraphDAGManager()
    success = dag.update_node_param("node_folder", "folder_name", "Crazy Slots 2026")
    assert success is True
    assert dag.nodes["node_folder"]["properties"]["folder_name"] == "Crazy Slots 2026"
    assert dag.nodes["node_folder"]["title"] == "Clip Folder: Crazy Slots 2026"


@pytest.mark.asyncio
async def test_rest_api_folder_endpoints(temp_db):
    """Tests the REST APIs: GET /api/folders/{id}/clips and POST /api/clips/{id}/folder."""
    # Seed clips
    cid1 = temp_db.save_clip({
        "channel_name": "marlon",
        "video_url": "/storage/clips/clip_a.mp4",
        "duration_seconds": 20.0,
        "cut_start": 0.0,
        "cut_end": 20.0,
        "heuristic_score": 8,
        "suggested_title": "Clip A in Folder 1",
        "folder_id": "folder_1",
        "folder_name": "Folder One",
        "folder_date": "2026-09-09",
    })

    cid2 = temp_db.save_clip({
        "channel_name": "marlon",
        "video_url": "/storage/clips/clip_b.mp4",
        "duration_seconds": 30.0,
        "cut_start": 0.0,
        "cut_end": 30.0,
        "heuristic_score": 6,
        "suggested_title": "Clip B unassigned",
    })

    app = web.Application()

    async def get_folder_clips_handler(request):
        fid = request.match_info["folder_id"]
        clips = temp_db.get_clips_by_folder(fid)
        return web.json_response(clips)

    async def post_clip_folder_handler(request):
        clip_id = request.match_info["id"]
        data = await request.json()
        success = temp_db.update_clip_folder(
            clip_id,
            data.get("folder_id"),
            data.get("folder_name"),
            data.get("folder_date"),
        )
        return web.json_response({"success": success, "id": clip_id, "folder_id": data.get("folder_id")})

    async def get_clips_handler(request):
        fid = request.query.get("folder_id")
        clips = temp_db.get_recent_clips(folder_id=fid)
        return web.json_response(clips)

    app.router.add_get("/api/folders/{folder_id}/clips", get_folder_clips_handler)
    app.router.add_post("/api/clips/{id}/folder", post_clip_folder_handler)
    app.router.add_get("/api/clips", get_clips_handler)

    from aiohttp.test_utils import TestServer, TestClient
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        # 1. Fetch folder 1 clips
        resp = await client.get("/api/folders/folder_1/clips")
        assert resp.status == 200
        clips = await resp.json()
        assert len(clips) == 1
        assert clips[0]["id"] == cid1

        # 2. Assign clip 2 to folder 1
        assign_resp = await client.post(f"/api/clips/{cid2}/folder", json={
            "folder_id": "folder_1",
            "folder_name": "Folder One",
            "folder_date": "2026-09-09",
        })
        assert assign_resp.status == 200
        result = await assign_resp.json()
        assert result["success"] is True

        # 3. Verify folder now has 2 clips
        resp2 = await client.get("/api/folders/folder_1/clips")
        clips2 = await resp2.json()
        assert len(clips2) == 2

        # 4. Verify query filter /api/clips?folder_id=folder_1
        q_resp = await client.get("/api/clips?folder_id=folder_1")
        assert q_resp.status == 200
        q_clips = await q_resp.json()
        assert len(q_clips) == 2
    finally:
        await client.close()
