import asyncio
import base64
import io
import json
import logging
import os
import signal
import sys
import threading
import time
from collections import deque
from typing import Dict, List, Optional
from dotenv import load_dotenv
from aiohttp import web

from services.ingest.stream_buffer import StreamRingBuffer, clean_channel_name
from services.ingest.twitch_irc import TwitchChatVelocityEngine
from services.heuristics.audio_monitor import AudioDecibelMonitor
from services.heuristics.ocr_engine import BoundedRegionOCR
from services.heuristics.cv_transformer import CVTransformerService
from services.heuristics.streamer_emotion import StreamerEmotionService
from services.heuristics.gambling_ocr import GamblingOCREngine
from services.heuristics.gambling_ledger import GamblingLedger
from services.heuristics.gate_evaluator import GateEvaluator
from services.heuristics.chat_descriptor import LocalChatDescriptorService
from services.heuristics.screen_summarizer import ScreenStateSummarizerService
from services.heuristics.watch_party_finder import WatchPartyFinderService
from services.processor.slicer import SegmentSlicer
from services.processor.transcriber import AudioTranscriber
from services.processor.boundary_ai import BoundaryOptimizer
from services.processor.render_engine import HardwareRenderEngine
from services.storage.local_storage import LocalStorageManager
from services.storage.db import DatabaseRepository
from services.orchestrator_dag import GraphDAGManager
import telemetry_server

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("orchestrator")

DEBOUNCE_SEC = float(os.getenv("HEURISTIC_DEBOUNCE_SECONDS", "30"))
POST_DELAY_SEC = float(os.getenv("POST_EVENT_DELAY_SECONDS", "10"))
HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))
STORAGE_DIR = os.getenv("STORAGE_DIR", "./storage/clips")
ENABLE_OCR = os.getenv("OCR_ENABLED", "true").lower() == "true"
ENABLE_CV = os.getenv("CV_ENABLED", "true").lower() == "true"
ENABLE_BURN_IN_SUBS = os.getenv("ENABLE_BURN_IN_SUBS", "false").lower() == "true"
DESCRIPTOR_INTERVAL_SEC = int(os.getenv("CHAT_DESCRIPTOR_INTERVAL_SECONDS", "60"))
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "llama3.2:1b")


