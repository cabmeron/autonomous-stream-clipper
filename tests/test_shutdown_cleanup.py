import asyncio
import os
import signal
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from services.ingest.stream_buffer import StreamRingBuffer, _ACTIVE_BUFFERS, _cleanup_all_buffers
from services.ingest.twitch_irc import TwitchChatVelocityEngine
from services.ingest.kick_chat import KickChatVelocityEngine
from services.storage.db import DatabaseRepository
import telemetry_server
from orchestrator import StreamClipperOrchestrator


class TestShutdownCleanup:

    @pytest.mark.asyncio
    async def test_stream_ring_buffer_process_group_kill(self):
        """Verifies _terminate_current_process properly issues SIGTERM to process group."""
        buf = StreamRingBuffer("test_chan", simulate=True)
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.wait.return_value = 0
        buf.process = mock_proc

        with patch("os.getpgid", return_value=12345), \
             patch("os.getpgrp", return_value=9999), \
             patch("os.killpg") as mock_killpg:
            buf._terminate_current_process()

            mock_killpg.assert_called_once_with(12345, signal.SIGTERM)
            mock_proc.wait.assert_called_once_with(timeout=2.0)
            assert buf.process is None

    @pytest.mark.asyncio
    async def test_stream_ring_buffer_sigkill_escalation(self):
        """Verifies _terminate_current_process escalates to SIGKILL if SIGTERM times out."""
        buf = StreamRingBuffer("test_chan", simulate=True)
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="ffmpeg", timeout=2.0), 0]
        buf.process = mock_proc

        with patch("os.getpgid", return_value=12345), \
             patch("os.getpgrp", return_value=9999), \
             patch("os.killpg") as mock_killpg:
            buf._terminate_current_process()

            # First call is SIGTERM, second call is SIGKILL
            assert mock_killpg.call_count == 2
            mock_killpg.assert_any_call(12345, signal.SIGTERM)
            mock_killpg.assert_any_call(12345, signal.SIGKILL)
            assert buf.process is None

    def test_active_buffers_registration_and_atexit(self):
        """Verifies that started buffers are registered in _ACTIVE_BUFFERS and cleaned up by _cleanup_all_buffers."""
        buf = StreamRingBuffer("test_cleanup", simulate=True)
        with patch.object(buf, "_start_ingest_process"), \
             patch.object(buf, "_terminate_current_process"), \
             patch("threading.Thread"):
            buf.start()
            assert buf in _ACTIVE_BUFFERS

            _cleanup_all_buffers()
            assert buf not in _ACTIVE_BUFFERS
            assert buf.running is False

    @pytest.mark.asyncio
    async def test_telemetry_server_stop(self):
        """Verifies telemetry_server.stop() closes clients, closes ws_server, and resets state."""
        mock_client1 = AsyncMock()
        mock_client2 = AsyncMock()
        telemetry_server.CLIENTS = {mock_client1, mock_client2}
        telemetry_server.running = True

        mock_server = MagicMock()
        mock_server.wait_closed = AsyncMock()
        telemetry_server.ws_server = mock_server

        await telemetry_server.stop()

        assert telemetry_server.running is False
        assert len(telemetry_server.CLIENTS) == 0
        mock_client1.close.assert_awaited_once()
        mock_client2.close.assert_awaited_once()
        mock_server.close.assert_called_once()
        mock_server.wait_closed.assert_awaited_once()
        assert telemetry_server.ws_server is None

    @pytest.mark.asyncio
    async def test_chat_engines_safe_stop(self):
        """Verifies twitch and kick chat engine stop() methods don't throw when sockets are closed or absent."""
        twitch = TwitchChatVelocityEngine("test_twitch")
        twitch.stop()
        assert twitch.running is False

        kick = KickChatVelocityEngine("test_kick")
        kick.stop()
        assert kick.running is False

        # With mock active socket
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.close = AsyncMock()
        twitch.ws = mock_ws
        twitch.stop()
        # Give event loop a cycle to execute close task
        await asyncio.sleep(0.01)
        mock_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_database_close_checkpoint(self, tmp_path):
        """Verifies DatabaseRepository.close() issues PRAGMA wal_checkpoint(TRUNCATE)."""
        db_path = str(tmp_path / "test.db")
        with patch.object(DatabaseRepository, "__init__", lambda self: None):
            db = DatabaseRepository()
            db._sqlite_path = db_path
            db._get_connection = MagicMock()
            mock_conn = MagicMock()
            db._get_connection.return_value.__enter__.return_value = mock_conn

            db.close()
            mock_conn.execute.assert_called_once_with("PRAGMA wal_checkpoint(TRUNCATE);")

    @pytest.mark.asyncio
    async def test_orchestrator_graceful_shutdown(self):
        """Verifies StreamClipperOrchestrator.shutdown cleanly halts all sessions, tasks, and servers."""
        with patch("services.storage.db.DatabaseRepository._init_sqlite"):
            orchestrator = StreamClipperOrchestrator()
            orchestrator.running = True

            mock_session = MagicMock()
            orchestrator.sessions["chan1"] = mock_session

            # Create a tracked long-running task
            dummy_task = orchestrator._track_task(asyncio.sleep(60))
            assert dummy_task in orchestrator._background_tasks

            mock_runner = AsyncMock()
            orchestrator.http_runner = mock_runner

            with patch("telemetry_server.stop", new_callable=AsyncMock) as mock_telem_stop, \
                 patch.object(orchestrator.db, "close") as mock_db_close:
                await orchestrator.shutdown()

                assert orchestrator.running is False
                assert orchestrator._shutting_down is True
                assert len(orchestrator.sessions) == 0
                mock_session.stop.assert_called_once()
                assert dummy_task.cancelled()
                assert len(orchestrator._background_tasks) == 0
                mock_telem_stop.assert_awaited_once()
                mock_runner.cleanup.assert_awaited_once()
                assert orchestrator.http_runner is None
                mock_db_close.assert_called_once()
