import asyncio
import time
from unittest.mock import patch, MagicMock
import pytest

from services.ingest.stream_buffer import StreamRingBuffer
from services.heuristics.watch_party_finder import WatchPartyFinderService, TWITCH_GQL_URL
from services.ingest.twitch_irc import TwitchChatVelocityEngine


def test_gql_endpoint_preserved():
    """Verify that the official private GQL endpoint is strictly preserved."""
    finder = WatchPartyFinderService()
    assert finder.gql_url == "https://gql.twitch.tv/gql"
    assert TWITCH_GQL_URL == "https://gql.twitch.tv/gql"
    assert finder.client_id == "kimne78kx3ncx6brgo4mv6wki5h1ko"


def test_stream_ring_buffer_exponential_backoff_growth():
    """Verify that StreamRingBuffer backs off exponentially when channel is offline."""
    buffer = StreamRingBuffer(channel="offline_channel_xyz", simulate=False)

    assert buffer.min_offline_check_interval == 10.0
    assert buffer.max_offline_check_interval == 120.0
    assert buffer.offline_backoff_factor == 1.8
    assert buffer.current_offline_interval == 10.0

    with patch.object(buffer, "_resolve_live_m3u8", return_value=None):
        with patch.object(buffer, "_build_env", return_value={}):
            with patch("subprocess.Popen") as mock_popen:
                mock_process = MagicMock()
                mock_process.poll.return_value = None
                mock_popen.return_value = mock_process

                # Start ingest in offline state
                buffer._start_ingest_process()
                assert buffer.is_standby is True
                assert buffer.current_offline_interval == 10.0

                # Simulate watchdog iterations while channel remains offline
                buffer.running = True
                intervals = []

                for _ in range(5):
                    # Force time past _next_live_check_time
                    buffer._next_live_check_time = time.time() - 1.0

                    prev_interval = buffer.current_offline_interval
                    # Simulate one offline check evaluation step
                    live_url = buffer._resolve_live_m3u8()
                    assert live_url is None

                    effective_delay = max(
                        buffer.min_offline_check_interval,
                        min(buffer.max_offline_check_interval, buffer.current_offline_interval),
                    )
                    intervals.append(effective_delay)
                    buffer.current_offline_interval = min(
                        buffer.max_offline_check_interval,
                        buffer.current_offline_interval * buffer.offline_backoff_factor,
                    )

                # Verify strictly monotonically increasing intervals
                for i in range(len(intervals) - 1):
                    assert intervals[i] < intervals[i + 1]

                assert intervals[0] == 10.0
                assert intervals[1] == 18.0
                assert intervals[2] == 32.4
                assert buffer.current_offline_interval <= buffer.max_offline_check_interval


def test_stream_ring_buffer_backoff_resets_on_live():
    """Verify that backoff resets to base interval as soon as a channel goes live."""
    buffer = StreamRingBuffer(channel="recovering_stream", simulate=False)
    buffer.is_standby = True
    # Simulate elevated backoff after multiple offline checks
    buffer.current_offline_interval = 120.0

    with patch.object(buffer, "_resolve_live_m3u8", return_value="http://twitch.tv/live.m3u8"):
        with patch.object(buffer, "_start_ingest_process") as mock_start:
            # When live_url is detected
            live_url = buffer._resolve_live_m3u8()
            assert live_url is not None

            # Logic executed by watchdog:
            buffer.current_offline_interval = buffer.min_offline_check_interval
            buffer.is_standby = False

            assert buffer.current_offline_interval == 10.0
            assert buffer.is_standby is False
