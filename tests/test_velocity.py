import time
from services.ingest.twitch_irc import TwitchChatVelocityEngine


def test_velocity_empty():
    engine = TwitchChatVelocityEngine("shroud")
    metrics = engine.recalculate()
    assert metrics["v_instant"] == 0.0
    assert metrics["v_baseline"] == 0.0
    assert metrics["spike_ratio"] == 0.0
    assert metrics["is_spiking"] is False


def test_velocity_steady_traffic():
    engine = TwitchChatVelocityEngine("shroud")
    now = time.time()
    # 2 msgs per second for 60 seconds
    for sec in range(60):
        t = now - 60 + sec
        engine.timestamps.append(t)
        engine.timestamps.append(t + 0.5)

    metrics = engine.recalculate()
    assert abs(metrics["v_baseline"] - 2.0) <= 0.2
    assert abs(metrics["v_instant"] - 2.0) <= 0.2
    assert metrics["is_spiking"] is False


def test_velocity_spike_detection():
    spikes = []

    def on_spike(v_inst, ratio):
        spikes.append((v_inst, ratio))

    engine = TwitchChatVelocityEngine("shroud", on_spike_callback=on_spike, spike_ratio_threshold=3.0, instant_min_threshold=10.0)
    now = time.time()

    # Steady 2 msg/s for baseline
    for sec in range(60):
        t = now - 60 + sec
        engine.timestamps.append(t)
        engine.timestamps.append(t + 0.5)

    # Spike in last 5 seconds: 80 messages (16 msg/s)
    for i in range(80):
        engine.timestamps.append(now - 4.0 + (i * 0.04))

    metrics = engine.recalculate()
    assert metrics["v_instant"] >= 14.0
    assert metrics["spike_ratio"] >= 3.0
    assert metrics["is_spiking"] is True
    assert len(spikes) == 1
