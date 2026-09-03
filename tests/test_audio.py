import numpy as np
import pytest
from services.heuristics.audio_monitor import AudioDecibelMonitor


def test_audio_monitor_silence():
    monitor = AudioDecibelMonitor()
    assert monitor.current_db == -60.0
    assert not monitor.is_spiking


def test_audio_monitor_sine_wave(tmp_path):
    import subprocess
    test_wav = str(tmp_path / "test.wav")
    # Generate 1-second 440Hz sine wave
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=1",
        "-y", test_wav,
    ]
    subprocess.run(cmd, check=True)

    monitor = AudioDecibelMonitor(jump_db_threshold=10.0, baseline_db=-50.0)
    res = monitor.process_segment(test_wav)
    assert res is not None
    assert res["current_db"] > -25.0
    assert res["delta_db"] > 10.0
    assert res["is_spiking"] is True


def test_audio_monitor_spike_detection():
    triggered = []

    def on_spike(level, jump):
        triggered.append((level, jump))

    monitor = AudioDecibelMonitor(
        jump_db_threshold=12.0,
        baseline_db=-40.0,
        on_spike_callback=on_spike,
    )
    # Simulate an internal spike
    monitor.current_db = -15.0
    monitor.delta_db = 25.0
    monitor.is_spiking = True
    monitor.on_spike(-15.0, 25.0)

    assert len(triggered) == 1
    assert triggered[0] == (-15.0, 25.0)
