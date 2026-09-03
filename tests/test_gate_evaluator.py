import time
import pytest
from services.heuristics.gate_evaluator import GateEvaluator


def test_gate_evaluator_scoring():
    evaluator = GateEvaluator()
    # Base score
    assert evaluator.calculate_heuristic_score("test") == 5

    # High chat spike
    assert evaluator.calculate_heuristic_score("chat", chat_ratio=5.5) == 8

    # Win multiplier 500x
    assert evaluator.calculate_heuristic_score("ocr", win_mult=600.0) == 8

    # High audio surge + chat spike
    assert evaluator.calculate_heuristic_score("audio", chat_ratio=3.5, audio_delta=20.0) == 9


def test_gate_evaluator_debounce():
    evaluator = GateEvaluator(debounce_seconds=10.0, post_event_delay_seconds=0.0)

    # First signal passes
    fired_1 = evaluator.evaluate_signals(source="chat_spike", chat_ratio=4.0)
    assert fired_1 is True

    # Immediate second signal blocked by cooldown
    fired_2 = evaluator.evaluate_signals(source="audio_spike", audio_delta=15.0)
    assert fired_2 is False
