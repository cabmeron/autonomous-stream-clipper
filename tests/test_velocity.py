import time
import pytest
from services.ingest.twitch_irc import TwitchChatVelocityEngine


def test_velocity_empty():
    engine = TwitchChatVelocityEngine("testchannel")
    res = engine.recalculate()
    assert res["v_instant"] == 0.0
    assert res["v_baseline"] == 0.0
    assert res["spike_ratio"] == 0.0
    assert not res["is_spiking"]


def test_velocity_steady_traffic():
    engine = TwitchChatVelocityEngine("testchannel")
    now = time.time()
    # Inject 1 message every 2 seconds for 60 seconds (30 messages)
    for i in range(30):
        engine.timestamps.append(now - 60.0 + (i * 2.0))

    res = engine.recalculate()
    # 5s window has ~2-3 messages
    assert res["v_baseline"] > 0
    assert not res["is_spiking"]


def test_velocity_spike_detection():
    spikes = []

    def on_spike(instant, ratio):
        spikes.append((instant, ratio))

    engine = TwitchChatVelocityEngine(
        "testchannel",
        on_spike_callback=on_spike,
        spike_ratio_threshold=3.0,
        instant_min_threshold=10.0,
    )

    now = time.time()
    # Inject 60 background messages over the last 60 seconds (1 msg/sec baseline)
    for i in range(55):
        engine.timestamps.append(now - 55.0 + i)

    # Now inject 60 messages in the last 4 seconds (~15 msgs/sec instant)
    for _ in range(60):
        engine.timestamps.append(now - 2.0)

    res = engine.recalculate()
    assert res["v_instant"] >= 10.0
    assert res["spike_ratio"] >= 3.0
    assert res["is_spiking"] is True
    assert len(spikes) == 1
    assert spikes[0][0] == res["v_instant"]
    assert spikes[0][1] == res["spike_ratio"]
