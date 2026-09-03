import glob
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from typing import List, Optional

logger = logging.getLogger(__name__)


def get_default_shm_dir() -> str:
    """Select appropriate high-speed temporary buffer directory across platforms."""
    if os.path.exists("/dev/shm") and os.access("/dev/shm", os.W_OK):
        return "/dev/shm/clipper"
    return os.path.join("/tmp", "clipper_shm")


def resolve_streamlink_binary() -> str:
    """Locates the streamlink executable from the active Python virtualenv or system PATH."""
    venv_bin = os.path.join(os.path.dirname(sys.executable), "streamlink")
    if os.path.exists(venv_bin) and os.access(venv_bin, os.X_OK):
        return venv_bin

    which_bin = shutil.which("streamlink")
    if which_bin:
        return which_bin

    # Fallback to invoking module through python
    return f'"{sys.executable}" -m streamlink'


class StreamRingBuffer:
    """Maintains a rolling MPEG-TS video buffer in RAM using streamlink + ffmpeg."""

    def __init__(
        self,
        channel: str,
        shm_dir: Optional[str] = None,
        window_seconds: int = 180,
        segment_time: int = 10,
        simulate: bool = False,
    ):
        self.channel = channel.lower().lstrip("#")
        base_dir = shm_dir or get_default_shm_dir()
        self.shm_dir = os.path.join(base_dir, self.channel)
        self.window_seconds = window_seconds
        self.segment_time = segment_time
        self.segment_wrap = max(1, self.window_seconds // self.segment_time)
        self.simulate = simulate or (self.channel in ("test", "demo") or os.getenv("SIMULATE_STREAM", "false").lower() == "true")

        self.process: Optional[subprocess.Popen] = None
        self.running = False
        self._watchdog_thread: Optional[threading.Thread] = None

    def _build_env(self) -> dict:
        """Constructs environment with venv and standard binary directories on PATH."""
        env = dict(os.environ)
        venv_dir = os.path.dirname(sys.executable)
        paths = [venv_dir, "/opt/homebrew/bin", "/usr/local/bin", env.get("PATH", "")]
        env["PATH"] = ":".join(p for p in paths if p)
        return env

    def _start_ingest_process(self):
        """Starts the stream ingestion or simulation subprocess."""
        os.makedirs(self.shm_dir, exist_ok=True)
        out_pattern = os.path.join(self.shm_dir, "seg_%02d.ts")

        if self.simulate:
            logger.info("[Buffer] Running in STREAM SIMULATION mode (synthetic live stream)...")
            cmd = (
                f'ffmpeg -hide_banner -loglevel error '
                f'-re -f lavfi -i "testsrc=size=1920x1080:rate=30" '
                f'-f lavfi -i "sine=frequency=440:sample_rate=16000" '
                f'-c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p '
                f'-c:a aac -b:a 128k '
                f'-f segment -segment_time {self.segment_time} '
                f'-segment_wrap {self.segment_wrap} -y "{out_pattern}"'
            )
        else:
            streamlink_bin = resolve_streamlink_binary()
            cmd = (
                f'{streamlink_bin} --retry-streams 15 --retry-open 5 '
                f'"twitch.tv/{self.channel}" best -o - | '
                f'ffmpeg -hide_banner -loglevel error -i - '
                f'-c copy -f segment -segment_time {self.segment_time} '
                f'-segment_wrap {self.segment_wrap} -y "{out_pattern}"'
            )

        logger.info(
            "[Buffer] Initializing ingest for %s -> %d segments (%ds total) at %s",
            self.channel,
            self.segment_wrap,
            self.window_seconds,
            self.shm_dir,
        )

        self.process = subprocess.Popen(
            cmd,
            shell=True,
            env=self._build_env(),
            preexec_fn=os.setsid if platform.system() != "Windows" else None,
        )

    def _watchdog_loop(self):
        """Monitors the ingestion process and restarts if the stream disconnects."""
        while self.running:
            if not self.is_alive():
                if self.running:
                    logger.info("[Buffer] Streamer #%s is currently offline or stream disconnected. Retrying in 15s...", self.channel)
                    time.sleep(15)
                    if self.running:
                        self._start_ingest_process()
            time.sleep(2)

    def start(self):
        """Starts ingestion and launches the background supervisor watchdog."""
        self.running = True
        self._start_ingest_process()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def is_alive(self) -> bool:
        """Returns True if the ingestion pipeline is actively running."""
        return self.process is not None and self.process.poll() is None

    def get_active_segments(self) -> List[str]:
        """Returns all existing TS segments ordered chronologically by modification time."""
        if not os.path.exists(self.shm_dir):
            return []
        segments = glob.glob(os.path.join(self.shm_dir, "seg_*.ts"))
        segments.sort(key=os.path.getmtime)
        return segments

    def get_latest_segment(self) -> Optional[str]:
        """Returns the path to the newest TS segment in the buffer."""
        segments = self.get_active_segments()
        return segments[-1] if segments else None

    def stop(self):
        """Terminates the process group and wipes temporary video segments."""
        self.running = False
        if self.process:
            try:
                if platform.system() != "Windows":
                    os.killpg(os.getpgid(self.process.pid), 15)
                else:
                    self.process.terminate()
                self.process.wait(timeout=5)
            except Exception as e:
                logger.debug("[Buffer] Error terminating process: %s", e)
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

        shutil.rmtree(self.shm_dir, ignore_errors=True)
        logger.info("[Buffer] Stopped and wiped buffer for %s", self.channel)
