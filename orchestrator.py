import asyncio
import json
import logging
import os
import signal
import sys
import time
from typing import Optional
from dotenv import load_dotenv
from aiohttp import web

from services.ingest.stream_buffer import StreamRingBuffer
from services.ingest.twitch_irc import TwitchChatVelocityEngine
from services.heuristics.audio_monitor import AudioDecibelMonitor
from services.heuristics.ocr_engine import BoundedRegionOCR
from services.heuristics.gate_evaluator import GateEvaluator
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

DEBOUNCE_SEC = float(os.getenv("HEURISTIC_DEBOUNCE_SECONDS", "90"))
POST_DELAY_SEC = float(os.getenv("POST_EVENT_DELAY_SECONDS", "15"))
HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))
STORAGE_DIR = os.getenv("STORAGE_DIR", "./storage/clips")
ENABLE_OCR = os.getenv("OCR_ENABLED", "true").lower() == "true"
ENABLE_BURN_IN_SUBS = os.getenv("ENABLE_BURN_IN_SUBS", "true").lower() == "true"


@web.middleware
async def cors_middleware(request, handler):
    """Adds CORS headers to all responses."""
    if request.method == "OPTIONS":
        response = web.Response()
    else:
        response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


class StreamClipperOrchestrator:
    """Master supervisor managing 100% local ingestion, heuristics, clipping, and telemetry."""

    def __init__(self):
        self.running = False
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.http_runner: Optional[web.AppRunner] = None

        # Starts with NO channel on startup - configured from Web UI
        self.channel: Optional[str] = None
        self.buffer: Optional[StreamRingBuffer] = None
        self.chat_engine: Optional[TwitchChatVelocityEngine] = None
        self.chat_task: Optional[asyncio.Task] = None

        # 1. Local Storage & Database
        self.storage = LocalStorageManager(storage_dir=STORAGE_DIR)
        self.db = DatabaseRepository()

        # 2. Multi-modal Heuristics
        self.audio_monitor = AudioDecibelMonitor(
            jump_db_threshold=float(os.getenv("HEURISTIC_AUDIO_DB_THRESHOLD", "12.0")),
            on_spike_callback=self._on_audio_spike,
        )

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

        self.gate_evaluator = GateEvaluator(
            on_trigger_dispatch=self.process_clip_trigger,
            debounce_seconds=DEBOUNCE_SEC,
            post_event_delay_seconds=POST_DELAY_SEC,
        )

        # 3. Processor Pipeline (100% Local)
        self.transcriber = AudioTranscriber()
        self.boundary_ai = BoundaryOptimizer()

    def get_status(self) -> dict:
        """Returns the current channel and monitoring status."""
        return {
            "channel": self.channel,
            "status": "monitoring" if self.channel else "idle",
            "is_buffering": self.buffer.is_alive() if self.buffer else False,
            "buffered_segments": len(self.buffer.get_active_segments()) if self.buffer else 0,
        }

    async def set_channel(self, new_channel: Optional[str]) -> dict:
        """Dynamically binds or unbinds the target Twitch channel at runtime."""
        clean_channel = new_channel.lower().lstrip("#").strip() if new_channel else ""

        if clean_channel and clean_channel == self.channel:
            return self.get_status()

        # Clean up existing channel processes if any
        if self.buffer:
            self.buffer.stop()
            self.buffer = None

        if self.chat_engine:
            self.chat_engine.stop()
            self.chat_engine = None

        if self.chat_task and not self.chat_task.done():
            self.chat_task.cancel()
            self.chat_task = None

        telemetry_server.reset_telemetry()

        # Disconnect / set empty
        if not clean_channel:
            self.channel = None
            telemetry_server.engine = None
            logger.info("[Orchestrator] Active channel cleared. System is now IDLE.")
            return self.get_status()

        # Bind new channel
        self.channel = clean_channel
        self.buffer = StreamRingBuffer(self.channel)
        self.buffer.start()

        self.chat_engine = TwitchChatVelocityEngine(
            self.channel,
            on_spike_callback=self._on_chat_spike,
            spike_ratio_threshold=float(os.getenv("HEURISTIC_CHAT_RATIO_THRESHOLD", "3.0")),
            instant_min_threshold=float(os.getenv("HEURISTIC_CHAT_INSTANT_MIN", "10.0")),
        )
        telemetry_server.engine = self.chat_engine

        if self.running and self.loop:
            self.chat_task = self.loop.create_task(self.chat_engine.listen())

        logger.info("[Orchestrator] Switched active channel to #%s", self.channel)
        return self.get_status()

    def _on_chat_spike(self, instant: float, ratio: float):
        """Invoked when chat IRC crosses spike velocity thresholds."""
        logger.info("[TriggerSource:Chat] instant=%.2f msgs/s, ratio=%.2fx", instant, ratio)
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
        """Invoked when audio volume jumps abruptly."""
        logger.info("[TriggerSource:Audio] level=%.1f dB, jump=+%.1f dB", instant_db, delta_db)
        instant_rate = self.chat_engine.v_instant if self.chat_engine else 0.0
        spike_ratio = self.chat_engine.spike_ratio if self.chat_engine else 1.0
        self.gate_evaluator.evaluate_signals(
            source="audio_spike",
            chat_instant=instant_rate,
            chat_ratio=spike_ratio,
            win_multiplier=self.ocr_engine.current_multiplier,
            pnl_delta=self.ocr_engine.pnl_delta,
            audio_db=instant_db,
            audio_delta=delta_db,
        )

    def _on_ocr_trigger(self, multiplier: float, delta: float):
        """Invoked when OCR registers a significant win multiplier."""
        logger.info("[TriggerSource:OCR] multiplier=%.1fx, delta=$%.2f", multiplier, delta)
        instant_rate = self.chat_engine.v_instant if self.chat_engine else 0.0
        spike_ratio = self.chat_engine.spike_ratio if self.chat_engine else 1.0
        self.gate_evaluator.evaluate_signals(
            source="ocr_multiplier",
            chat_instant=instant_rate,
            chat_ratio=spike_ratio,
            win_multiplier=multiplier,
            pnl_delta=delta,
            audio_db=self.audio_monitor.current_db,
            audio_delta=self.audio_monitor.delta_db,
        )

    async def heuristics_polling_loop(self):
        """Periodically samples the newest video segment for audio analysis and OCR."""
        logger.info("[Orchestrator] Starting heuristics polling loop (1 Hz)...")
        while self.running:
            try:
                if self.buffer and self.channel:
                    latest_seg = self.buffer.get_latest_segment()
                    if latest_seg and os.path.exists(latest_seg):
                        # 1. Analyze audio
                        audio_res = self.audio_monitor.process_segment(latest_seg)
                        if audio_res:
                            telemetry_server.update_audio_telemetry(
                                audio_res["current_db"],
                                audio_res["is_spiking"],
                            )

                        # 2. Analyze OCR
                        if ENABLE_OCR:
                            ocr_res = self.ocr_engine.process_segment(latest_seg)
                            if ocr_res:
                                telemetry_server.update_ocr_telemetry(
                                    ocr_res["balance"],
                                    ocr_res["multiplier"],
                                    ocr_res["pnl_delta"],
                                )
            except Exception as e:
                logger.debug("[Orchestrator] Polling loop exception: %s", e)

            await asyncio.sleep(1.0)

    async def process_clip_trigger(self, context: dict):
        """Full clipping DAG: slice candidate -> transcribe -> boundary optimize -> render 9:16 -> store locally."""
        if not self.channel:
            logger.warning("[DAG] Trigger received but no active channel configured; skipping.")
            return

        active_channel = self.channel
        logger.info("[DAG] Executing local clipping pipeline for event: %s on #%s", context.get("trigger_source"), active_channel)
        timestamp = int(time.time())

        # Step 1: Zero-copy concatenation of candidate slice
        candidate_path = SegmentSlicer.extract_window(active_channel, duration_seconds=60)
        if not candidate_path or not os.path.exists(candidate_path):
            logger.error("[DAG] Failed to extract candidate slice; aborting clip pipeline.")
            return

        try:
            # Step 2: Word-level speech transcription (faster-whisper)
            words = self.transcriber.transcribe_words(candidate_path)

            # Step 3: Local boundary optimization (sentence & pause detection)
            cut_info = self.boundary_ai.find_optimal_cut(words, context, total_duration=60.0)
            cut_start = cut_info.get("cut_start", 0.0)
            cut_end = cut_info.get("cut_end", 45.0)
            duration = round(cut_end - cut_start, 2)
            title = cut_info.get("title", f"Clip from {active_channel}")
            caption = cut_info.get("caption", "#twitch #highlights")
            score = cut_info.get("score", context.get("score", 7))

            logger.info("[DAG] AI Cut Selected: [%.1fs - %.1fs] (duration: %.1fs) | Title: %s", cut_start, cut_end, duration, title)

            # Step 4: Vertical 9:16 hardware rendering
            out_video = f"/tmp/clipper_candidates/clip_{active_channel}_{timestamp}_vertical.mp4"
            out_thumb = f"/tmp/clipper_candidates/thumb_{active_channel}_{timestamp}.jpg"

            badge_text = ""
            mult = context.get("win_multiplier", 1.0)
            if mult >= 100.0:
                badge_text = f"{int(mult)}x MULTIPLIER"
            elif context.get("pnl_delta", 0.0) > 0:
                badge_text = f"+${context.get('pnl_delta'):,.0f} PnL"

            HardwareRenderEngine.render_vertical(
                source_path=candidate_path,
                cut_start=cut_start,
                cut_end=cut_end,
                output_path=out_video,
                words=words,
                pnl_text=badge_text,
                enable_subs=ENABLE_BURN_IN_SUBS,
            )

            # Step 5: Extract poster thumbnail
            HardwareRenderEngine.extract_thumbnail(out_video, out_thumb, offset_seconds=1.5)

            # Step 6: Store bundle locally in ./storage/clips
            video_url, thumb_url = self.storage.store_clip_bundle(out_video, out_thumb)

            # Step 7: Persist to local SQLite database
            clip_record = {
                "channel_name": active_channel,
                "video_url": video_url,
                "thumbnail_url": thumb_url,
                "duration_seconds": duration,
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

            logger.info("[DAG] Successfully stored clip %s locally! Video URL: %s", clip_id, video_url)

            # Step 8: Notify HUD client
            telemetry_server.notify_new_clip({
                "id": clip_id,
                "title": title,
                "score": score,
                "duration": duration,
                "video_url": video_url,
            })

        except Exception as err:
            logger.error("[DAG] Error executing clipping pipeline: %s", err, exc_info=True)
        finally:
            if os.path.exists(candidate_path):
                try:
                    os.remove(candidate_path)
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

        async def get_clips_handler(request):
            limit = int(request.query.get("limit", 20))
            clips = self.db.get_recent_clips(limit=limit)
            return web.json_response(clips)

        async def post_clip_status_handler(request):
            clip_id = request.match_info["id"]
            try:
                data = await request.json()
                status = data.get("status", "approved")
                success = self.db.update_clip_status(clip_id, status)
                return web.json_response({"success": success, "status": status})
            except Exception:
                return web.json_response({"error": "Invalid request"}, status=400)

        app.router.add_get("/", index_handler)
        app.router.add_get("/api/channel", get_channel_handler)
        app.router.add_post("/api/channel", post_channel_handler)
        app.router.add_get("/api/clips", get_clips_handler)
        app.router.add_post("/api/clips/{id}/status", post_clip_status_handler)

        # Static file mounts: /clips serves video storage with byte-range support; / serves static HUD files
        app.router.add_static("/clips", clips_dir)
        app.router.add_static("/", static_dir)

        self.http_runner = web.AppRunner(app)
        await self.http_runner.setup()
        site = web.TCPSite(self.http_runner, "0.0.0.0", HTTP_PORT, reuse_address=True, reuse_port=True)
        await site.start()
        logger.info("[LocalServer] Async web server active at http://localhost:%d (HUD, /clips/, & REST API)", HTTP_PORT)

    async def run(self):
        """Initializes and runs all pipeline services locally."""
        self.running = True
        self.loop = asyncio.get_running_loop()

        logger.info("=" * 70)
        logger.info("  AUTONOMOUS TWITCH STREAM CLIPPER (100%% LOCAL MODE)")
        logger.info("  Channel on startup: [NONE - Awaiting Web UI configuration]")
        logger.info("  Web HUD & Gallery:  http://localhost:%d", HTTP_PORT)
        logger.info("  Storage Path:       %s", os.path.abspath(STORAGE_DIR))
        logger.info("  Database Path:      %s", self.db._sqlite_path)
        logger.info("=" * 70)

        # Start native async HTTP server
        await self.start_local_http_server()

        # Setup shutdown signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self.loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except NotImplementedError:
                pass

        try:
            import websockets
            await websockets.serve(telemetry_server.ws_handler, "0.0.0.0", telemetry_server.PORT)
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
        """Gracefully stops all background processes."""
        if not self.running:
            return
        logger.info("[Orchestrator] Halting local clipper services...")
        self.running = False
        if self.chat_engine:
            self.chat_engine.stop()
        if self.buffer:
            self.buffer.stop()
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
