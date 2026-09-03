import time
from services.heuristics.gate_evaluator import GateEvaluator


def test_gate_evaluator_scoring():
    evaluator = GateEvaluator(on_trigger_dispatch=lambda ctx: None)

    # Low signal
    assert evaluator.calculate_score(chat_instant=2.0, chat_ratio=1.1, win_multiplier=1.0, pnl_delta=0.0, audio_delta=2.0) == 1

    # High chat spike
    score_chat = evaluator.calculate_score(chat_instant=35.0, chat_ratio=5.5, win_multiplier=1.0, pnl_delta=0.0, audio_delta=0.0)
    assert score_chat >= 4

    # High OCR win
    score_ocr = evaluator.calculate_score(chat_instant=0.0, chat_ratio=1.0, win_multiplier=600.0, pnl_delta=10000.0, audio_delta=0.0)
    assert score_ocr >= 5

    # Multi-signal synergy
    score_combo = evaluator.calculate_score(chat_instant=20.0, chat_ratio=4.0, win_multiplier=150.0, pnl_delta=1200.0, audio_delta=15.0)
    assert score_combo >= 7


def test_gate_evaluator_debounce():
    dispatched = []

    def dispatch(ctx):
        dispatched.append(ctx)

    evaluator = GateEvaluator(on_trigger_dispatch=dispatch, debounce_seconds=10.0, post_event_delay_seconds=0.0)
    evaluator.evaluate_signals("chat_spike", chat_instant=40.0, chat_ratio=6.0)

    assert evaluator.last_trigger_time > 0

    # Second trigger within 10s should be debounced/suppressed
    evaluator.evaluate_signals("audio_spike", audio_delta=20.0)
    assert time.time() - evaluator.last_trigger_time < 10.0


def test_single_audio_spike_qualifies():
    activated = []
    evaluator = GateEvaluator(
        on_trigger_dispatch=lambda ctx: None,
        on_trigger_activated=lambda ctx: activated.append(ctx),
        debounce_seconds=5.0,
        post_event_delay_seconds=0.0,
    )
    score = evaluator.calculate_score(chat_instant=2.0, chat_ratio=1.0, win_multiplier=1.0, pnl_delta=0.0, audio_delta=14.0)
    assert score >= 4
    evaluator.evaluate_signals("audio_spike", audio_delta=14.0)
    assert len(activated) == 1
    assert activated[0]["score"] >= 4


def test_single_chat_spike_qualifies():
    activated = []
    evaluator = GateEvaluator(
        on_trigger_dispatch=lambda ctx: None,
        on_trigger_activated=lambda ctx: activated.append(ctx),
        debounce_seconds=5.0,
        post_event_delay_seconds=0.0,
    )
    score = evaluator.calculate_score(chat_instant=15.0, chat_ratio=3.5, win_multiplier=1.0, pnl_delta=0.0, audio_delta=0.0)
    assert score >= 4
    evaluator.evaluate_signals("chat_spike", chat_instant=15.0, chat_ratio=3.5)
    assert len(activated) == 1
    assert activated[0]["score"] >= 4
