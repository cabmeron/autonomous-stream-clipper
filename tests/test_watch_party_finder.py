import pytest
import asyncio
from services.heuristics.watch_party_finder import WatchPartyFinderService


@pytest.fixture
def finder():
    return WatchPartyFinderService()


def test_evaluate_candidates_watch_party(finder):
    candidates = [
        {
            "id": "c1",
            "login": "streamer_a",
            "display_name": "StreamerA",
            "title": "🔴 LIVE WATCH PARTY | WATCHING MARLON TOURNAMENT",
            "viewers": 2500,
            "game": "Just Chatting",
        },
        {
            "id": "c2",
            "login": "streamer_b",
            "display_name": "StreamerB",
            "title": "Reacting to marlon funny moments and clutches",
            "viewers": 450,
            "game": "Just Chatting",
        },
        {
            "id": "c3",
            "login": "streamer_c",
            "display_name": "StreamerC",
            "title": "Solo queue valorant grind | might play with marlon later",
            "viewers": 80,
            "game": "VALORANT",
        },
        {
            "id": "c4",
            "login": "streamer_d",
            "display_name": "StreamerD",
            "title": "Cooking pasta in Rome | IRL Stream",
            "viewers": 3,
            "game": "Just Chatting",
        },
    ]

    results = finder.evaluate_candidates("marlon", candidates)

    assert len(results) == 4
    # The top candidate should be StreamerA (explicit watch party + high viewers)
    top = results[0]
    assert top["login"] == "streamer_a"
    assert top["decision"] == "HOOK_IN"
    assert top["confidence"] >= 0.85
    assert "marlon" in top["reasoning"].lower()

    # Second candidate is streamer_b (direct reaction)
    second = results[1]
    assert second["login"] == "streamer_b"
    assert second["decision"] == "HOOK_IN"
    assert second["confidence"] >= 0.75

    # Third candidate is streamer_c (casual mention)
    third = results[2]
    assert third["login"] == "streamer_c"
    assert third["decision"] in ("POTENTIAL", "HOOK_IN")

    # Last candidate is streamer_d (unrelated + low viewers)
    last = results[3]
    assert last["login"] == "streamer_d"
    assert last["decision"] == "DISMISS"
    assert last["confidence"] < 0.30


def test_simulation_candidates(finder):
    sim_cands = finder.generate_simulation_candidates("zarbex")
    assert len(sim_cands) >= 3
    for cand in sim_cands:
        assert cand.get("is_simulation") is True
        assert "decision" in cand
        assert "confidence" in cand
        assert "reasoning" in cand
        assert cand["confidence"] > 0

    # Verify at least one recommended hook-in candidate in demo mode
    hook_ins = [c for c in sim_cands if c["decision"] == "HOOK_IN"]
    assert len(hook_ins) >= 1
    assert "zarbex" in hook_ins[0]["title"].lower()


@pytest.mark.asyncio
async def test_discover_and_evaluate_simulation(finder):
    res = await finder.discover_and_evaluate("test_channel", force_simulation=True)
    assert res["target_channel"] == "test_channel"
    assert res["candidates_count"] > 0
    assert res["hook_recommendations"] >= 1
    assert "candidates" in res
    assert "elapsed_seconds" in res

    # Verify cached results
    cached = finder.get_cached_results("test_channel")
    assert cached is not None
    assert cached["target_channel"] == "test_channel"
