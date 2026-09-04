import asyncio
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

from services.ingest.stream_buffer import StreamRingBuffer
from services.ingest.twitch_irc import TwitchChatVelocityEngine
from services.heuristics.audio_monitor import AudioDecibelMonitor
from services.heuristics.ocr_engine import BoundedRegionOCR
from services.heuristics.gate_evaluator import GateEvaluator
from services.heuristics.chat_sentiment import ChatSentimentAnalyzer
from services.processor.slicer import SegmentSlicer
from services.processor.transcriber import AudioTranscriber
from services.processor.boundary_ai import BoundaryOptimizer
from services.processor.render_engine import HardwareRenderEngine
from services.storage.local_storage import LocalStorageManager
from services.storage.db import DatabaseRepository
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
ENABLE_BURN_IN_SUBS = os.getenv("ENABLE_BURN_IN_SUBS", "false").lower() == "true"


class StreamSession:
    """Represents an independent monitoring session for a single Twitch channel."""

    def __init__(self, channel: str, orchestrator: "StreamClipperOrchestrator"):
        self.channel = channel.lower().lstrip("#").strip()
        self.orchestrator = orchestrator

        # 1. Video Buffer
        self.buffer = StreamRingBuffer(self.channel)

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

        # 5. Gate Evaluator
        self.gate_evaluator = GateEvaluator(
            on_trigger_dispatch=self._on_clip_trigger,
            on_trigger_activated=self._on_trigger_activated,
            debounce_seconds=DEBOUNCE_SEC,
            post_event_delay_seconds=POST_DELAY_SEC,
        )

        # Telemetry metrics
        self.extra_telemetry = {
            "audio_rms_db": -60.0,
            "audio_spike": False,
            "audio_waveform": [],
            "ocr_balance": "$0.00",
            "ocr_multiplier": "1.0x",
            "ocr_pnl_delta": 0.0,
        }
        self.last_analyzed_segment: Optional[str] = None
        self.sentiment_analyzer = ChatSentimentAnalyzer()
        self.last_sentiment_time = time.time()
        self.recent_sentiments = deque(maxlen=50)

        # Pre-load saved sentiments from DB if present
        try:
            saved_sentiments = self.orchestrator.db.get_recent_sentiments(channel=self.channel, limit=30)
            for s in reversed(saved_sentiments):
                self.recent_sentiments.append(s)
        except Exception:
            pass

    def start(self, loop: asyncio.AbstractEventLoop):
        """Starts HLS ingestion and connects to IRC WebSocket."""
        logger.info("[Session:%s] Starting stream buffer and chat listener...", self.channel)
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
        self.gate_evaluator.evaluate_signals(
            source="chat_spike",
            chat_instant=instant,
            chat_ratio=ratio,
            win_multiplier=self.ocr_engine.current_multiplier,
            pnl_delta=self.ocr_engine.pnl_delta,
            audio_db=self.audio_monitor.current_db,
            audio_delta=self.audio_monitor.delta_db,
        )

    def _on_audio_spike(self, instant_db: float, delta_db: float):
        logger.info("[Session:%s][AudioSpike] level=%.1f dB, jump=+%.1f dB", self.channel, instant_db, delta_db)
        self.gate_evaluator.evaluate_signals(
            source="audio_spike",
            chat_instant=self.chat_engine.v_instant,
            chat_ratio=self.chat_engine.spike_ratio,
            win_multiplier=self.ocr_engine.current_multiplier,
            pnl_delta=self.ocr_engine.pnl_delta,
            audio_db=instant_db,
            audio_delta=delta_db,
        )

    def _on_ocr_trigger(self, multiplier: float, delta: float):
        logger.info("[Session:%s][OCRTrigger] multiplier=%.1fx, delta=$%.2f", self.channel, multiplier, delta)
        self.gate_evaluator.evaluate_signals(
            source="ocr_multiplier",
            chat_instant=self.chat_engine.v_instant,
            chat_ratio=self.chat_engine.spike_ratio,
            win_multiplier=multiplier,
            pnl_delta=delta,
            audio_db=self.audio_monitor.current_db,
            audio_delta=self.audio_monitor.delta_db,
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
            "recent_sentiments": list(self.recent_sentiments),
            "audio_rms_db": self.extra_telemetry["audio_rms_db"],
            "audio_spike": self.extra_telemetry["audio_spike"],
            "audio_waveform": self.extra_telemetry.get("audio_waveform", []),
            "ocr_balance": self.extra_telemetry["ocr_balance"],
            "ocr_multiplier": self.extra_telemetry["ocr_multiplier"],
            "ocr_pnl_delta": self.extra_telemetry["ocr_pnl_delta"],
            "buffered_messages": calc["buffered_messages"],
            "total_messages": calc.get("total_messages", 0),
            "buffered_segments": self.buffer.get_segment_count() if self.buffer else 0,
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

        # Hook telemetry providers into telemetry server
        telemetry_server.sessions_telemetry_provider = self.get_all_telemetry
        telemetry_server.active_jobs_provider = self.get_active_jobs

    def create_job(self, channel: str, context: dict) -> str:
        """Instantiates a new tracked clipping pipeline job with real-time step progress and logs."""
        job_id = f"job_{channel}_{int(time.time())}"
        now_str = time.strftime("%H:%M:%S")
        source = context.get("trigger_source", "spike")
        score = context.get("score", 7)
        delay = context.get("post_event_delay", 15.0)

        job = {
            "id": job_id,
            "channel": channel,
            "status": "processing",
            "score": score,
            "source": source,
            "created_at": time.time(),
            "updated_at": time.time(),
            "current_step": f"Buffering post-event reaction (+{int(delay)}s)...",
            "progress_pct": 12,
            "steps": [
                {"id": "trigger", "name": "Spike Trigger Activated", "status": "done", "detail": f"Signal: {source} (Score: {score}/10)"},
                {"id": "delay", "name": "Post-Event Delay Buffer", "status": "running", "detail": f"Capturing +{int(delay)}s reaction window"},
                {"id": "slicing", "name": "RAM Buffer Slicing", "status": "pending", "detail": "Zero-copy TS slice concatenation"},
                {"id": "transcribe", "name": "Speech Transcription", "status": "pending", "detail": "faster-whisper word alignment"},
                {"id": "boundary", "name": "Speech Pause Optimization", "status": "pending", "detail": "Boundary trimming on speech pauses"},
                {"id": "render", "name": "Raw Video Extraction", "status": "pending", "detail": "Hardware-accelerated uncropped cut"},
                {"id": "save", "name": "Storage & Database", "status": "pending", "detail": "Persisting to local disk & gallery"},
            ],
            "logs": [
                f"[{now_str}] Excitement spike triggered via {source} (Score: {score}/10).",
                f"[{now_str}] Post-event buffer initiated (+{int(delay)}s reaction capture).",
            ],
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

    async def add_session(self, channel: str) -> dict:
        """Adds a new channel session and begins ingestion."""
        clean = channel.lower().lstrip("#").strip()
        if not clean:
            raise ValueError("Channel name cannot be empty")

        if clean in self.sessions:
            logger.info("[Orchestrator] Channel #%s already active", clean)
            return self.sessions[clean].get_status()

        session = StreamSession(clean, self)
        if self.running and self.loop:
            session.start(self.loop)
        self.sessions[clean] = session

        logger.info("[Orchestrator] Active sessions (%d total): %s", len(self.sessions), list(self.sessions.keys()))
        return session.get_status()

    async def remove_session(self, channel: str) -> bool:
        """Stops and removes an existing channel session."""
        clean = channel.lower().lstrip("#").strip()
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
        clean = new_channel.lower().lstrip("#").strip() if new_channel else ""
        if not clean:
            for ch in list(self.sessions.keys()):
                await self.remove_session(ch)
            return self.get_status()
        else:
            return await self.add_session(clean)

    async def heuristics_polling_loop(self):
        """Periodically samples the newest video segment for each active session for audio & OCR."""
        logger.info("[Orchestrator] Starting multi-session heuristics polling loop (1 Hz)...")
        while self.running:
            try:
                for session in list(self.sessions.values()):
                    # 1. 60-Second Chat Sentiment Analysis Cycle
                    now = time.time()
                    if now - session.last_sentiment_time >= 60.0:
                        w_start = session.last_sentiment_time
                        session.last_sentiment_time = now
                        if session.chat_engine:
                            msgs = session.chat_engine.drain_window_messages()
                            sentiment = session.sentiment_analyzer.analyze_window(
                                messages=msgs,
                                channel=session.channel,
                                window_start=w_start,
                                window_end=now,
                            )
                            self.db.save_chat_sentiment(sentiment)
                            session.recent_sentiments.append(sentiment)
                            logger.info(
                                "[Session:%s][Sentiment60s] %s (%d msgs, score=%.2f)",
                                session.channel,
                                sentiment["descriptor"],
                                sentiment["message_count"],
                                sentiment["score"],
                            )

                    # 2. Segment Heuristics (Audio & OCR)
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
            except Exception as e:
                logger.debug("[Orchestrator] Polling loop exception: %s", e)

            await asyncio.sleep(1.0)

    async def process_clip_trigger(self, session: StreamSession, context: dict):
        """Dispatches the full clipping DAG to a worker thread so the asyncio event loop stays responsive."""
        await asyncio.to_thread(self._execute_clipping_dag, session, context)

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

        self.update_job_step(job_id, "delay", "done", 22, log_msg="Post-event reaction buffer accumulation completed.")
        self.update_job_step(job_id, "slicing", "running", 28, log_msg="Concatenating candidate stream slice from RAM ring buffer...")

        # Step 1: Zero-copy concatenation of candidate slice
        candidate_path = SegmentSlicer.extract_window(active_channel, duration_seconds=60)
        if not candidate_path or not os.path.exists(candidate_path):
            err = f"Failed to extract candidate slice from RAM ring buffer for #{active_channel}"
            logger.error("[DAG] %s; aborting clip pipeline.", err)
            self.fail_job(job_id, err)
            return

        try:
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

        app = web.Application(middlewares=[cors_middleware])

        async def index_handler(request):
            return web.FileResponse(os.path.join(static_dir, "index.html"))

        # Multi-session APIs
        async def get_sessions_handler(request):
            return web.json_response(self.get_all_sessions_status())

        async def post_session_handler(request):
            try:
                data = await request.json()
                channel = data.get("channel", "")
                res = await self.add_session(channel)
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

        # 60s Chat Sentiment Descriptors API
        async def get_sentiments_handler(request):
            channel_filter = request.query.get("channel")
            limit = int(request.query.get("limit", 50))
            sentiments = self.db.get_recent_sentiments(limit=limit, channel=channel_filter)
            return web.json_response(sentiments)

        app.router.add_get("/", index_handler)
        app.router.add_get("/api/sessions", get_sessions_handler)
        app.router.add_post("/api/sessions", post_session_handler)
        app.router.add_delete("/api/sessions/{channel}", delete_session_handler)

        app.router.add_get("/api/channel", get_channel_handler)
        app.router.add_post("/api/channel", post_channel_handler)

        app.router.add_get("/api/clips", get_clips_handler)
        app.router.add_delete("/api/clips/{id}", delete_clip_handler)
        app.router.add_post("/api/clips/{id}/status", post_clip_status_handler)

        app.router.add_get("/api/sentiments", get_sentiments_handler)
        app.router.add_get("/api/jobs", get_jobs_handler)
        app.router.add_get("/api/jobs/{id}", get_job_detail_handler)

        # Static mounts
        app.router.add_static("/clips", clips_dir)
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
