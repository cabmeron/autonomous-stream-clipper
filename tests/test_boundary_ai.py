from services.processor.boundary_ai import BoundaryOptimizer


def test_boundary_ai_fallback():
    opt = BoundaryOptimizer()
    context = {"win_multiplier": 150.0, "pnl_delta": 2500.0, "score": 8, "trigger_source": "ocr"}
    res = opt.find_optimal_cut(words=[], event_context=context, total_duration=60.0)

    assert "cut_start" in res
    assert "cut_end" in res
    duration = res["cut_end"] - res["cut_start"]
    assert 20.0 <= duration <= 58.0
    assert "150X" in res["title"].upper()
