from collections import deque
import logging
import subprocess
import time
from typing import Callable, Deque, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class AudioDecibelMonitor:
    """Monitors live stream audio segments for abrupt decibel/RMS volume spikes."""

    def __init__(
        self,
        jump_db_threshold: float = 12.0,
        instant_window_seconds: float = 3.0,
        baseline_window_seconds: float = 30.0,
        on_spike_callback: Optional[Callable[[float, float], None]] = None,
    ):
        self.jump_db_threshold = jump_db_threshold
        self.instant_window = instant_window_seconds
        self.baseline_window = baseline_window_seconds
        self.on_spike = on_spike_callback

        # Deque of (timestamp, db_val)
        self.history: Deque[Tuple[float, float]] = deque()
        self.current_db: float = -60.0
        self.instant_db: float = -60.0
        self.baseline_db: float = -60.0
        self.delta_db: float = 0.0
        self.is_spiking: bool = False

    @staticmethod
    def extract_pcm_from_media(media_path: str, tail_seconds: float = 5.0) -> Optional[np.ndarray]:
        """Extracts raw 16kHz mono 16-bit PCM audio samples from media via FFmpeg pipe."""
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-sseof", f"-{tail_seconds}",
            "-i", media_path,
            "-vn",
            "-f", "s16le",
            "-ac", "1",
            "-ar", "16000",
            "-"
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True)
            if not res.stdout:
                return None
            samples = np.frombuffer(res.stdout, dtype=np.int16).astype(np.float32) / 32768.0
            return samples
        except Exception as err:
            logger.debug("[AudioMonitor] Failed to extract PCM from %s: %s", media_path, err)
            return None

    @staticmethod
    def compute_rms_db(samples: np.ndarray) -> float:
        """Computes Root Mean Square decibel full scale (dBFS)."""
        if len(samples) == 0:
            return -90.0
        rms = np.sqrt(np.mean(np.square(samples)))
        if rms < 1e-6:
            return -90.0
        return float(20.0 * np.log10(rms))

    def process_samples(self, samples: np.ndarray, timestamp: Optional[float] = None) -> dict:
        """Calculates RMS dB for sample array and updates the sliding windows."""
        now = timestamp or time.time()
        db = self.compute_rms_db(samples)
        self.current_db = round(db, 2)

        # Baseline is computed over history prior to the current instant spike
        cutoff_baseline = now - self.baseline_window
        while self.history and self.history[0][0] < cutoff_baseline:
            self.history.popleft()

        cutoff_instant = now - self.instant_window
        # Baseline before current peak
        prior_baseline = [val for (t, val) in self.history if t < cutoff_instant]
        if not prior_baseline:
            prior_baseline = [val for (t, val) in self.history]

        self.history.append((now, db))

        instant_vals = [val for (t, val) in self.history if t >= cutoff_instant]
        self.instant_db = round(float(np.max(instant_vals)), 2) if instant_vals else self.current_db
        self.baseline_db = round(float(np.mean(prior_baseline)), 2) if prior_baseline else self.current_db

        self.delta_db = round(self.instant_db - self.baseline_db, 2)
        spike_flag = self.delta_db >= self.jump_db_threshold

        if spike_flag and not self.is_spiking:
            self.is_spiking = True
            logger.info(
                "[AudioMonitor] VOLUME SPIKE DETECTED: instant=%.1f dB, baseline=%.1f dB (delta=+%.1f dB)",
                self.instant_db,
                self.baseline_db,
                self.delta_db,
            )
            if self.on_spike:
                try:
                    self.on_spike(self.instant_db, self.delta_db)
                except Exception as e:
                    logger.error("[AudioMonitor] on_spike callback error: %s", e)
        elif not spike_flag:
            self.is_spiking = False

        return {
            "current_db": self.current_db,
            "instant_db": self.instant_db,
            "baseline_db": self.baseline_db,
            "delta_db": self.delta_db,
            "is_spiking": self.is_spiking,
        }

    def process_segment(self, segment_path: str) -> Optional[dict]:
        """Extracts and analyzes audio from a video segment."""
        samples = self.extract_pcm_from_media(segment_path)
        if samples is not None and len(samples) > 0:
            return self.process_samples(samples)
        return None
