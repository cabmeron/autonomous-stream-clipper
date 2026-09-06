import aiohttp
import asyncio
import base64
import glob
import logging
import os
import subprocess
import time
import uuid
from typing import List, Optional

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("SCREEN_SUMMARIZER_TIMEOUT_SECONDS", "30.0"))


def get_default_shm_dir() -> str:
    """Select appropriate temporary buffer directory across platforms."""
    if os.path.exists("/dev/shm") and os.access("/dev/shm", os.W_OK):
        return "/dev/shm/clipper"
    return os.path.join("/tmp", "clipper_shm")


class ScreenStateSummarizerService:
    """Extracts the latest stream frame from RAM ring-buffer and generates multimodal screen summaries."""

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        gemini_model: str = DEFAULT_GEMINI_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        shm_base: Optional[str] = None,
    ):
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self.gemini_model = gemini_model
        self.timeout_seconds = timeout_seconds
        self.shm_base = shm_base or get_default_shm_dir()

    def extract_latest_frame(self, channel: str) -> Optional[bytes]:
        """Extracts a high-resolution JPEG image from the newest fully-written TS segment in the buffer."""
        channel_clean = channel.lower().lstrip("#")
        channel_dir = os.path.join(self.shm_base, channel_clean)

        if not os.path.exists(channel_dir):
            logger.debug("[ScreenSummarizer] Buffer directory %s does not exist", channel_dir)
            return None

        segments = glob.glob(os.path.join(channel_dir, "seg_*.ts"))
        if not segments:
            logger.debug("[ScreenSummarizer] No TS segments available in %s", channel_dir)
            return None

        segments.sort(key=os.path.getmtime)
        # Prefer the second-to-last segment if available (last segment is actively written by ffmpeg)
        target_segment = segments[-2] if len(segments) >= 2 else segments[-1]

        # Fast single-frame extraction to pipe as MJPEG
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-sseof", "-1.0",
            "-i", target_segment,
            "-vframes", "1",
            "-q:v", "2",
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-",
        ]
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=4)
            if p.stdout and len(p.stdout) > 1000:
                return p.stdout
        except Exception:
            pass

        # Fallback without -sseof in case segment is too short
        fallback_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-i", target_segment,
            "-vframes", "1",
            "-q:v", "2",
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-",
        ]
        try:
            p = subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=4)
            if p.stdout and len(p.stdout) > 1000:
                return p.stdout
        except Exception as e:
            logger.warning("[ScreenSummarizer] Failed to extract frame from %s: %s", target_segment, e)

        return None

    def format_payload(self, channel: str, messages: List[dict], frame_bytes: Optional[bytes] = None) -> dict:
        """Constructs Google Gemini multimodal REST payload with inline JPEG base64 and chat transcript."""
        count = len(messages)
        sampled = messages[-40:] if count > 40 else messages

        formatted_lines = [f"- {m.get('user', 'anon')}: {m.get('text', '')}" for m in sampled]
        messages_text = "\n".join(formatted_lines) if formatted_lines else "(No recent chat messages)"

        system_instruction = (
            "You are an expert live stream analyst. Given a real-time screenshot of the stream and recent live chat messages, "
            "synthesize a concise and insightful 2-4 sentence summary of the current screen state:\n"
            "1. Visual Scene: What is currently happening on screen? (e.g. game title, match status/score, UI elements, streamer camera/reaction, browsing content)\n"
            "2. Chat Reaction: What is chat actively discussing or reacting to relative to the screen?\n"
            "3. Current Moment: The overall momentum, climax, or vibe of the stream right now.\n"
            "Write naturally in 2 to 4 clear sentences. Do not use bullet points, prefixes, or markdown headers."
        )

        user_text = (
            f"Stream: #{channel}\n"
            f"Recent Chat Messages ({count} total):\n"
            f"{messages_text}\n\n"
            f"Summarize the state of the screen and current stream context:"
        )

        parts = []
        if frame_bytes:
            b64_image = base64.b64encode(frame_bytes).decode("utf-8")
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": b64_image
                }
            })

        parts.append({"text": user_text})

        return {
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": parts
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 260,
            }
        }

    async def _call_gemini_multimodal(self, payload: dict) -> str:
        """Sends the multimodal request to the Gemini REST API."""
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.gemini_model}:generateContent?key={self.gemini_api_key}"
        )
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip().strip('"').strip("'")
                else:
                    err_msg = await resp.text()
                    logger.warning("[ScreenSummarizer] Gemini API error (HTTP %d): %s", resp.status, err_msg[:200])
                    raise RuntimeError(f"Gemini API returned HTTP {resp.status}")

        return ""

    async def summarize_screen(
        self,
        channel: str,
        messages: List[dict],
        frame_bytes: Optional[bytes] = None,
    ) -> dict:
        """Captures screen and chat state and generates a 2-4 sentence multimodal description."""
        clean_channel = channel.lower().lstrip("#")

        # Refresh API key from environment if needed
        self.gemini_api_key = self.gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

        # Extract frame if not explicitly passed
        if frame_bytes is None:
            frame_bytes = await asyncio.to_thread(self.extract_latest_frame, clean_channel)

        payload = self.format_payload(clean_channel, messages, frame_bytes)
        summary_text = ""
        model_tag = self.gemini_model if self.gemini_api_key else "fallback"

        if self.gemini_api_key:
            try:
                summary_text = await self._call_gemini_multimodal(payload)
            except asyncio.TimeoutError:
                logger.warning("[ScreenSummarizer:#%s] Gemini multimodal timed out after %.1fs", clean_channel, self.timeout_seconds)
                summary_text = (
                    f"Captured live screen for #{clean_channel} with {len(messages)} recent chat messages. "
                    f"Gemini multimodal response timed out."
                )
                model_tag = "timeout_fallback"
            except Exception as e:
                logger.warning("[ScreenSummarizer:#%s] Gemini multimodal call failed: %s", clean_channel, e)
                summary_text = (
                    f"Screen snapshot captured for #{clean_channel} with {len(messages)} recent messages. "
                    f"Analysis could not complete: {e}"
                )
                model_tag = "error_fallback"
        else:
            has_frame_note = "video frame captured" if frame_bytes else "awaiting stream frame buffer"
            summary_text = (
                f"Stream #{clean_channel} is live with {len(messages)} recent chat messages ({has_frame_note}). "
                f"Configure GEMINI_API_KEY to enable AI multimodal screen analysis."
            )
            model_tag = "no_key_fallback"

        if not summary_text:
            summary_text = f"Live stream state captured for #{clean_channel} with {len(messages)} chat messages."

        image_b64 = None
        if frame_bytes:
            image_b64 = f"data:image/jpeg;base64,{base64.b64encode(frame_bytes).decode('utf-8')}"

        return {
            "id": str(uuid.uuid4()),
            "channel_name": clean_channel,
            "summary": summary_text,
            "image_b64": image_b64,
            "message_count": len(messages),
            "has_image": bool(frame_bytes),
            "model_name": model_tag,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
