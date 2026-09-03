import glob
import logging
import os
import subprocess
import time
from typing import Optional
from services.ingest.stream_buffer import get_default_shm_dir

logger = logging.getLogger(__name__)


class SegmentSlicer:
    """Extracts and concatenates the target slice from the ring buffer without re-encoding."""

    @staticmethod
    def extract_window(
        channel: str,
        duration_seconds: int = 60,
        shm_dir: Optional[str] = None,
        output_dir: str = "/tmp/clipper_candidates",
    ) -> Optional[str]:
        """Concatenates the latest MPEG-TS segments covering the candidate duration."""
        base_shm = shm_dir or get_default_shm_dir()
        target_dir = os.path.join(base_shm, channel.lower().lstrip("#"))
        os.makedirs(output_dir, exist_ok=True)

        if not os.path.exists(target_dir):
            logger.warning("[Slicer] Buffer directory does not exist: %s", target_dir)
            return None

        # Order segments chronologically by modification time
        segments = glob.glob(os.path.join(target_dir, "seg_*.ts"))
        if not segments:
            logger.warning("[Slicer] No segments found in %s", target_dir)
            return None

        segments.sort(key=os.path.getmtime)

        # 10 seconds per segment + 1 safety segment
        needed = (duration_seconds // 10) + 1
        selected = segments[-needed:] if len(segments) >= needed else segments

        timestamp = int(time.time())
        out_file = os.path.join(output_dir, f"raw_{channel}_{timestamp}.mp4")
        concat_manifest = os.path.join(output_dir, f"concat_{timestamp}.txt")

        try:
            with open(concat_manifest, "w") as f:
                for seg in selected:
                    abs_path = os.path.abspath(seg)
                    f.write(f"file '{abs_path}'\n")

            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_manifest,
                "-c", "copy",
                "-movflags", "+faststart",
                "-y",
                out_file,
            ]
            subprocess.run(cmd, check=True)
            logger.info(
                "[Slicer] Extracted candidate %s (%d segments, ~%ds)",
                out_file,
                len(selected),
                len(selected) * 10,
            )
            return out_file
        except Exception as err:
            logger.error("[Slicer] Concatenation failed: %s", err)
            return None
        finally:
            if os.path.exists(concat_manifest):
                try:
                    os.remove(concat_manifest)
                except OSError:
                    pass
