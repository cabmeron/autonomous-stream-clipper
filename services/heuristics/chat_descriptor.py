import aiohttp
import asyncio
import logging
import os
import time
import uuid
from typing import List, Optional

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = int(os.getenv("CHAT_DESCRIPTOR_INTERVAL_SECONDS", "60"))
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
DEFAULT_LOCAL_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
DEFAULT_LOCAL_MODEL = os.getenv("LOCAL_LLM_MODEL", "llama3.2:1b")


class LocalChatDescriptorService:
    """Asynchronous service to describe chat state every X seconds using Gemini API or local LLM."""

    def __init__(
        self,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        gemini_api_key: Optional[str] = None,
        gemini_model: str = DEFAULT_GEMINI_MODEL,
        local_api_base_url: str = DEFAULT_LOCAL_URL,
        local_model_name: str = DEFAULT_LOCAL_MODEL,
        timeout_seconds: float = 10.0,
        enabled: bool = True,
    ):
        self.interval_seconds = max(10, interval_seconds)
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self.gemini_model = gemini_model
        self.local_api_base_url = local_api_base_url.rstrip("/")
        self.local_model_name = local_model_name
        self.timeout_seconds = timeout_seconds
        self.enabled = enabled

    @property
    def provider(self) -> str:
        """Determines active provider: 'gemini' if key is present, else 'local'."""
        return "gemini" if bool(self.gemini_api_key.strip()) else "local"

    def format_prompts(self, messages: List[dict], channel: str, interval: int) -> tuple[str, str]:
        """Formats the system instructions and user chat transcript."""
        count = len(messages)
        sampled = messages[-100:] if count > 100 else messages

        formatted_lines = [f"- {m.get('user', 'anon')}: {m.get('text', '')}" for m in sampled]
        messages_text = "\n".join(formatted_lines)

        system_instruction = (
            f"You are an assistant analyzing live Twitch chat in real time. "
            f"Given a batch of recent chat messages from the last {interval} seconds, "
            f"write a concise 2-3 sentence description of the current state of the chat. "
            f"Highlight what viewers are reacting to or discussing, the dominant mood/vibe "
            f"(e.g. hype, laughter, trolling, disbelief, suspense), and any prominent emotes or memes. "
            f"Write ONLY 2 to 3 natural sentences. Do not use bullet points, prefixes, or markdown headers."
        )

        user_content = (
            f"Stream: #{channel}\n"
            f"Window: Last {interval} seconds ({count} messages received)\n\n"
            f"Recent Chat Messages:\n"
            f"{messages_text}\n\n"
            f"Provide the 2-3 sentence chat description:"
        )

        return system_instruction, user_content

    async def _call_gemini(self, system_instruction: str, user_content: str) -> str:
        """Calls Google Gemini REST API."""
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.gemini_model}:generateContent?key={self.gemini_api_key}"
        )
        payload = {
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_content}]
                }
            ],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 140,
            }
        }

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
                    logger.warning("[ChatDescriptor] Gemini API error (HTTP %d): %s", resp.status, err_msg[:200])
                    raise RuntimeError(f"Gemini API returned HTTP {resp.status}")

        return ""

    async def _call_local_llm(self, system_instruction: str, user_content: str) -> str:
        """Calls local OpenAI-compatible endpoint."""
        endpoint = f"{self.local_api_base_url}/chat/completions"
        payload = {
            "model": self.local_model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.4,
            "max_tokens": 120,
        }
        headers = {"Content-Type": "application/json"}
        api_key = os.getenv("LOCAL_LLM_API_KEY", "ollama")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if choices and "message" in choices[0]:
                        return choices[0]["message"].get("content", "").strip().strip('"').strip("'")
                else:
                    err_body = await resp.text()
                    logger.warning("[ChatDescriptor] Local LLM error (HTTP %d): %s", resp.status, err_body[:200])
                    raise RuntimeError(f"Local LLM returned HTTP {resp.status}")
        return ""

    async def describe_chat_window(
        self,
        messages: List[dict],
        channel: str,
        window_start: Optional[float] = None,
        window_end: Optional[float] = None,
    ) -> Optional[dict]:
        """Generates a 2-3 sentence description of the chat window."""
        if not self.enabled:
            return None

        now = time.time()
        end_time = window_end or now
        start_time = window_start or (end_time - self.interval_seconds)
        count = len(messages)

        # Fallback for quiet or dormant chat
        if count < 3:
            if count == 0:
                desc = f"Chat has been quiet with no messages received over the last {int(self.interval_seconds)} seconds."
            else:
                user_list = ", ".join(f"@{m.get('user', 'viewer')}" for m in messages)
                desc = (
                    f"Chat activity has been minimal with only {count} message(s) in the last {int(self.interval_seconds)} seconds "
                    f"from {user_list}."
                )

            return {
                "id": str(uuid.uuid4()),
                "channel_name": channel.lower(),
                "window_start": start_time,
                "window_end": end_time,
                "message_count": count,
                "description": desc,
                "model_name": "rule_based_fallback",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time)),
            }

        # Format prompt
        system_instruction, user_content = self.format_prompts(messages, channel, int(self.interval_seconds))

        description_text = ""
        # Refresh API key in case it was added or updated
        self.gemini_api_key = self.gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        active_provider = self.provider
        model_tag = self.gemini_model if active_provider == "gemini" else self.local_model_name

        try:
            if active_provider == "gemini":
                description_text = await self._call_gemini(system_instruction, user_content)
            else:
                description_text = await self._call_local_llm(system_instruction, user_content)
        except asyncio.TimeoutError:
            logger.warning("[ChatDescriptor:#%s] %s model timed out after %.1fs", channel, active_provider, self.timeout_seconds)
            description_text = (
                f"Chat had steady flow with {count} messages over the last {int(self.interval_seconds)} seconds, "
                f"but {active_provider} response timed out."
            )
            model_tag = "timeout_fallback"
        except Exception as e:
            logger.debug("[ChatDescriptor:#%s] Could not complete %s call: %s", channel, active_provider, e)
            if active_provider == "gemini":
                description_text = (
                    f"Chat recorded {count} messages ({count / max(1.0, self.interval_seconds):.1f} msg/s). "
                    f"[Gemini API key error or network issue]"
                )
            else:
                description_text = (
                    f"Chat recorded {count} messages ({count / max(1.0, self.interval_seconds):.1f} msg/s). "
                    f"[Local model offline at {self.local_api_base_url}]"
                )
            model_tag = f"{active_provider}_offline_fallback"

        if not description_text:
            description_text = f"Chat active with {count} messages over the past {int(self.interval_seconds)} seconds."

        return {
            "id": str(uuid.uuid4()),
            "channel_name": channel.lower(),
            "window_start": start_time,
            "window_end": end_time,
            "message_count": count,
            "description": description_text,
            "model_name": model_tag,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time)),
        }
