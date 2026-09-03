import logging
import math
import subprocess
from typing import Callable, Optional
import numpy as np

logger = logging.getLogger(__name__)


class AudioDecibelMonitor:
    """Demuxes raw audio from TS segments and calculates rolling RMS decibels to detect scream/reaction spikes."""

    def __init__(
        self,
        jump_db_threshold: float = 12.0,
        baseline_db: float = -32.0,
        sample_rate: int = 16000,
        on_spike_callback: Optional[Callable[[float, float], None]] = None,
    ):
        self.jump_db_threshold = jump_db_threshold
        self.baseline_db = baseline_db
        self.sample_rate = sample_rate
        self.on_spike = on_spike_callback

        self.current_db = -60.0
        self.delta_db = 0.0
        self.is_spiking = False

    def process_segment(self, segment_path: str) -> Optional[dict]:
        """Extracts 16kHz mono PCM audio and computes the peak RMS decibel jump."""
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-i", segment_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", str(self.sample_rate),
            "-ac", "1",
            "-f", "s16le",
            "-",
        ]

        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
            raw_pcm = p.stdout
            if not raw_pcm or len(raw_pcm) < 3200:
                return None

            samples = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32)
            rms = np.sqrt(np.mean(samples ** 2))
            if rms < 1e-4:
                instant_db = -90.0
            else:
                instant_db = 20.0 * math.log10(rms / 32768.0)

            self.current_db = round(float(instant_db), 1)
            self.delta_db = round(self.current_db - self.baseline_db, 1)

            # Adapt rolling baseline slowly
            self.baseline_db = 0.90 * self.baseline_db + 0.10 * self.current_db

            # Spike detection
            self.is_spiking = self.delta_db >= self.jump_db_threshold
            if self.is_spiking and self.on_spike:
                try:
                    self.on_spike(self.current_db, self.delta_db)
                except Exception as err:
                    logger.error("[Audio] Callback error: %s", err)

            # Downsample to 64 normalized waveform points [-1.0, 1.0]
            step = max(1, len(samples) // 64)
            waveform = [round(float(s) / 32768.0, 3) for s in samples[::step][:64]]

            return {
                "current_db": self.current_db,
                "baseline_db": round(self.baseline_db, 1),
                "delta_db": self.delta_db,
                "is_spiking": self.is_spiking,
                "waveform": waveform,
            }
        except Exception as e:
            logger.debug("[Audio] Error processing segment %s: %s", segment_path, e)
            return None
