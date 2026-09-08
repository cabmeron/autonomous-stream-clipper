import glob
import logging
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def clean_channel_name(raw: str) -> str:
    """Extracts a normalized alphanumeric Twitch channel name from raw strings, URLs, or tags.

    Examples:
        'https://www.twitch.tv/ponden' -> 'ponden'
        'twitch.tv/ponden/'           -> 'ponden'
        '#marlon'                     -> 'marlon'
        '@marlon'                     -> 'marlon'
        'zarbex'                      -> 'zarbex'
    """
    if not raw:
        return ""
    s = str(raw).strip()
    lower_s = s.lower()
    if "twitch.tv/" in lower_s:
        s = lower_s.split("twitch.tv/", 1)[1]
        s = s.split("?")[0].split("#")[0].split("/")[0]
    elif lower_s.startswith("http://") or lower_s.startswith("https://"):
        try:
            p = urlparse(s)
            parts = [part for part in p.path.split("/") if part]
            if parts:
                s = parts[0]
        except Exception:
            pass
    s = re.sub(r"^[@#]+", "", s).strip()
    s = s.split("?")[0].split("/")[0]
    s = re.sub(r"[^a-zA-Z0-9_]", "", s)
    return s.lower()


def get_default_shm_dir() -> str:
    """Select appropriate high-speed temporary buffer directory across platforms."""
    if os.path.exists("/dev/shm") and os.access("/dev/shm", os.W_OK):
        return "/dev/shm/clipper"
    return os.path.join("/tmp", "clipper_shm")


