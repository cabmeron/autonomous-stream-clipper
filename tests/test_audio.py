import time
import numpy as np
import pytest
from services.heuristics.audio_monitor import AudioDecibelMonitor


def test_audio_monitor_silence():
    monitor = AudioDecibelMonitor()
    samples = np.zeros(16000, dtype=np.float32)
    db = monitor.compute_rms_db(samples)
    assert db <= -60.0


def test_audio_monitor_sine_wave():
    monitor = AudioDecibelMonitor()
    # 440 Hz tone at 0.5 peak amplitude
    t = np.linspace(0, 1, 16000, endpoint=False)
    samples = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    db = monitor.compute_rms_db(samples)
    # RMS of 0.5 amplitude sine is 0.5 / sqrt(2) ≈ 0.3535 -> 20*log10(0.3535) ≈ -9.03 dB
    assert -10.0 <= db <= -8.0


def test_audio_monitor_spike_detection():
    spikes = []

    def on_spike(instant, delta):
        spikes.append((instant, delta))

    monitor = AudioDecibelMonitor(jump_db_threshold=12.0, on_spike_callback=on_spike)

    now = time.time()
    t = np.linspace(0, 1, 16000, endpoint=False)

    # 1. Feed quiet baseline (-35 dB) for 20 seconds
    quiet_samples = (0.01 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    for i in range(20):
        monitor.process_samples(quiet_samples, timestamp=now - 20.0 + i)

    assert not monitor.is_spiking

    # 2. Feed loud shout (-6 dB) at present time
    loud_samples = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    res = monitor.process_samples(loud_samples, timestamp=now)

    assert res["delta_db"] >= 12.0
    assert res["is_spiking"] is True
    assert len(spikes) == 1
    assert spikes[0][1] == res["delta_db"]
