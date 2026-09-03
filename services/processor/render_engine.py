import logging
import os
import platform
import subprocess
import tempfile
from typing import List
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


def detect_optimal_encoder() -> str:
    """Detects available hardware video encoders (Apple Silicon videotoolbox, NVIDIA nvenc, or libx264)."""
    custom = os.getenv("VIDEO_ENCODER", "auto").lower()
    if custom in ("videotoolbox", "h264_videotoolbox"):
        return "h264_videotoolbox"
    if custom in ("nvenc", "h264_nvenc"):
        return "h264_nvenc"
    if custom in ("libx264", "cpu"):
        return "libx264"

    try:
        res = subprocess.run(["ffmpeg", "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        out = res.stdout
        if "h264_videotoolbox" in out and platform.system() == "Darwin":
            logger.info("[Render] Selected Apple Silicon hardware acceleration: h264_videotoolbox")
            return "h264_videotoolbox"
        if "h264_nvenc" in out:
            logger.info("[Render] Selected NVIDIA hardware acceleration: h264_nvenc")
            return "h264_nvenc"
    except Exception:
        pass

    logger.info("[Render] Selected CPU encoder: libx264")
    return "libx264"


def check_ffmpeg_filter(filter_name: str) -> bool:
    """Checks if a specific filter is compiled into FFmpeg using exact filter lookup."""
    try:
        res = subprocess.run(
            ["ffmpeg", "-h", f"filter={filter_name}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
        )
        return (
            res.returncode == 0
            and f"Unknown filter '{filter_name}'" not in res.stderr
            and f"Unknown filter '{filter_name}'" not in res.stdout
        )
    except Exception:
        return False


class HardwareRenderEngine:
    """Renders full-sized, uncropped stream clips with frame-accurate hardware acceleration."""

    @staticmethod
    def get_duration(filepath: str) -> float:
        """Returns exact media duration in seconds using ffprobe."""
        if not filepath or not os.path.exists(filepath):
            return 0.0
        try:
            import json
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json", filepath
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
            data = json.loads(res.stdout)
            return float(data.get("format", {}).get("duration", 0.0))
        except Exception:
            return 0.0

    @staticmethod
    def format_ass_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    @classmethod
    def generate_ass_subtitles(cls, words: List[dict], cut_start: float, output_path: str):
        """Generates karaoke-style ASS subtitles shifted relative to clip start."""
        header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Arial Black,48,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,40,40,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = []
        chunk = []
        for w in words:
            w_start = w["start"] - cut_start
            w_end = w["end"] - cut_start
            if w_end < 0:
                continue
            chunk.append((w["word"], max(0.0, w_start), max(0.0, w_end)))

            if len(chunk) >= 4 or w["word"].endswith((".", "!", "?")):
                c_start = chunk[0][1]
                c_end = chunk[-1][2]
                text = " ".join(item[0].upper() for item in chunk)
                lines.append(f"Dialogue: 0,{cls.format_ass_time(c_start)},{cls.format_ass_time(c_end)},Karaoke,,0,0,0,,{text}")
                chunk = []

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write("\n".join(lines) + "\n")

    @classmethod
    def create_badge_overlay(cls, text: str, output_path: str, width: int = 1920, height: int = 1080):
        """Generates a transparent PNG with a styled gaming/win badge at the top of the widescreen frame."""
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        box_w, box_h = 560, 75
        box_x = (width - box_w) // 2
        box_y = 40

        draw.rounded_rectangle(
            [box_x, box_y, box_x + box_w, box_y + box_h],
            radius=14,
            fill=(10, 14, 23, 210),
            outline=(56, 189, 248, 255),
            width=3,
        )

        try:
            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 32)
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        text_x = box_x + (box_w - text_w) // 2
        text_y = box_y + (box_h - text_h) // 2

        draw.text((text_x, text_y), text, fill=(255, 255, 255), font=font)
        img.save(output_path, "PNG")

    @classmethod
    def render_clip(
        cls,
        source_path: str,
        cut_start: float,
        cut_end: float,
        output_path: str,
        words: List[dict] = None,
        pnl_text: str = "",
        enable_subs: bool = False,
        crop_vertical: bool = False,
    ) -> bool:
        """Renders the clip in full original resolution without cropping by default."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        duration = max(1.0, cut_end - cut_start)
        encoder = detect_optimal_encoder()

        temp_ass = None
        temp_badge = None
        inputs = ["-ss", str(cut_start), "-i", source_path]
        filter_parts = []
        current_pad = "[0:v]"

        # Optional vertical cropping (only if explicitly requested)
        if crop_vertical:
            filter_parts.append(f"{current_pad}crop=ih*9/16:ih:(iw-ow)/2:0,scale=1080:1920[v_base]")
            current_pad = "[v_base]"

        has_ass_filter = check_ffmpeg_filter("ass")
        if enable_subs and words and has_ass_filter:
            with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
                temp_ass = f.name
            cls.generate_ass_subtitles(words, cut_start, temp_ass)
            filter_parts.append(f"{current_pad}ass='{temp_ass}'[v_subs]")
            current_pad = "[v_subs]"

        if pnl_text:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                temp_badge = f.name
            cls.create_badge_overlay(pnl_text, temp_badge, width=1920, height=1080)
            inputs.extend(["-i", temp_badge])
            filter_parts.append(f"{current_pad}[1:v]overlay=0:0[v_out]")
            current_pad = "[v_out]"

        if filter_parts:
            filter_args = [
                "-filter_complex", ";".join(filter_parts),
                "-map", current_pad,
                "-map", "0:a?",
            ]
        else:
            filter_args = []

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            *inputs,
            "-t", str(duration),
            *filter_args,
            "-c:v", encoder,
            "-b:v", "6M",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-y", output_path,
        ]

        mode_str = "9:16 vertical" if crop_vertical else "Full-Sized (Uncropped)"
        logger.info("[Render] Rendering clip [%.1fs - %.1fs] -> %s (Mode: %s, encoder: %s)", cut_start, cut_end, output_path, mode_str, encoder)
        try:
            subprocess.run(cmd, check=True, timeout=90)
            success = os.path.exists(output_path) and os.path.getsize(output_path) > 0
            if success:
                logger.info("[Render] Render complete: %s (%d bytes)", output_path, os.path.getsize(output_path))
            return success
        except Exception as e:
            logger.error("[Render] Rendering failed: %s", e)
            return False
        finally:
            for tmp in (temp_ass, temp_badge):
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

    # Backward-compatible alias
    @classmethod
    def render_vertical(cls, *args, **kwargs):
        """Preserved for backward compatibility, defaults to uncropped full-sized rendering."""
        kwargs.setdefault("crop_vertical", False)
        return cls.render_clip(*args, **kwargs)

    @classmethod
    def extract_thumbnail(cls, video_path: str, thumb_path: str, offset_seconds: float = 1.5):
        """Extracts a poster thumbnail frame from the rendered clip."""
        if not os.path.exists(video_path):
            logger.error("[Render] Cannot extract thumbnail: source video %s does not exist", video_path)
            return False
        os.makedirs(os.path.dirname(os.path.abspath(thumb_path)), exist_ok=True)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-ss", str(offset_seconds),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            "-y", thumb_path,
        ]
        try:
            subprocess.run(cmd, check=True, timeout=10)
            return os.path.exists(thumb_path)
        except Exception as e:
            logger.error("[Render] Failed to extract thumbnail: %s", e)
            return False
