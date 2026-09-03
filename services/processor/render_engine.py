import logging
import os
import platform
import subprocess
import tempfile
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


def detect_optimal_encoder() -> str:
    """Detects available hardware accelerated video encoders via ffmpeg."""
    override = os.getenv("VIDEO_ENCODER", "auto").lower()
    if override in ("nvenc", "h264_nvenc"):
        return "h264_nvenc"
    if override in ("videotoolbox", "h264_videotoolbox"):
        return "h264_videotoolbox"
    if override in ("libx264", "cpu"):
        return "libx264"

    try:
        res = subprocess.run(["ffmpeg", "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        encoders = res.stdout.lower()
        if platform.system() == "Darwin" and "h264_videotoolbox" in encoders:
            return "h264_videotoolbox"
        if "h264_nvenc" in encoders:
            return "h264_nvenc"
    except Exception:
        pass
    return "libx264"


def check_filter_support(filter_name: str) -> bool:
    """Checks whether the local FFmpeg build contains a specific filter."""
    try:
        res = subprocess.run(["ffmpeg", "-filters"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return f" {filter_name} " in res.stdout
    except Exception:
        return False


def format_ass_time(seconds: float) -> str:
    """Formats seconds into ASS timestamp: H:MM:SS.cs"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


class HardwareRenderEngine:
    """Crops 16:9 to 9:16, burns in dynamic ASS subtitles and badges, and encodes with hardware acceleration."""

    @staticmethod
    def generate_ass_subtitles(words: List[dict], cut_start: float, cut_end: float, ass_path: str):
        """Generates an Advanced SubStation Alpha (.ass) subtitle file with word-by-word dynamic timing."""
        header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,54,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,0,2,60,60,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        # Group words within [cut_start, cut_end] into short lines (3-4 words each)
        relevant_words = [
            w for w in words
            if w.get("start", 0) >= cut_start - 0.5 and w.get("end", 0) <= cut_end + 0.5
        ]

        dialogue_lines = []
        chunk_size = 4
        for i in range(0, len(relevant_words), chunk_size):
            chunk = relevant_words[i:i + chunk_size]
            if not chunk:
                continue
            line_start = max(0.0, chunk[0]["start"] - cut_start)
            line_end = max(line_start + 0.5, chunk[-1]["end"] - cut_start)

            # Build line text with uppercase style
            text = " ".join(w["word"].upper() for w in chunk)
            start_str = format_ass_time(line_start)
            end_str = format_ass_time(line_end)
            dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}")

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(dialogue_lines) + "\n")

    @staticmethod
    def create_badge_image(badge_text: str, output_png: str):
        """Creates a transparent 1080x1920 PNG with a styled badge pill for FFmpeg overlay."""
        img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Attempt to load a bold font or fallback
        font = None
        font_paths = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/SFNS.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    font = ImageFont.truetype(fp, 46)
                    break
                except Exception:
                    pass
        if font is None:
            font = ImageFont.load_default()

        # Compute text bounding box
        bbox = draw.textbbox((0, 0), badge_text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        # Draw centered badge pill at y=180
        cx = 1080 // 2
        cy = 180
        pad_x = 28
        pad_y = 16
        pill_rect = [cx - (tw // 2) - pad_x, cy - pad_y, cx + (tw // 2) + pad_x, cy + th + pad_y]

        draw.rounded_rectangle(pill_rect, radius=16, fill=(0, 0, 0, 180), outline=(255, 255, 255, 60), width=2)
        draw.text((cx - (tw // 2), cy), badge_text, font=font, fill=(255, 255, 255, 255))
        img.save(output_png, "PNG")

    @classmethod
    def render_vertical(
        cls,
        source_path: str,
        cut_start: float,
        cut_end: float,
        output_path: str,
        words: Optional[List[dict]] = None,
        pnl_text: str = "",
        enable_subs: bool = True,
    ) -> str:
        """Crops landscape video to 9:16, applies subtitle and badge filters, and renders vertical MP4."""
        duration = max(1.0, cut_end - cut_start)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        encoder = detect_optimal_encoder()

        has_ass = check_filter_support("ass")
        has_drawtext = check_filter_support("drawtext")
        has_overlay = check_filter_support("overlay")

        ass_path = None
        badge_png = None
        temp_files = []

        try:
            # Base 9:16 crop filter
            base_filter = "crop=in_h*(9/16):in_h:(in_w-out_w)/2:0,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"

            filter_complex = None
            input_args = ["-ss", str(cut_start), "-t", str(duration), "-i", source_path]

            # 1. Subtitles handling
            if enable_subs and words and has_ass:
                ass_path = output_path + ".ass"
                cls.generate_ass_subtitles(words, cut_start, cut_end, ass_path)
                temp_files.append(ass_path)
                escaped_ass = ass_path.replace(":", "\\:").replace("'", "\\'")
                base_filter += f",ass=filename='{escaped_ass}'"
            elif enable_subs and words and not has_ass:
                logger.debug("[RenderEngine] 'ass' filter not available in FFmpeg build; skipping subtitle burn-in.")

            # 2. Badge handling
            if pnl_text:
                if has_drawtext:
                    clean_text = pnl_text.replace("'", "").replace(":", "-")
                    base_filter += (
                        f",drawtext=text='{clean_text}':fontcolor=white:fontsize=46:"
                        f"box=1:boxcolor=black@0.7:boxborderw=14:x=(w-text_w)/2:y=180"
                    )
                elif has_overlay:
                    # Universal fallback using transparent PNG overlay
                    badge_png = output_path + "_badge.png"
                    cls.create_badge_image(pnl_text, badge_png)
                    temp_files.append(badge_png)
                    input_args.extend(["-i", badge_png])
                    filter_complex = f"[0:v]{base_filter}[base];[base][1:v]overlay=0:0[outv]"

            # Build encoder arguments
            if encoder == "h264_videotoolbox":
                enc_args = ["-c:v", "h264_videotoolbox", "-b:v", "6M", "-maxrate", "8M", "-bufsize", "12M"]
            elif encoder == "h264_nvenc":
                enc_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "21", "-b:v", "6M", "-maxrate", "8M", "-bufsize", "12M"]
            else:
                enc_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"]

            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", *input_args]
            if filter_complex:
                cmd.extend(["-filter_complex", filter_complex, "-map", "[outv]", "-map", "0:a?"])
            else:
                cmd.extend(["-vf", base_filter])

            cmd.extend([*enc_args, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-y", output_path])

            logger.info("[RenderEngine] Rendering 9:16 clip with %s (duration: %.1fs)...", encoder, duration)
            subprocess.run(cmd, check=True)
            logger.info("[RenderEngine] Render completed successfully: %s", output_path)
            return output_path

        finally:
            for tf in temp_files:
                if os.path.exists(tf):
                    try:
                        os.remove(tf)
                    except OSError:
                        pass

    @staticmethod
    def extract_thumbnail(video_path: str, thumbnail_path: str, offset_seconds: float = 1.5) -> Optional[str]:
        """Extracts a poster frame thumbnail from the rendered clip."""
        os.makedirs(os.path.dirname(os.path.abspath(thumbnail_path)), exist_ok=True)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-ss", str(offset_seconds),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            "-y",
            thumbnail_path,
        ]
        try:
            subprocess.run(cmd, check=True)
            return thumbnail_path
        except Exception as e:
            logger.warning("[RenderEngine] Failed to extract thumbnail: %s", e)
            return None
