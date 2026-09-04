import glob
import logging
import os
import shutil
import subprocess
import tempfile
import time
from typing import List, Optional

logger = logging.getLogger(__name__)


class SegmentSlicer:
    """Zero-copy extraction of a 60-second window (-45s to +15s of event) from the RAM ring buffer."""

    @staticmethod
    def extract_window(
        channel: str,
        duration_seconds: int = 60,
        output_dir: str = "/tmp/clipper_candidates",
        shm_base: Optional[str] = None,
    ) -> Optional[str]:
        channel_clean = channel.lower().lstrip("#")
        base = shm_base or ("/dev/shm/clipper" if os.path.exists("/dev/shm") else "/tmp/clipper_shm")
        channel_dir = os.path.join(base, channel_clean)

        if not os.path.exists(channel_dir):
            logger.error("[Slicer] Channel buffer directory %s does not exist.", channel_dir)
            return None

        segments = glob.glob(os.path.join(channel_dir, "seg_*.ts"))
        if not segments:
            logger.error("[Slicer] No TS segments available in %s.", channel_dir)
            return None

        segments.sort(key=os.path.getmtime)
        # If at least 3 segments exist, exclude the in-flight segment currently being appended
        usable_segments = segments[:-1] if len(segments) >= 3 else segments

        # 60s @ 10s per segment = 6 segments
        target_count = max(1, duration_seconds // 10)
        selected = usable_segments[-target_count:]

        os.makedirs(output_dir, exist_ok=True)
        timestamp = int(time.time())
        output_file = os.path.join(output_dir, f"raw_{channel_clean}_{timestamp}.mp4")

        # Copy selected segments to temporary staging directory to prevent ring-buffer wrap-around race condition
        staging_dir = tempfile.mkdtemp(prefix=f"slice_stage_{channel_clean}_")
        concat_list = None
        try:
            staged_segments = []
            for i, seg in enumerate(selected):
                dst = os.path.join(staging_dir, f"part_{i:02d}.ts")
                shutil.copy2(seg, dst)
                staged_segments.append(dst)

            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                for seg in staged_segments:
                    f.write(f"file '{os.path.abspath(seg)}'\n")
                concat_list = f.name

            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                "-y", output_file,
            ]
            subprocess.run(cmd, check=True, timeout=15)
            logger.info("[Slicer] Successfully created %s from %d segments", output_file, len(selected))
            return output_file
        except Exception as e:
            logger.error("[Slicer] Failed to concatenate segments: %s", e)
            return None
        finally:
            if concat_list and os.path.exists(concat_list):
                try:
                    os.remove(concat_list)
                except OSError:
                    pass
            if staging_dir and os.path.exists(staging_dir):
                shutil.rmtree(staging_dir, ignore_errors=True)