def resolve_streamlink_binary() -> str:
    """Locates the streamlink executable from the active Python virtualenv or system PATH."""
    candidates = [
        os.path.join(os.path.dirname(sys.executable), "streamlink"),
        shutil.which("streamlink"),
        "/opt/homebrew/bin/streamlink",
        "/usr/local/bin/streamlink",
        os.path.join(os.getcwd(), "venv", "bin", "streamlink"),
        os.path.join(os.getcwd(), ".venv", "bin", "streamlink"),
        "/Users/user2/Documents/Projects/clipper/venv/bin/streamlink",
        "/Users/user2/Documents/Projects/autonomous-stream-clipper/venv/bin/streamlink",
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.access(c, os.X_OK):
            return c

    for venv_py in (
        os.path.join(os.getcwd(), "venv", "bin", "python3"),
        "/Users/user2/Documents/Projects/clipper/venv/bin/python3",
    ):
        if os.path.exists(venv_py):
            return f'"{venv_py}" -m streamlink'

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
        self.channel = clean_channel_name(channel)
        base_dir = shm_dir or get_default_shm_dir()
        self.shm_dir = os.path.join(base_dir, self.channel)
        self.window_seconds = window_seconds
        self.segment_time = segment_time
        self.segment_wrap = max(1, self.window_seconds // self.segment_time)

        # Auto-detect simulation streams (demo, sim_, _reacts, watch_, or explicit simulate flag)
        is_sim = (
            simulate
            or self.channel in ("test", "demo", "test1", "test2")
            or self.channel.startswith("sim_")
            or "_reacts" in self.channel
            or "watch_" in self.channel
            or "react_" in self.channel
            or os.getenv("SIMULATE_STREAM", "false").lower() == "true"
        )
        self.simulate = bool(is_sim)
        self.is_standby = False

        self.process: Optional[subprocess.Popen] = None
        self.running = False
        self._watchdog_thread: Optional[threading.Thread] = None

        # Exponential backoff parameters for checking if offline streams have gone live
        self.min_offline_check_interval: float = 10.0   # Start checking after 10s
        self.max_offline_check_interval: float = 120.0  # Cap check interval at 120s (2 min)
        self.offline_backoff_factor: float = 1.8        # Backoff multiplier
        self.current_offline_interval: float = self.min_offline_check_interval
        self._next_live_check_time: float = 0.0

        # Exponential backoff parameters for process restart failures
        self.min_restart_interval: float = 5.0
        self.max_restart_interval: float = 60.0
        self.restart_backoff_factor: float = 2.0
        self.current_restart_interval: float = self.min_restart_interval
        self._last_process_start_time: float = 0.0

    def _build_env(self) -> dict:
        """Constructs environment with venv and standard binary directories on PATH."""
        env = dict(os.environ)
        venv_dir = os.path.dirname(sys.executable)
        paths = [venv_dir, "/opt/homebrew/bin", "/usr/local/bin", env.get("PATH", "")]
        env["PATH"] = ":".join(p for p in paths if p)
        return env

    def _resolve_live_m3u8(self) -> Optional[str]:
        """Queries streamlink for the direct Twitch HLS playlist URL."""
        streamlink_bin = resolve_streamlink_binary()
        try:
            res = subprocess.run(
                f'{streamlink_bin} --stream-url "twitch.tv/{self.channel}" best',
                shell=True,
                capture_output=True,
                text=True,
                timeout=7.0,
                env=self._build_env(),
            )
            if res.returncode == 0 and res.stdout.strip().startswith("http"):
                return res.stdout.strip()
        except Exception as e:
            logger.debug("[Buffer:%s] Error resolving stream URL: %s", self.channel, e)
        return None

    def _start_ingest_process(self):
        """Starts the stream ingestion or simulation subprocess."""
        os.makedirs(self.shm_dir, exist_ok=True)
        out_pattern = os.path.join(self.shm_dir, "seg_%02d.ts")
        self._last_process_start_time = time.time()

        if self.simulate:
            self.is_standby = False
            logger.info("[Buffer:%s] Running in SIMULATION mode (synthetic 1080p stream)...", self.channel)
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
            # Check if live stream is actively broadcasting
            live_url = self._resolve_live_m3u8()
            if live_url:
                self.is_standby = False
                self.current_offline_interval = self.min_offline_check_interval
                logger.info("[Buffer:%s] Live Twitch broadcast detected! Ingesting direct HLS stream...", self.channel)
                cmd = (
                    f'ffmpeg -hide_banner -loglevel error '
                    f'-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 5 '
                    f'-i "{live_url}" '
                    f'-c copy -f segment -segment_time {self.segment_time} '
                    f'-segment_wrap {self.segment_wrap} -y "{out_pattern}"'
                )
            else:
                self.is_standby = True
                self.current_offline_interval = self.min_offline_check_interval
                self._next_live_check_time = time.time() + self.current_offline_interval
                logger.info(
                    "[Buffer:%s] Channel is currently OFFLINE on Twitch. Running standby feed until stream goes live (first check in %.1fs)...",
                    self.channel,
                    self.current_offline_interval,
                )
                cmd = (
                    f'ffmpeg -hide_banner -loglevel error '
                    f'-re -f lavfi -i "testsrc=size=1920x1080:rate=30" '
                    f'-f lavfi -i "sine=frequency=220:sample_rate=16000" '
                    f'-c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p '
                    f'-c:a aac -b:a 64k '
                    f'-f segment -segment_time {self.segment_time} '
                    f'-segment_wrap {self.segment_wrap} -y "{out_pattern}"'
                )

        logger.info(
            "[Buffer:%s] Initializing ingest -> %d segments (%ds total) at %s",
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
        """Monitors the ingestion process and checks if offline streams go live with exponential backoff."""
        while self.running:
            now = time.time()

            # 1. Standby state: channel is offline, poll for stream going live using exponential backoff
            if self.is_standby and not self.simulate:
                if now >= self._next_live_check_time:
                    live_url = self._resolve_live_m3u8()
                    if live_url:
                        logger.info(
                            "[Buffer:%s] Channel has gone LIVE! Switching from standby to live Twitch feed...",
                            self.channel,
                        )
                        self.current_offline_interval = self.min_offline_check_interval
                        if self.process:
                            try:
                                if platform.system() != "Windows":
                                    try:
                                        pgid = os.getpgid(self.process.pid)
                                        if pgid != os.getpgrp() and pgid > 1:
                                            os.killpg(pgid, 15)
                                        else:
                                            self.process.terminate()
                                    except (ProcessLookupError, OSError):
                                        self.process.terminate()
                                else:
                                    self.process.terminate()
                            except Exception:
                                pass
                        self._start_ingest_process()
                    else:
                        # Stream remains offline: schedule next check with exponential backoff and jitter
                        jitter = random.uniform(-0.1, 0.1) * self.current_offline_interval
                        effective_delay = max(
                            self.min_offline_check_interval,
                            min(self.max_offline_check_interval, self.current_offline_interval + jitter),
                        )
                        self._next_live_check_time = now + effective_delay
                        logger.info(
                            "[Buffer:%s] Channel still offline. Next live check in %.1fs (exponential backoff, cap %ds)",
                            self.channel,
                            effective_delay,
                            int(self.max_offline_check_interval),
                        )
                        # Advance backoff interval for next cycle
                        self.current_offline_interval = min(
                            self.max_offline_check_interval,
                            self.current_offline_interval * self.offline_backoff_factor,
                        )

            # 2. Check if the ingest process ended unexpectedly
            if not self.is_alive():
                if self.running:
                    uptime = now - self._last_process_start_time
                    if uptime < 15.0:
                        restart_delay = self.current_restart_interval
                        self.current_restart_interval = min(
                            self.max_restart_interval,
                            self.current_restart_interval * self.restart_backoff_factor,
                        )
                    else:
                        self.current_restart_interval = self.min_restart_interval
                        restart_delay = self.min_restart_interval

                    logger.info(
                        "[Buffer:%s] Ingest process ended. Restarting in %.1fs (backoff)...",
                        self.channel,
                        restart_delay,
                    )
                    # Sleep in small ticks to remain responsive to stop()
                    sleep_deadline = time.time() + restart_delay
                    while self.running and time.time() < sleep_deadline:
                        time.sleep(0.5)

                    if self.running:
                        self._start_ingest_process()

            time.sleep(1.0)

    def start(self):
        """Starts ingestion and launches the background supervisor watchdog."""
        self.running = True
        self._start_ingest_process()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def is_alive(self) -> bool:
        """Returns True if the ingestion pipeline is actively running."""
        return self.process is not None and self.process.poll() is None

    def get_segment_count(self) -> int:
        """Returns the count of buffered TS segments without sorting or stat calls."""
        if not os.path.exists(self.shm_dir):
            return 0
        try:
            with os.scandir(self.shm_dir) as it:
                return sum(1 for entry in it if entry.name.startswith("seg_") and entry.name.endswith(".ts"))
        except OSError:
            return 0

    def get_active_segments(self) -> List[str]:
        """Returns all existing TS segments ordered chronologically by modification time."""
        if not os.path.exists(self.shm_dir):
            return []
        segments = glob.glob(os.path.join(self.shm_dir, "seg_*.ts"))
        segments.sort(key=os.path.getmtime)
        return segments

    def get_latest_segment(self) -> Optional[str]:
        """Returns the newest fully written TS segment in the buffer."""
        segments = self.get_active_segments()
        if not segments:
            return None
        # If multiple segments exist, return the second to last because FFmpeg is actively appending to the last one
        if len(segments) >= 2:
            return segments[-2]
        return segments[-1]

    def stop(self):
        """Terminates the process group and wipes temporary video segments."""
        self.running = False
        if self.process:
            try:
                if platform.system() != "Windows":
                    try:
                        pgid = os.getpgid(self.process.pid)
                        if pgid != os.getpgrp() and pgid > 1:
                            os.killpg(pgid, 15)
                        else:
                            self.process.terminate()
                    except (ProcessLookupError, OSError):
                        self.process.terminate()
                else:
                    self.process.terminate()
                self.process.wait(timeout=5)
            except Exception as e:
                logger.debug("[Buffer:%s] Error terminating process: %s", self.channel, e)
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

        shutil.rmtree(self.shm_dir, ignore_errors=True)
        logger.info("[Buffer:%s] Stopped and wiped buffer", self.channel)