class StreamSession:
    """Represents an independent monitoring session for a single Twitch channel."""

    def __init__(self, channel: str, orchestrator: "StreamClipperOrchestrator", simulate: bool = False):
        self.channel = clean_channel_name(channel)
        self.orchestrator = orchestrator
        self.simulate = simulate

        # 1. Video Buffer
        self.buffer = StreamRingBuffer(self.channel, simulate=self.simulate)

        # 2. IRC Chat Velocity Engine
        self.chat_engine = TwitchChatVelocityEngine(
            self.channel,
            on_spike_callback=self._on_chat_spike,
            spike_ratio_threshold=float(os.getenv("HEURISTIC_CHAT_RATIO_THRESHOLD", "3.0")),
            instant_min_threshold=float(os.getenv("HEURISTIC_CHAT_INSTANT_MIN", "10.0")),
        )
        self.chat_task: Optional[asyncio.Task] = None

        # 3. Audio Monitor
        self.audio_monitor = AudioDecibelMonitor(
            jump_db_threshold=float(os.getenv("HEURISTIC_AUDIO_DB_THRESHOLD", "12.0")),
            on_spike_callback=self._on_audio_spike,
        )

        # 4. OCR Engine
        roi = {
            "x": float(os.getenv("OCR_ROI_X", "0.70")),
            "y": float(os.getenv("OCR_ROI_Y", "0.85")),
            "w": float(os.getenv("OCR_ROI_W", "0.28")),
            "h": float(os.getenv("OCR_ROI_H", "0.12")),
        }
        self.ocr_engine = BoundedRegionOCR(
            roi=roi,
            win_multiplier_threshold=float(os.getenv("HEURISTIC_WIN_MULTIPLIER_THRESHOLD", "100.0")),
            on_trigger_callback=self._on_ocr_trigger,
        )

        # 4b. Computer Vision Transformer Engine (Zero-Shot & Object Detection)
        self.cv_service = CVTransformerService(
            on_trigger_callback=self._on_cv_trigger,
        )

        # 4c. Streamer Facial Emotion & Tilt Tracking
        self.streamer_emotion = StreamerEmotionService(
            on_tilt_spike=self._on_tilt_spike,
            on_euphoria_spike=self._on_euphoria_spike,
        )

        # 4d. Multi-Region Gambling OCR & Spin Motion Engine
        self.gambling_ocr = GamblingOCREngine()

        # 4e. Gambling Session Financial Ledger & Winrate Engine
        self.gambling_ledger = GamblingLedger(
            on_big_win=self._on_gambling_big_win,
            on_tilt_bet=self._on_gambling_tilt_bet,
        )

        # 5. Gate Evaluator
        self.gate_evaluator = GateEvaluator(
            on_trigger_dispatch=self._on_clip_trigger,
            on_trigger_activated=self._on_trigger_activated,
            debounce_seconds=DEBOUNCE_SEC,
            post_event_delay_seconds=POST_DELAY_SEC,
        )

        # 6. Local Chat State Descriptor Service (Disabled by default, superseded by on-demand Screen State Summarizer)
        self.chat_descriptor_service = LocalChatDescriptorService(
            interval_seconds=DESCRIPTOR_INTERVAL_SEC,
            gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "",
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
            local_api_base_url=LOCAL_LLM_URL,
            local_model_name=LOCAL_LLM_MODEL,
            enabled=False,
        )
        self.last_descriptor_time: float = time.time()
        self.latest_description: Optional[dict] = None

        # 7. On-Demand Multimodal Screen State Summarizer Service
        self.screen_summarizer = ScreenStateSummarizerService(
            gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "",
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        )
        self.latest_screen_summary: Optional[dict] = None

        # Telemetry metrics
        self.extra_telemetry = {
            "audio_rms_db": -60.0,
            "audio_spike": False,
            "audio_waveform": [],
            "ocr_balance": "$0.00",
            "ocr_multiplier": "1.0x",
            "ocr_pnl_delta": 0.0,
            "cv_top_label": "standby",
            "cv_confidence": 0.0,
            "cv_probabilities": {},
            "cv_boxes": [],
            "cv_latency_ms": 0.0,
            "cv_thumbnail_b64": "",
            "emotion_top": "neutral",
            "emotion_confidence": 0.0,
            "emotion_distribution": {},
            "emotion_valence": 0.0,
            "emotion_arousal": 0.0,
            "emotion_tilt": 0.0,
            "emotion_euphoria": 0.0,
            "is_tilting": False,
            "gambling_balance": 0.0,
            "gambling_bet": 0.0,
            "gambling_win": 0.0,
            "gambling_multiplier": 0.0,
            "gambling_spin_state": "IDLE",
            "stream_frame_b64": "",
        }
        self.last_analyzed_segment: Optional[str] = None

    def start(self, loop: asyncio.AbstractEventLoop):
        """Starts HLS ingestion and connects to IRC WebSocket."""
        logger.info("[Session:%s] Starting stream buffer and chat listener...", self.channel)
        self.loop = loop
        self.gate_evaluator.loop = loop
        self.buffer.start()
        self.chat_task = loop.create_task(self.chat_engine.listen())

    def stop(self):
        """Stops the session and cleans up resources."""
        logger.info("[Session:%s] Stopping session...", self.channel)
        if self.chat_engine:
            self.chat_engine.stop()
        if self.chat_task and not self.chat_task.done():
            self.chat_task.cancel()
        if self.buffer:
            self.buffer.stop()

    def _on_chat_spike(self, instant: float, ratio: float):
        logger.info("[Session:%s][ChatSpike] instant=%.2f msgs/s, ratio=%.2fx", self.channel, instant, ratio)
        cv_res = getattr(self.cv_service, "latest_result", None) or {}
        self.gate_evaluator.evaluate_signals(
            source="chat_spike",
            chat_instant=instant,
            chat_ratio=ratio,
            win_multiplier=self.ocr_engine.current_multiplier,
            pnl_delta=self.ocr_engine.pnl_delta,
            audio_db=self.audio_monitor.current_db,
            audio_delta=self.audio_monitor.delta_db,
            cv_score=cv_res.get("confidence", 0.0),
            cv_label=cv_res.get("top_label", ""),
        )

    def _on_audio_spike(self, instant_db: float, delta_db: float):
        logger.info("[Session:%s][AudioSpike] level=%.1f dB, jump=+%.1f dB", self.channel, instant_db, delta_db)
        cv_res = getattr(self.cv_service, "latest_result", None) or {}
        self.gate_evaluator.evaluate_signals(
            source="audio_spike",
            chat_instant=self.chat_engine.v_instant,
            chat_ratio=self.chat_engine.spike_ratio,
            win_multiplier=self.ocr_engine.current_multiplier,
            pnl_delta=self.ocr_engine.pnl_delta,
            audio_db=instant_db,
            audio_delta=delta_db,
            cv_score=cv_res.get("confidence", 0.0),
            cv_label=cv_res.get("top_label", ""),
        )

    def _on_ocr_trigger(self, multiplier: float, delta: float):
        logger.info("[Session:%s][OCRTrigger] multiplier=%.1fx, delta=$%.2f", self.channel, multiplier, delta)
        cv_res = getattr(self.cv_service, "latest_result", None) or {}
        self.gate_evaluator.evaluate_signals(
            source="ocr_multiplier",
            chat_instant=self.chat_engine.v_instant,
            chat_ratio=self.chat_engine.spike_ratio,
            win_multiplier=multiplier,
            pnl_delta=delta,
            audio_db=self.audio_monitor.current_db,
            audio_delta=self.audio_monitor.delta_db,
            cv_score=cv_res.get("confidence", 0.0),
            cv_label=cv_res.get("top_label", ""),
        )

    def _on_cv_trigger(self, result: dict):
        top_label = result.get("top_label", "")
        conf = result.get("confidence", 0.0)
        logger.info("[Session:%s][CVTrigger] label=%s (%.1f%%)", self.channel, top_label, conf * 100)
        self.gate_evaluator.evaluate_signals(
            source=f"cv_{top_label}",
            chat_instant=self.chat_engine.v_instant if self.chat_engine else 0.0,
            chat_ratio=self.chat_engine.spike_ratio if self.chat_engine else 1.0,
            win_multiplier=self.ocr_engine.current_multiplier if self.ocr_engine else 1.0,
            pnl_delta=self.ocr_engine.pnl_delta if self.ocr_engine else 0.0,
            audio_db=self.audio_monitor.current_db if self.audio_monitor else -60.0,
            audio_delta=self.audio_monitor.delta_db if self.audio_monitor else 0.0,
            cv_score=conf,
            cv_label=top_label,
        )

    def _on_tilt_spike(self, metrics: dict):
        top_emo = metrics.get("top_emotion", "rage")
        tilt = metrics.get("tilt_score", 0.0)
        logger.warning("[Session:%s][TiltSpike] Streamer tilting: %s (Tilt Index: %.1f/100)", self.channel, top_emo, tilt)
        self.gate_evaluator.evaluate_signals(
            source=f"streamer_tilt_{top_emo}",
            chat_instant=self.chat_engine.v_instant if self.chat_engine else 0.0,
            chat_ratio=self.chat_engine.spike_ratio if self.chat_engine else 1.0,
            win_multiplier=self.ocr_engine.current_multiplier if self.ocr_engine else 1.0,
            pnl_delta=self.gambling_ledger.get_net_pnl() if getattr(self, "gambling_ledger", None) else 0.0,
            audio_db=self.audio_monitor.current_db if self.audio_monitor else -60.0,
            audio_delta=self.audio_monitor.delta_db if self.audio_monitor else 0.0,
            cv_score=tilt / 100.0,
            cv_label=f"tilt_{top_emo}",
        )

    def _on_euphoria_spike(self, metrics: dict):
        euphoria = metrics.get("euphoria_score", 0.0)
        logger.info("[Session:%s][EuphoriaSpike] Streamer ecstatic! Euphoria: %.1f/100", self.channel, euphoria)
        self.gate_evaluator.evaluate_signals(
            source="streamer_euphoria",
            chat_instant=self.chat_engine.v_instant if self.chat_engine else 0.0,
            chat_ratio=self.chat_engine.spike_ratio if self.chat_engine else 1.0,
            win_multiplier=self.ocr_engine.current_multiplier if self.ocr_engine else 1.0,
            pnl_delta=self.gambling_ledger.get_net_pnl() if getattr(self, "gambling_ledger", None) else 0.0,
            audio_db=self.audio_monitor.current_db if self.audio_monitor else -60.0,
            audio_delta=self.audio_monitor.delta_db if self.audio_monitor else 0.0,
            cv_score=euphoria / 100.0,
            cv_label="victory celebration",
        )

    def _on_gambling_big_win(self, data: dict):
        win_amt = data.get("win_amount", 0.0)
        mult = data.get("multiplier", 1.0)
        logger.info("[Session:%s][BigWin] Payout: $%.2f (%.1fx)", self.channel, win_amt, mult)
        self.gate_evaluator.evaluate_signals(
            source="gambling_big_win",
            chat_instant=self.chat_engine.v_instant if self.chat_engine else 0.0,
            chat_ratio=self.chat_engine.spike_ratio if self.chat_engine else 1.0,
            win_multiplier=mult,
            pnl_delta=win_amt,
            audio_db=self.audio_monitor.current_db if self.audio_monitor else -60.0,
            audio_delta=self.audio_monitor.delta_db if self.audio_monitor else 0.0,
            cv_score=1.0,
            cv_label="jackpot win",
        )

    def _on_gambling_tilt_bet(self, data: dict):
        esc = data.get("escalation_ratio", 2.0)
        cur_bet = data.get("current_bet", 0.0)
        logger.warning("[Session:%s][TiltBet] Loss-chasing bet escalation: %.1fx ($%.2f)", self.channel, esc, cur_bet)
        self.gate_evaluator.evaluate_signals(
            source="gambling_tilt_bet",
            chat_instant=self.chat_engine.v_instant if self.chat_engine else 0.0,
            chat_ratio=self.chat_engine.spike_ratio if self.chat_engine else 1.0,
            win_multiplier=1.0,
            pnl_delta=self.gambling_ledger.get_net_pnl() if getattr(self, "gambling_ledger", None) else 0.0,
            audio_db=self.audio_monitor.current_db if self.audio_monitor else -60.0,
            audio_delta=self.audio_monitor.delta_db if self.audio_monitor else 0.0,
            cv_score=0.85,
            cv_label="rage tilt bet",
        )

    def _on_trigger_activated(self, context: dict):
        """Immediately instantiates a tracked clipping job upon excitement spike detection."""
        job_id = self.orchestrator.create_job(self.channel, context)
        context["job_id"] = job_id

    async def _on_clip_trigger(self, context: dict):
        """Passes clip trigger to the central orchestrator."""
        await self.orchestrator.process_clip_trigger(self, context)

    def get_status(self) -> dict:
        return {
            "channel": self.channel,
            "status": "monitoring",
            "is_buffering": self.buffer.is_alive() if self.buffer else False,
            "buffered_segments": len(self.buffer.get_active_segments()) if self.buffer else 0,
        }

    def get_telemetry(self) -> dict:
        calc = self.chat_engine.recalculate() if self.chat_engine else {
            "v_instant": 0.0, "v_baseline": 0.0, "spike_ratio": 1.0, "is_spiking": False, "buffered_messages": 0, "total_messages": 0, "recent_messages": []
        }
        return {
            "channel": self.channel,
            "status": "monitoring",
            "v_instant": calc["v_instant"],
            "v_baseline": calc["v_baseline"],
            "spike_ratio": calc["spike_ratio"],
            "is_spiking": calc["is_spiking"],
            "recent_messages": calc.get("recent_messages", []),
            "audio_rms_db": self.extra_telemetry["audio_rms_db"],
            "audio_spike": self.extra_telemetry["audio_spike"],
            "audio_waveform": self.extra_telemetry.get("audio_waveform", []),
            "ocr_balance": self.extra_telemetry["ocr_balance"],
            "ocr_multiplier": self.extra_telemetry["ocr_multiplier"],
            "ocr_pnl_delta": self.extra_telemetry["ocr_pnl_delta"],
            "cv_top_label": self.extra_telemetry.get("cv_top_label", "standby"),
            "cv_confidence": self.extra_telemetry.get("cv_confidence", 0.0),
            "cv_probabilities": self.extra_telemetry.get("cv_probabilities", {}),
            "cv_boxes": self.extra_telemetry.get("cv_boxes", []),
            "cv_latency_ms": self.extra_telemetry.get("cv_latency_ms", 0.0),
            "cv_thumbnail_b64": self.extra_telemetry.get("cv_thumbnail_b64", ""),
            "stream_frame_b64": self.extra_telemetry.get("stream_frame_b64", ""),
            "emotion_top": self.extra_telemetry.get("emotion_top", "neutral"),
            "emotion_confidence": self.extra_telemetry.get("emotion_confidence", 0.0),
            "emotion_distribution": self.extra_telemetry.get("emotion_distribution", {}),
            "emotion_valence": self.extra_telemetry.get("emotion_valence", 0.0),
            "emotion_arousal": self.extra_telemetry.get("emotion_arousal", 0.0),
            "emotion_tilt": self.extra_telemetry.get("emotion_tilt", 0.0),
            "emotion_euphoria": self.extra_telemetry.get("emotion_euphoria", 0.0),
            "is_tilting": self.extra_telemetry.get("is_tilting", False),
            "gambling_balance": self.extra_telemetry.get("gambling_balance", 0.0),
            "gambling_bet": self.extra_telemetry.get("gambling_bet", 0.0),
            "gambling_win": self.extra_telemetry.get("gambling_win", 0.0),
            "gambling_multiplier": self.extra_telemetry.get("gambling_multiplier", 0.0),
            "gambling_spin_state": self.extra_telemetry.get("gambling_spin_state", "IDLE"),
            "gambling_ledger": self.gambling_ledger.get_summary() if getattr(self, "gambling_ledger", None) else {},
            "buffered_messages": calc["buffered_messages"],
            "total_messages": calc.get("total_messages", 0),
            "buffered_segments": self.buffer.get_segment_count() if self.buffer else 0,
            "latest_chat_description": self.latest_description,
            "latest_screen_summary": self.latest_screen_summary,
        }


