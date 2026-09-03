import pytest
from services.processor.boundary_ai import BoundaryOptimizer


def test_boundary_ai_fallback():
    optimizer = BoundaryOptimizer()
    words = [
        {"word": "OH", "start": 5.0, "end": 5.5},
        {"word": "MY", "start": 5.6, "end": 6.0},
        {"word": "GOD", "start": 6.1, "end": 7.0},
        {"word": "LOOK", "start": 32.0, "end": 33.0},
    ]
    context = {
        "trigger_source": "ocr_multiplier",
        "win_multiplier": 250.0,
        "score": 9,
    }

    result = optimizer.find_optimal_cut(words, context, total_duration=60.0)

    assert "cut_start" in result
    assert "cut_end" in result
    assert "title" in result
    assert "caption" in result
    assert "score" in result

    duration = result["cut_end"] - result["cut_start"]
    assert 20.0 <= duration <= 58.0
    assert "250X" in result["title"]