@web.middleware
async def cors_middleware(request, handler):
    """Adds CORS headers to all responses."""
    if request.method == "OPTIONS":
        response = web.Response()
    else:
        response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


class StreamClipperOrchestrator:
    """Master supervisor managing multi-session ingestion, heuristics, clipping, and telemetry."""

    def __init__(self):
        self.running = False
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.http_runner: Optional[web.AppRunner] = None

        # Registry of active channel sessions: channel_name -> StreamSession
        self.sessions: Dict[str, StreamSession] = {}

        # 1. Local Storage & Database
        self.storage = LocalStorageManager(storage_dir=STORAGE_DIR)
        self.db = DatabaseRepository()

        # 2. Processor Pipeline (100% Local)
        self.transcriber = AudioTranscriber()
        self.boundary_ai = BoundaryOptimizer()
        self.transcription_lock = threading.Lock()

        # Registry of active clipping pipeline jobs: job_id -> job_dict
        self.active_jobs: Dict[str, dict] = {}

        # 3. Watch Party & Co-Stream Discovery Engine
        self.watch_party_finder = WatchPartyFinderService()

        # 4. ComfyUI-Style Dynamic Graph DAG Manager
        self.graph_manager = GraphDAGManager(orchestrator=self)

        # Hook telemetry providers into telemetry server
        telemetry_server.sessions_telemetry_provider = self.get_all_telemetry
        telemetry_server.active_jobs_provider = self.get_active_jobs
        telemetry_server.node_telemetry_provider = self.graph_manager.get_node_telemetry_payload

    def create_job(self, channel: str, context: dict) -> str:
        """Instantiates a new tracked clipping pipeline job with real-time step progress and logs."""
        job_id = f"job_{channel}_{int(time.time())}"
        now_str = time.strftime("%H:%M:%S")
        source = context.get("trigger_source", "spike")
        score = context.get("score", 7)
        is_manual = (source == "manual_trigger")
        delay = 0.0 if is_manual else context.get("post_event_delay", POST_DELAY_SEC)

        if is_manual:
            current_step = "Slicing newest 60s stream buffer..."
            progress_pct = 25
            steps = [
                {"id": "trigger", "name": "Manual Quick Clip Triggered", "status": "done", "detail": "User clicked 'Clip Last 60s'"},
                {"id": "delay", "name": "Post-Event Delay Buffer", "status": "done", "detail": "Bypassed (instant manual capture)"},
                {"id": "slicing", "name": "RAM Buffer Slicing", "status": "running", "detail": "Concatenating newest 60s RAM slice"},
                {"id": "transcribe", "name": "Speech Transcription", "status": "pending", "detail": "faster-whisper word alignment"},
                {"id": "boundary", "name": "Speech Pause Optimization", "status": "pending", "detail": "Full 60s highlight preserved"},
                {"id": "render", "name": "Raw Video Extraction", "status": "pending", "detail": "Hardware-accelerated uncropped cut"},
                {"id": "save", "name": "Storage & Database", "status": "pending", "detail": "Persisting to local disk & gallery"},
            ]
            logs = [
                f"[{now_str}] Manual highlight triggered by user for #{channel}.",
                f"[{now_str}] Bypassed post-event delay (capturing newest 60s buffer immediately).",
            ]
        else:
            current_step = f"Buffering post-event reaction (+{int(delay)}s)..."
            progress_pct = 12
            steps = [
                {"id": "trigger", "name": "Spike Trigger Activated", "status": "done", "detail": f"Signal: {source} (Score: {score}/10)"},
                {"id": "delay", "name": "Post-Event Delay Buffer", "status": "running", "detail": f"Capturing +{int(delay)}s reaction window"},
                {"id": "slicing", "name": "RAM Buffer Slicing", "status": "pending", "detail": "Zero-copy TS slice concatenation"},
                {"id": "transcribe", "name": "Speech Transcription", "status": "pending", "detail": "faster-whisper word alignment"},
                {"id": "boundary", "name": "Speech Pause Optimization", "status": "pending", "detail": "Boundary trimming on speech pauses"},
                {"id": "render", "name": "Raw Video Extraction", "status": "pending", "detail": "Hardware-accelerated uncropped cut"},
                {"id": "save", "name": "Storage & Database", "status": "pending", "detail": "Persisting to local disk & gallery"},
            ]
            logs = [
                f"[{now_str}] Excitement spike triggered via {source} (Score: {score}/10).",
                f"[{now_str}] Post-event buffer initiated (+{int(delay)}s reaction capture).",
            ]

        job = {
            "id": job_id,
            "channel": channel,
            "status": "processing",
            "score": score,
            "source": source,
            "created_at": time.time(),
            "updated_at": time.time(),
            "current_step": current_step,
            "progress_pct": progress_pct,
            "steps": steps,
            "logs": logs,
        }
        self.active_jobs[job_id] = job
        logger.info("[Job:%s] Created clipping job for #%s (source: %s, score: %d/10)", job_id, channel, source, score)
        return job_id

    def update_job_step(
        self,
        job_id: str,
        step_id: str,
        step_status: str,
        progress_pct: int,
        log_msg: str = None,
        detail: str = None,
    ):
        """Updates status of a specific step in the clipping pipeline and appends to live log console."""
        job = self.active_jobs.get(job_id)
        if not job:
            return
        job["updated_at"] = time.time()
        job["progress_pct"] = progress_pct
        for step in job["steps"]:
            if step["id"] == step_id:
                step["status"] = step_status
                if detail:
                    step["detail"] = detail
                if step_status == "running":
                    job["current_step"] = step["name"]
        if log_msg:
            now_str = time.strftime("%H:%M:%S")
            job["logs"].append(f"[{now_str}] {log_msg}")

    def complete_job(self, job_id: str, clip_summary: dict):
        """Marks a clipping pipeline job as successfully completed."""
        job = self.active_jobs.get(job_id)
        if not job:
            return
        now_str = time.strftime("%H:%M:%S")
        job["status"] = "completed"
        job["progress_pct"] = 100
        job["current_step"] = "Generation complete!"
        job["clip"] = clip_summary
        for step in job["steps"]:
            step["status"] = "done"
        job["logs"].append(f"[{now_str}] Successfully saved clip! (Duration: {clip_summary.get('duration_seconds')}s)")
        logger.info("[Job:%s] Completed clipping job for #%s (Duration: %ss)", job_id, job.get("channel"), clip_summary.get("duration_seconds"))

    def fail_job(self, job_id: str, error_msg: str):
        """Marks a clipping job as failed and records the error log."""
        job = self.active_jobs.get(job_id)
        if not job:
            return
        now_str = time.strftime("%H:%M:%S")
        job["status"] = "failed"
        job["current_step"] = f"Failed: {error_msg}"
        job["logs"].append(f"[{now_str}] ERROR: {error_msg}")
        job["updated_at"] = time.time()
        for s in job.get("steps", []):
            if s.get("status") == "running":
                s["status"] = "failed"
                s["detail"] = error_msg
        logger.error("[Job:%s] Failed: %s", job_id, error_msg)

    def get_active_jobs(self) -> Dict[str, dict]:
        """Returns all current jobs and cleans up finished jobs older than 60 seconds."""
        now = time.time()
        for jid in list(self.active_jobs.keys()):
            j = self.active_jobs[jid]
            if j.get("status") in ("completed", "failed") and (now - j.get("updated_at", now)) > 60.0:
                self.active_jobs.pop(jid, None)
        return self.active_jobs

    def get_all_telemetry(self) -> Dict[str, dict]:
        """Provides real-time telemetry dictionaries for all active sessions."""
        return {ch: sess.get_telemetry() for ch, sess in self.sessions.items()}

    def get_all_sessions_status(self) -> List[dict]:
        """Returns summary status for all active sessions."""
        return [sess.get_status() for sess in self.sessions.values()]

    async def add_session(self, channel: str, simulate: bool = False) -> dict:
        """Adds a new channel session and begins ingestion."""
        clean = clean_channel_name(channel)
        if not clean:
            raise ValueError("Channel name or Twitch URL cannot be empty or invalid")

        if clean in self.sessions:
            logger.info("[Orchestrator] Channel #%s already active", clean)
            return self.sessions[clean].get_status()

        # Auto-detect simulation channel from naming patterns or explicit simulate flag
        if simulate or clean.startswith("sim_") or "_reacts" in clean or "watch_" in clean or "react_" in clean:
            simulate = True

        session = StreamSession(clean, self, simulate=simulate)
        if self.running and self.loop:
            session.start(self.loop)
        self.sessions[clean] = session

        logger.info("[Orchestrator] Active sessions (%d total): %s", len(self.sessions), list(self.sessions.keys()))
        return session.get_status()

    async def remove_session(self, channel: str) -> bool:
        """Stops and removes an existing channel session."""
        clean = clean_channel_name(channel)
        if clean in self.sessions:
            session = self.sessions.pop(clean)
            session.stop()
            logger.info("[Orchestrator] Removed session #%s (%d remaining)", clean, len(self.sessions))
            return True
        return False

    # Backward compatibility for single channel operations
    @property
    def channel(self) -> Optional[str]:
        keys = list(self.sessions.keys())
        return keys[0] if keys else None

    @property
    def buffer(self) -> Optional[StreamRingBuffer]:
        keys = list(self.sessions.keys())
        return self.sessions[keys[0]].buffer if keys else None

    @property
    def chat_engine(self) -> Optional[TwitchChatVelocityEngine]:
        keys = list(self.sessions.keys())
        return self.sessions[keys[0]].chat_engine if keys else None

    def get_status(self) -> dict:
        if not self.sessions:
            return {"channel": None, "status": "idle", "is_buffering": False, "buffered_segments": 0}
        first = list(self.sessions.values())[0]
        return first.get_status()

    async def set_channel(self, new_channel: Optional[str]) -> dict:
        """Single-channel compatibility wrapper."""
        clean = clean_channel_name(new_channel) if new_channel else ""
        if not clean:
            for ch in list(self.sessions.keys()):
                await self.remove_session(ch)
            return self.get_status()
        else:
            return await self.add_session(clean)

    async def trigger_manual_clip(self, channel: str) -> dict:
        """Manually captures the newest 60 seconds from the rolling stream buffer."""
        clean = clean_channel_name(channel)
        session = self.sessions.get(clean)
        if not session:
            raise ValueError(f"Stream #{clean} is not active. Please add or select an active session.")

        context = {
            "trigger_source": "manual_trigger",
            "score": 10,
            "win_multiplier": 1.0,
            "pnl_delta": 0.0,
            "channel": clean,
            "timestamp": time.time(),
        }

        job_id = self.create_job(clean, context)
        context["job_id"] = job_id

        # Dispatch clipping DAG in a non-blocking background task
        asyncio.create_task(self.process_clip_trigger(session, context))

        logger.info("[Orchestrator] Manual 60s clip initiated for #%s (job: %s)", clean, job_id)
        return {
            "success": True,
            "job_id": job_id,
            "channel": clean,
            "message": f"Manual 60-second clip initiated for #{clean}",
        }

    @staticmethod
    def _process_video_and_cv_heuristics(session: StreamSession, segment_path: str) -> dict:
        """Extracts decoded video frame once and runs CV transformers, emotion tracking, gambling OCR and ledger."""
        results = {}
        frame = None

        # 1. Decode video frame using CV extractor
        if getattr(session, "cv_service", None) and hasattr(session.cv_service, "extractor"):
            try:
                frame = session.cv_service.extractor.extract_frame(segment_path)
            except Exception as e:
                logger.debug("[FrameExtractor] Error extracting frame: %s", e)

        # 2. Run Computer Vision Transformer (Zero-Shot & Object Detection)
        if ENABLE_CV and getattr(session, "cv_service", None):
            try:
                cv_res = session.cv_service.process_segment(segment_path)
                results["cv_res"] = cv_res
            except Exception as e:
                logger.debug("[CVService] Error processing segment: %s", e)

        # 3. Streamer Facial Emotion Recognition & Continuous Tilt Index
        if getattr(session, "streamer_emotion", None) and frame is not None:
            try:
                emotion_res = session.streamer_emotion.process_frame(frame)
                results["emotion_res"] = emotion_res
            except Exception as e:
                logger.debug("[StreamerEmotion] Error processing frame: %s", e)

        # 4. Multi-Region Gambling OCR & Spin State Engine
        if getattr(session, "gambling_ocr", None) and frame is not None:
            try:
                gambling_res = session.gambling_ocr.process_frame(frame)
                results["gambling_res"] = gambling_res

                # Feed parsed numbers into Gambling Ledger
                if getattr(session, "gambling_ledger", None) and gambling_res:
                    session.gambling_ledger.update_from_ocr(gambling_res)
                    ledger_summary = session.gambling_ledger.get_summary()
                    results["ledger_summary"] = ledger_summary

                    # Correlate gambling loss streak & bet escalation back into facial emotion service
                    if getattr(session, "streamer_emotion", None):
                        streak = ledger_summary.get("current_streak", 0)
                        loss_streak = abs(streak) if streak < 0 else 0
                        base_bet = ledger_summary.get("baseline_bet", 0.0) or 1.0
                        curr_bet = ledger_summary.get("current_bet", 0.0)
                        session.streamer_emotion.update_gambling_context(
                            loss_streak=loss_streak,
                            bet_escalation=(curr_bet / base_bet) if base_bet > 0 else 1.0,
                        )
            except Exception as e:
                logger.debug("[GamblingOCR] Error processing frame: %s", e)

        # 5. Generate clean, compressed JPEG base64 frame thumbnail for in-node and stream ROI dragging
        thumb_b64 = ""
        if frame is not None:
            try:
                t_buf = io.BytesIO()
                thumb = frame.resize((480, 270))
                thumb.save(t_buf, format="JPEG", quality=60)
                thumb_b64 = "data:image/jpeg;base64," + base64.b64encode(t_buf.getvalue()).decode("utf-8")
            except Exception as e:
                logger.debug("[Thumbnail] Error generating thumbnail: %s", e)
        elif results.get("cv_res") and results["cv_res"].get("thumbnail_b64"):
            thumb_b64 = results["cv_res"]["thumbnail_b64"]
        results["stream_frame_b64"] = thumb_b64

        return results

    async def heuristics_polling_loop(self):
        """Periodically samples the newest video segment for each active session for audio & OCR."""
        logger.info("[Orchestrator] Starting multi-session heuristics polling loop (1 Hz)...")
        while self.running:
            try:
                for session in list(self.sessions.values()):
                    # Segment Heuristics (Audio & OCR)
                    if not session.buffer:
                        continue
                    latest_seg = session.buffer.get_latest_segment()
                    if latest_seg and latest_seg != session.last_analyzed_segment and os.path.exists(latest_seg):
                        session.last_analyzed_segment = latest_seg
                        # Run audio & OCR in worker thread so event loop never blocks
                        audio_res = await asyncio.to_thread(session.audio_monitor.process_segment, latest_seg)
                        if audio_res:
                            session.extra_telemetry["audio_rms_db"] = audio_res["current_db"]
                            session.extra_telemetry["audio_spike"] = audio_res["is_spiking"]
                            if "waveform" in audio_res:
                                session.extra_telemetry["audio_waveform"] = audio_res["waveform"]

                        # 2. Analyze OCR
                        if ENABLE_OCR:
                            ocr_res = await asyncio.to_thread(session.ocr_engine.process_segment, latest_seg)
                            if ocr_res:
                                if ocr_res["balance"] is not None:
                                    session.extra_telemetry["ocr_balance"] = f"${ocr_res['balance']:,.2f}"
                                session.extra_telemetry["ocr_multiplier"] = f"{ocr_res['multiplier']:.1f}x"
                                session.extra_telemetry["ocr_pnl_delta"] = ocr_res["pnl_delta"]

                        # 3. Analyze Computer Vision, Emotion & Gambling HUD
                        heur_res = await asyncio.to_thread(self._process_video_and_cv_heuristics, session, latest_seg)
                        if heur_res:
                            if heur_res.get("stream_frame_b64"):
                                session.extra_telemetry["stream_frame_b64"] = heur_res["stream_frame_b64"]

                            if heur_res.get("cv_res"):
                                cv_res = heur_res["cv_res"]
                                session.extra_telemetry["cv_top_label"] = cv_res["top_label"]
                                session.extra_telemetry["cv_confidence"] = cv_res["confidence"]
                                session.extra_telemetry["cv_probabilities"] = cv_res["probabilities"]
                                session.extra_telemetry["cv_boxes"] = cv_res["detections"]
                                session.extra_telemetry["cv_latency_ms"] = cv_res["latency_ms"]
                                session.extra_telemetry["cv_thumbnail_b64"] = cv_res["thumbnail_b64"]

                            if heur_res.get("emotion_res"):
                                emo = heur_res["emotion_res"]
                                session.extra_telemetry["emotion_top"] = emo["top_emotion"]
                                session.extra_telemetry["emotion_confidence"] = emo["confidence"]
                                session.extra_telemetry["emotion_distribution"] = emo["emotions"]
                                session.extra_telemetry["emotion_valence"] = emo["valence"]
                                session.extra_telemetry["emotion_arousal"] = emo["arousal"]
                                session.extra_telemetry["emotion_tilt"] = emo["tilt_score"]
                                session.extra_telemetry["emotion_euphoria"] = emo["euphoria_score"]
                                session.extra_telemetry["is_tilting"] = emo["is_tilt_spike"]

                            if heur_res.get("gambling_res"):
                                g_res = heur_res["gambling_res"]
                                session.extra_telemetry["gambling_balance"] = g_res["balance"]
                                session.extra_telemetry["gambling_bet"] = g_res["bet"]
                                session.extra_telemetry["gambling_win"] = g_res["win"]
                                session.extra_telemetry["gambling_multiplier"] = g_res["multiplier"]
                                session.extra_telemetry["gambling_spin_state"] = g_res["spin_state"]

                    # 4. Chat State Description (every X seconds)
                    if session.chat_engine and session.chat_descriptor_service.enabled:
                        now = time.time()
                        if now - session.last_descriptor_time >= session.chat_descriptor_service.interval_seconds:
                            session.last_descriptor_time = now
                            msgs = session.chat_engine.drain_window_messages()
                            asyncio.create_task(
                                self._run_chat_descriptor(
                                    session, msgs, now - session.chat_descriptor_service.interval_seconds, now
                                )
                            )
            except Exception as e:
                logger.debug("[Orchestrator] Polling loop exception: %s", e)

            await asyncio.sleep(1.0)

    async def _run_chat_descriptor(self, session: StreamSession, msgs: List[dict], window_start: float, window_end: float):
        """Asynchronously summarizes chat messages using local LLM and saves to database."""
        try:
            result = await session.chat_descriptor_service.describe_chat_window(
                messages=msgs,
                channel=session.channel,
                window_start=window_start,
                window_end=window_end,
            )
            if result:
                session.latest_description = result
                await asyncio.to_thread(self.db.save_chat_descriptor, result)
                logger.info(
                    "[Session:%s][ChatDescriptor] %s",
                    session.channel, result.get("description", "")[:120]
                )
        except Exception as e:
            logger.debug("[Session:%s] Chat descriptor error: %s", session.channel, e)

    async def process_clip_trigger(self, session: StreamSession, context: dict):
        """Dispatches the full clipping DAG to a worker thread so the asyncio event loop stays responsive."""
        job_id = context.get("job_id")
        try:
            await asyncio.to_thread(self._execute_clipping_dag, session, context)
        except Exception as e:
            logger.error("[Orchestrator] process_clip_trigger failed for #%s (job %s): %s", session.channel, job_id, e, exc_info=True)
            if job_id:
                self.fail_job(job_id, str(e))

    def _execute_clipping_dag(self, session: StreamSession, context: dict):
        """Full clipping DAG for a specific stream session (preserving full original resolution)."""
        active_channel = session.channel
        logger.info("[DAG] Executing clipping pipeline for event: %s on #%s", context.get("trigger_source"), active_channel)
        timestamp = int(time.time())
        candidate_path = None
        out_video = None
        out_thumb = None

        job_id = context.get("job_id")
        if not job_id:
            job_id = self.create_job(active_channel, context)

        try:
            if context.get("trigger_source") != "manual_trigger":
                self.update_job_step(job_id, "delay", "done", 22, log_msg="Post-event reaction buffer accumulation completed.")
            self.update_job_step(job_id, "slicing", "running", 28, log_msg="Concatenating candidate stream slice from RAM ring buffer...")

            # Step 1: Zero-copy concatenation of candidate slice
            candidate_path = SegmentSlicer.extract_window(active_channel, duration_seconds=60)
            if not candidate_path or not os.path.exists(candidate_path):
                err = f"Failed to extract candidate slice from RAM ring buffer for #{active_channel}"
                logger.error("[DAG] %s; aborting clip pipeline.", err)
                self.fail_job(job_id, err)
                return
            # Step 2: Measure actual available duration of the concatenated slice
            candidate_duration = HardwareRenderEngine.get_duration(candidate_path)
            if candidate_duration < 6.0:
                err = f"Insufficient buffered video ({candidate_duration:.1f}s < 6s required)"
                logger.info("[DAG] %s for #%s; waiting for stream buffer to accumulate.", err, active_channel)
                self.fail_job(job_id, err)
                return

            self.update_job_step(
                job_id, "slicing", "done", 38,
                detail=f"{candidate_duration:.1f}s candidate window",
                log_msg=f"Candidate window extracted ({candidate_duration:.1f}s)."
            )

            # Step 3: Word-level speech transcription (faster-whisper)
            self.update_job_step(job_id, "transcribe", "running", 45, log_msg="Transcribing speech with local faster-whisper (int8)...")
            with self.transcription_lock:
                words = self.transcriber.transcribe_words(candidate_path)
            self.update_job_step(
                job_id, "transcribe", "done", 60,
                detail=f"{len(words)} words recognized",
                log_msg=f"Transcription complete ({len(words)} words aligned)."
            )

            # Step 4: Local boundary optimization bounded by actual duration
            self.update_job_step(job_id, "boundary", "running", 66, log_msg="Optimizing cut boundaries around speech pauses...")
            cut_info = self.boundary_ai.find_optimal_cut(words, context, total_duration=candidate_duration)
            cut_start = cut_info.get("cut_start", 0.0)
            cut_end = cut_info.get("cut_end", candidate_duration)
            target_duration = round(cut_end - cut_start, 2)
            title = cut_info.get("title", f"Clip from {active_channel}")
            caption = cut_info.get("caption", "#twitch #highlights")
            score = cut_info.get("score", context.get("score", 7))

            logger.info("[DAG] AI Cut Selected (#%s): [%.1fs - %.1fs] (target: %.1fs) | Title: %s", active_channel, cut_start, cut_end, target_duration, title)
            self.update_job_step(
                job_id, "boundary", "done", 75,
                detail=f"Cut: [{cut_start}s - {cut_end}s] ({target_duration}s)",
                log_msg=f"Selected boundaries [{cut_start}s - {cut_end}s] ({target_duration}s). Title: '{title}'."
            )

            # Step 5: Pure raw video cut (100% clean, no text, no overlays, no cropping)
            self.update_job_step(job_id, "render", "running", 80, log_msg="Cutting full-sized raw video using hardware acceleration...")
            out_video = f"/tmp/clipper_candidates/clip_{active_channel}_{timestamp}.mp4"
            out_thumb = f"/tmp/clipper_candidates/thumb_{active_channel}_{timestamp}.jpg"

            rendered = HardwareRenderEngine.render_clip(
                source_path=candidate_path,
                cut_start=cut_start,
                cut_end=cut_end,
                output_path=out_video,
                words=None,
                pnl_text="",
                enable_subs=False,
                crop_vertical=False,  # Full-sized raw video without cropping or overlays
            )

            if not rendered or not os.path.exists(out_video):
                err = f"Video rendering failed for {out_video}"
                logger.error("[DAG] %s; aborting clip save.", err)
                self.fail_job(job_id, err)
                return

            # Step 6: Measure actual rendered duration of the saved video file
            actual_video_duration = round(HardwareRenderEngine.get_duration(out_video), 2)
            if actual_video_duration <= 0.0:
                actual_video_duration = target_duration

            self.update_job_step(
                job_id, "render", "done", 90,
                detail=f"{actual_video_duration}s uncropped MP4",
                log_msg=f"Hardware render complete ({actual_video_duration}s, {os.path.getsize(out_video):,} bytes)."
            )

            # Step 7: Extract poster thumbnail
            thumb_ok = HardwareRenderEngine.extract_thumbnail(out_video, out_thumb, offset_seconds=1.5)
            if not thumb_ok:
                out_thumb = ""

            # Step 8: Store bundle locally in ./storage/clips
            self.update_job_step(job_id, "save", "running", 95, log_msg="Saving clip to local storage and SQLite database...")
            video_url, thumb_url = self.storage.store_clip_bundle(out_video, out_thumb if out_thumb else out_video)

            # Step 9: Persist to local SQLite database with verified actual duration
            clip_record = {
                "channel_name": active_channel,
                "video_url": video_url,
                "thumbnail_url": thumb_url,
                "duration_seconds": actual_video_duration,
                "cut_start": cut_start,
                "cut_end": cut_end,
                "chat_velocity_peak": context.get("chat_instant", 0.0),
                "spike_ratio": context.get("chat_ratio", 1.0),
                "ocr_pnl_delta": context.get("pnl_delta", 0.0),
                "ocr_multiplier": context.get("win_multiplier", 1.0),
                "heuristic_score": score,
                "suggested_title": title,
                "suggested_caption": caption,
                "transcript_json": words,
                "status": "pending_triage",
            }
            clip_id = self.db.save_clip(clip_record)

            logger.info("[DAG] Successfully stored full-sized clip %s locally! Video URL: %s", clip_id, video_url)

            clip_summary = {
                "id": clip_id,
                "channel": active_channel,
                "title": title,
                "score": score,
                "duration": actual_video_duration,
                "duration_seconds": actual_video_duration,
                "video_url": video_url,
            }

            # Mark job completed
            self.complete_job(job_id, clip_summary)

            # Step 10: Notify HUD client
            telemetry_server.notify_new_clip(clip_summary)

        except Exception as err:
            logger.error("[DAG] Error executing clipping pipeline for #%s: %s", active_channel, err, exc_info=True)
            self.fail_job(job_id, str(err))
        finally:
            for p in (candidate_path, out_video, out_thumb):
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    async def start_local_http_server(self):
        """Starts a native async aiohttp web server serving the HUD client, local clips, and REST APIs."""
        static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
        clips_dir = os.path.abspath(STORAGE_DIR)
        os.makedirs(clips_dir, exist_ok=True)
        os.makedirs(static_dir, exist_ok=True)

        @web.middleware
        async def no_cache_middleware(request, handler):
            resp = await handler(request)
            if request.path.startswith("/static") or request.path.endswith(".html") or request.path == "/":
                resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                resp.headers["Pragma"] = "no-cache"
                resp.headers["Expires"] = "0"
            return resp

        app = web.Application(middlewares=[cors_middleware, no_cache_middleware])

        async def index_handler(request):
            return web.FileResponse(os.path.join(static_dir, "index.html"))

        # Multi-session APIs
        async def get_sessions_handler(request):
            return web.json_response(self.get_all_sessions_status())

        async def post_session_handler(request):
            try:
                data = await request.json()
                channel = data.get("channel", "")
                simulate = bool(data.get("simulate", False))
                res = await self.add_session(channel, simulate=simulate)
                return web.json_response(res)
            except ValueError as ve:
                return web.json_response({"error": str(ve)}, status=400)
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)

        async def delete_session_handler(request):
            channel = request.match_info["channel"]
            success = await self.remove_session(channel)
            return web.json_response({"success": success, "channel": channel})

        # Backward compatibility single-channel APIs
        async def get_channel_handler(request):
            return web.json_response(self.get_status())

        async def post_channel_handler(request):
            try:
                data = await request.json()
                target_channel = data.get("channel", "")
                result = await self.set_channel(target_channel)
                return web.json_response(result)
            except Exception as e:
                return web.json_response({"error": str(e)}, status=400)

        # Clip Gallery & Management APIs
        async def get_clips_handler(request):
            limit = int(request.query.get("limit", 50))
            channel_filter = request.query.get("channel")
            if channel_filter:
                channel_filter = clean_channel_name(channel_filter)
            clips = self.db.get_recent_clips(limit=limit, channel=channel_filter)
            return web.json_response(clips)

        async def delete_clip_handler(request):
            clip_id = request.match_info["id"]
            clip = self.db.get_clip(clip_id)
            if not clip:
                return web.json_response({"error": "Clip not found"}, status=404)
            # Delete physical files
            self.storage.delete_clip_bundle(clip.get("video_url"), clip.get("thumbnail_url"))
            # Delete database row
            success = self.db.delete_clip(clip_id)
            logger.info("[LocalServer] Deleted clip %s (success=%s)", clip_id, success)
            return web.json_response({"success": success, "id": clip_id})

        async def post_clip_status_handler(request):
            clip_id = request.match_info["id"]
            try:
                data = await request.json()
                status = data.get("status", "approved")
                success = self.db.update_clip_status(clip_id, status)
                return web.json_response({"success": success, "status": status})
            except Exception:
                return web.json_response({"error": "Invalid request"}, status=400)

        # Active Clipping Jobs APIs
        async def get_jobs_handler(request):
            return web.json_response(self.get_active_jobs())

        async def get_job_detail_handler(request):
            job_id = request.match_info["id"]
            job = self.active_jobs.get(job_id)
            if not job:
                return web.json_response({"error": "Job not found"}, status=404)
            return web.json_response(job)

        # Manual Clip Trigger APIs (Newest 60 Seconds from RAM Buffer)
        async def post_manual_clip_handler(request):
            channel = request.match_info["channel"]
            try:
                result = await self.trigger_manual_clip(channel)
                return web.json_response(result)
            except ValueError as ve:
                return web.json_response({"error": str(ve)}, status=404)
            except Exception as ex:
                logger.error("[LocalServer] Manual clip failed for #%s: %s", channel, ex)
                return web.json_response({"error": str(ex)}, status=500)

        async def post_clip_current_handler(request):
            try:
                body = await request.json() if request.can_read_body else {}
            except Exception:
                body = {}
            target = body.get("channel") or self.channel
            if not target and self.sessions:
                target = list(self.sessions.keys())[0]
            if not target:
                return web.json_response({"error": "No active stream session to clip."}, status=400)
            try:
                result = await self.trigger_manual_clip(target)
                return web.json_response(result)
            except Exception as e:
                return web.json_response({"error": str(e)}, status=400)

        app.router.add_get("/", index_handler)
        app.router.add_get("/api/sessions", get_sessions_handler)
        app.router.add_post("/api/sessions", post_session_handler)
        app.router.add_delete("/api/sessions/{channel}", delete_session_handler)
        app.router.add_post("/api/sessions/{channel}/clip", post_manual_clip_handler)

        app.router.add_get("/api/channel", get_channel_handler)
        app.router.add_post("/api/channel", post_channel_handler)
        app.router.add_post("/api/clip", post_clip_current_handler)

        # Chat Descriptors & Settings APIs
        async def get_descriptors_handler(request):
            limit = int(request.query.get("limit", 20))
            channel_filter = request.query.get("channel")
            descriptors = self.db.get_recent_descriptors(channel=channel_filter, limit=limit)
            return web.json_response(descriptors)

        async def post_settings_descriptor_handler(request):
            try:
                data = await request.json()
                interval = data.get("interval_seconds")
                model = data.get("model_name")
                gemini_key = data.get("gemini_api_key")
                gemini_model = data.get("gemini_model")
                timeout_sec = data.get("timeout_seconds")
                enabled = data.get("enabled")
                channel = data.get("channel")

                target_sessions = [self.sessions[channel]] if (channel and channel in self.sessions) else list(self.sessions.values())
                for s in target_sessions:
                    if interval is not None:
                        s.chat_descriptor_service.interval_seconds = max(10, int(interval))
                    if timeout_sec is not None:
                        s.chat_descriptor_service.timeout_seconds = max(5.0, float(timeout_sec))
                    if model is not None:
                        s.chat_descriptor_service.local_model_name = str(model)
                    if gemini_key is not None:
                        s.chat_descriptor_service.gemini_api_key = str(gemini_key)
                    if gemini_model is not None:
                        s.chat_descriptor_service.gemini_model = str(gemini_model)
                    if enabled is not None:
                        s.chat_descriptor_service.enabled = bool(enabled)
                return web.json_response({
                    "success": True,
                    "interval_seconds": interval,
                    "timeout_seconds": timeout_sec,
                    "model_name": model,
                    "gemini_model": gemini_model,
                    "provider": target_sessions[0].chat_descriptor_service.provider if target_sessions else "unknown",
                    "enabled": enabled,
                    "updated_sessions": [s.channel for s in target_sessions],
                })
            except Exception as e:
                return web.json_response({"error": str(e)}, status=400)

        app.router.add_get("/api/clips", get_clips_handler)
        app.router.add_delete("/api/clips/{id}", delete_clip_handler)
        app.router.add_post("/api/clips/{id}/status", post_clip_status_handler)

        app.router.add_get("/api/jobs", get_jobs_handler)
        app.router.add_get("/api/jobs/{id}", get_job_detail_handler)

        app.router.add_get("/api/descriptors", get_descriptors_handler)
        app.router.add_post("/api/settings/chat-descriptor", post_settings_descriptor_handler)

        async def post_summarize_screen_handler(request):
            """On-demand multimodal screen & chat summarization."""
            try:
                raw_channel = request.match_info.get("channel") or request.query.get("channel")
                if not raw_channel and request.can_read_body:
                    try:
                        body = await request.json()
                        raw_channel = body.get("channel")
                    except Exception:
                        pass

                channel = clean_channel_name(raw_channel) if raw_channel else None
                if not channel:
                    channel = list(self.sessions.keys())[0] if self.sessions else None

                if not channel or channel not in self.sessions:
                    return web.json_response({"error": f"Channel '{raw_channel or channel}' is not actively monitored"}, status=404)

                session = self.sessions[channel]
                messages = list(session.chat_engine.recent_messages) if session.chat_engine else []

                result = await session.screen_summarizer.summarize_screen(
                    channel=session.channel,
                    messages=messages,
                )
                session.latest_screen_summary = result
                await asyncio.to_thread(self.db.save_screen_summary, result)
                return web.json_response(result)
            except Exception as e:
                logger.error("[LocalServer] Error summarizing screen: %s", e, exc_info=True)
                return web.json_response({"error": str(e)}, status=500)

        async def get_screen_summaries_handler(request):
            limit = int(request.query.get("limit", 10))
            channel = request.query.get("channel")
            if channel:
                channel = clean_channel_name(channel)
            summaries = await asyncio.to_thread(self.db.get_recent_screen_summaries, channel, limit)
            return web.json_response(summaries)

        async def post_discover_watchers_handler(request):
            """Discovers Twitch streams watching or reacting to a channel, evaluated by an autonomous agent."""
            try:
                channel = request.match_info.get("channel") or request.query.get("channel")
                force_simulation = request.query.get("simulate", "false").lower() in ("true", "1")
                include_simulation = request.query.get("include_simulation", "true").lower() in ("true", "1")

                if not channel and request.can_read_body:
                    try:
                        body = await request.json()
                        channel = body.get("channel")
                        if "force_simulation" in body:
                            force_simulation = bool(body.get("force_simulation"))
                        if "include_simulation" in body:
                            include_simulation = bool(body.get("include_simulation"))
                    except Exception:
                        pass

                clean = clean_channel_name(channel) if channel else None
                if not clean:
                    clean = list(self.sessions.keys())[0] if self.sessions else "marlon"

                res = await self.watch_party_finder.discover_and_evaluate(
                    target_channel=clean,
                    include_simulation_if_empty=include_simulation,
                    force_simulation=force_simulation,
                )
                # Annotate each candidate with whether it is already actively hooked into Clipper
                for cand in res.get("candidates", []):
                    c_login = cand.get("login")
                    cand["is_active_session"] = c_login in self.sessions

                return web.json_response(res)
            except Exception as e:
                logger.error("[LocalServer] Error in watch party discovery: %s", e, exc_info=True)
                return web.json_response({"error": str(e)}, status=500)

        async def get_watchers_handler(request):
            channel = clean_channel_name(request.match_info.get("channel") or request.query.get("channel") or "")
            if not channel:
                channel = list(self.sessions.keys())[0] if self.sessions else "marlon"
            cached = self.watch_party_finder.get_cached_results(channel)
            if not cached:
                cached = await self.watch_party_finder.discover_and_evaluate(channel)
            for cand in cached.get("candidates", []):
                cand["is_active_session"] = cand.get("login") in self.sessions
            return web.json_response(cached)

        app.router.add_post("/api/sessions/{channel}/discover-watchers", post_discover_watchers_handler)
        app.router.add_post("/api/discover-watchers", post_discover_watchers_handler)
        app.router.add_get("/api/sessions/{channel}/watchers", get_watchers_handler)
        app.router.add_get("/api/watchers", get_watchers_handler)

        app.router.add_post("/api/sessions/{channel}/summarize-screen", post_summarize_screen_handler)
        app.router.add_post("/api/summarize-screen", post_summarize_screen_handler)
        app.router.add_get("/api/screen-summaries", get_screen_summaries_handler)

        async def get_live_playlist_handler(request):
            """Generates a live HLS m3u8 playlist from active TS segments in the RAM ring buffer."""
            channel = clean_channel_name(request.match_info.get("channel", ""))
            if not channel or channel not in self.sessions:
                return web.Response(text="#EXTM3U\n", status=404, content_type="application/vnd.apple.mpegurl")
            session = self.sessions[channel]
            if not session.buffer or not os.path.exists(session.buffer.shm_dir):
                return web.Response(text="#EXTM3U\n", status=503, content_type="application/vnd.apple.mpegurl")

            segments = session.buffer.get_active_segments()
            if not segments:
                return web.Response(text="#EXTM3U\n", status=503, content_type="application/vnd.apple.mpegurl")

            usable = segments[:-1] if len(segments) > 1 else segments
            recent = usable[-5:]
            target_duration = getattr(session.buffer, "segment_time", 10)

            if not hasattr(session, "hls_media_sequence"):
                session.hls_media_sequence = 0
                session.hls_last_first_seg = None

            first_seg = recent[0] if recent else None
            if session.hls_last_first_seg and first_seg != session.hls_last_first_seg:
                session.hls_media_sequence += 1
            session.hls_last_first_seg = first_seg

            lines = [
                "#EXTM3U",
                "#EXT-X-VERSION:3",
                f"#EXT-X-TARGETDURATION:{target_duration}",
                f"#EXT-X-MEDIA-SEQUENCE:{session.hls_media_sequence}",
            ]
            for seg_path in recent:
                seg_name = os.path.basename(seg_path)
                try:
                    mtime = int(os.path.getmtime(seg_path))
                except OSError:
                    mtime = 0
                lines.append(f"#EXTINF:{target_duration}.0,")
                lines.append(f"/api/sessions/{channel}/segments/{seg_name}?t={mtime}")

            playlist_content = "\n".join(lines) + "\n"
            return web.Response(
                text=playlist_content,
                content_type="application/vnd.apple.mpegurl",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Access-Control-Allow-Origin": "*",
                },
            )

        async def get_live_segment_handler(request):
            """Serves a raw MPEG-TS video segment from the RAM ring buffer."""
            channel = clean_channel_name(request.match_info.get("channel", ""))
            segment = request.match_info.get("segment", "")
            if ".." in segment or "/" in segment or not segment.endswith(".ts"):
                return web.Response(text="Invalid segment", status=400)
            if not channel or channel not in self.sessions:
                return web.Response(text="Session not found", status=404)
            session = self.sessions[channel]
            if not session.buffer or not os.path.exists(session.buffer.shm_dir):
                return web.Response(text="Buffer not found", status=404)
            seg_path = os.path.join(session.buffer.shm_dir, segment)
            if not os.path.exists(seg_path):
                return web.Response(text="Segment not found", status=404)
            return web.FileResponse(
                seg_path,
                headers={
                    "Content-Type": "video/MP2T",
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "public, max-age=3600",
                },
            )

        app.router.add_get("/api/sessions/{channel}/live.m3u8", get_live_playlist_handler)
        app.router.add_get("/api/sessions/{channel}/segments/{segment}", get_live_segment_handler)

        # Node Graph Studio APIs
        async def get_graph_handler(request):
            return web.json_response(self.graph_manager.get_graph())

        async def post_graph_sync_handler(request):
            try:
                data = await request.json()
                success, msg = self.graph_manager.sync_graph(data)
                return web.json_response({"success": success, "message": msg}, status=200 if success else 400)
            except Exception as e:
                return web.json_response({"error": str(e)}, status=400)

        async def post_graph_node_param_handler(request):
            node_id = request.match_info["id"]
            try:
                data = await request.json()
                param = data.get("param")
                value = data.get("value")
                success = self.graph_manager.update_node_param(node_id, param, value)
                return web.json_response({"success": success})
            except Exception as e:
                return web.json_response({"error": str(e)}, status=400)

        app.router.add_get("/api/graph", get_graph_handler)
        app.router.add_post("/api/graph/sync", post_graph_sync_handler)
        app.router.add_post("/api/graph/nodes/{id}/param", post_graph_node_param_handler)

        # Static mounts
        app.router.add_static("/clips", clips_dir)
        app.router.add_static("/static", static_dir)
        app.router.add_static("/", static_dir)

        self.http_runner = web.AppRunner(app)
        await self.http_runner.setup()
        site = web.TCPSite(self.http_runner, "0.0.0.0", HTTP_PORT, reuse_address=True, reuse_port=True)
        await site.start()
        logger.info("[LocalServer] Async web server active at http://localhost:%d", HTTP_PORT)

    async def run(self):
        """Initializes and runs all pipeline services locally."""
        self.running = True
        self.loop = asyncio.get_running_loop()

        logger.info("=" * 70)
        logger.info("  AUTONOMOUS TWITCH STREAM CLIPPER (MULTI-SESSION LOCAL MODE)")
        logger.info("  Web HUD & Multi-Tab UI: http://localhost:%d", HTTP_PORT)
        logger.info("  Storage Path:           %s", os.path.abspath(STORAGE_DIR))
        logger.info("  Database Path:          %s", self.db._sqlite_path)
        logger.info("=" * 70)

        # Start native async HTTP server
        await self.start_local_http_server()

        # Start all currently registered sessions (if any)
        for session in self.sessions.values():
            session.start(self.loop)

        # Setup shutdown signal handlers
        if hasattr(signal, "SIGHUP"):
            try:
                signal.signal(signal.SIGHUP, signal.SIG_IGN)
            except Exception:
                pass

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self.loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except NotImplementedError:
                pass

        try:
            import websockets
            await websockets.serve(
                telemetry_server.ws_handler,
                "0.0.0.0",
                telemetry_server.PORT,
                reuse_address=True,
                reuse_port=True,
            )
            logger.info("[Telemetry] WebSocket active on ws://0.0.0.0:%d", telemetry_server.PORT)

            await asyncio.gather(
                telemetry_server.broadcast_loop(),
                self.heuristics_polling_loop(),
            )
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Gracefully stops all background sessions."""
        if not self.running:
            return
        logger.info("[Orchestrator] Halting local clipper sessions (%d active)...", len(self.sessions))
        self.running = False
        for session in list(self.sessions.values()):
            session.stop()
        self.sessions.clear()
        if self.http_runner:
            try:
                await self.http_runner.cleanup()
            except Exception:
                pass
        logger.info("[Orchestrator] Shutdown complete.")


if __name__ == "__main__":
    orchestrator = StreamClipperOrchestrator()
    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        logger.info("Local clipper halted.")
        sys.exit(0)
