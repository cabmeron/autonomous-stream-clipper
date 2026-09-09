"""Kick.com Slots & Casino Live Stream Radar Service.

Discovers, monitors, and evaluates live broadcasters currently streaming in Kick's
'Slots & Casino' category (e.g. Roshtein, Trainwreckstv, ClassyBeef, AyeZee).
"""

import asyncio
import json
import logging
import time
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TOP_KICK_SLOT_CHANNELS = [
    "roshtein",
    "classybeef",
    "trainwreckstv",
    "ayezee",
    "deuceace",
    "fossolag",
    "frankdimes",
    "yassuo",
    "xqc",
    "adinross",
    "corinnakopf",
    "westcol",
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class KickSlotRadarService:
    """Discovers live slot streamers on Kick.com and reports viewer counts and metadata."""

    def __init__(self, cache_ttl_seconds: float = 30.0):
        self.cache_ttl = cache_ttl_seconds
        self._cached_streams: List[Dict[str, Any]] = []
        self._last_fetch_time: float = 0.0

    def get_cached_streams(self) -> List[Dict[str, Any]]:
        return self._cached_streams

    async def discover_live_slots(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Queries Kick API for active Slots & Casino streams."""
        now = time.time()
        if not force_refresh and (now - self._last_fetch_time < self.cache_ttl) and self._cached_streams:
            return self._cached_streams

        streams_by_channel: Dict[str, Dict[str, Any]] = {}

        # 1. Fetch from featured livestreams
        try:
            featured = await asyncio.to_thread(self._fetch_featured_streams)
            for s in featured:
                ch = s.get("channel")
                if ch:
                    streams_by_channel[ch] = s
        except Exception as e:
            logger.debug("[KickSlotRadar] Error fetching featured streams: %s", e)

        # 2. Fetch from subcategory livestreams (slots)
        try:
            subcat = await asyncio.to_thread(self._fetch_subcategory_slots)
            for s in subcat:
                ch = s.get("channel")
                if ch and ch not in streams_by_channel:
                    streams_by_channel[ch] = s
        except Exception as e:
            logger.debug("[KickSlotRadar] Error fetching subcategory streams: %s", e)

        # 3. Check top curated channels if not already found
        unseen_top = [c for c in TOP_KICK_SLOT_CHANNELS if c not in streams_by_channel]
        if unseen_top:
            try:
                top_live = await asyncio.to_thread(self._check_channels_status, unseen_top[:6])
                for s in top_live:
                    ch = s.get("channel")
                    if ch:
                        streams_by_channel[ch] = s
            except Exception as e:
                logger.debug("[KickSlotRadar] Error checking curated channels: %s", e)

        # Sort by viewer count descending
        sorted_streams = sorted(
            streams_by_channel.values(),
            key=lambda x: x.get("viewer_count", 0),
            reverse=True,
        )

        self._cached_streams = sorted_streams
        self._last_fetch_time = now
        logger.info("[KickSlotRadar] Discovered %d live Kick slot streams", len(sorted_streams))
        return sorted_streams

    def _fetch_featured_streams(self) -> List[Dict[str, Any]]:
        url = "https://kick.com/stream/featured-livestreams/en"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = []
        for item in data.get("data", []):
            ch_data = item.get("channel", {})
            categories = item.get("categories", [])
            is_slot = False
            cat_name = "Slots & Casino"
            for c in categories:
                c_slug = str(c.get("slug", "")).lower()
                c_name = str(c.get("name", "")).lower()
                if "slot" in c_slug or "gambling" in c_slug or "casino" in c_name:
                    is_slot = True
                    cat_name = c.get("name", "Slots & Casino")
                    break

            if is_slot:
                slug = ch_data.get("slug")
                if slug:
                    title = item.get("session_title") or ch_data.get("status") or "Live Slots"
                    results.append({
                        "channel": slug,
                        "channel_slug": slug,
                        "title": title,
                        "session_title": title,
                        "viewer_count": int(item.get("viewer_count") or 0),
                        "category": cat_name,
                        "profile_pic": ch_data.get("profile_picture") or item.get("thumbnail", {}).get("url", ""),
                        "playback_url": ch_data.get("playback_url") or "",
                        "is_live": True,
                    })
        return results

    def _fetch_subcategory_slots(self) -> List[Dict[str, Any]]:
        url = "https://kick.com/stream/livestreams/en?subcategory=slots"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = []
        for item in data.get("data", []):
            ch_data = item.get("channel", {})
            slug = ch_data.get("slug")
            if slug:
                title = item.get("session_title") or "Live Slots"
                results.append({
                    "channel": slug,
                    "channel_slug": slug,
                    "title": title,
                    "session_title": title,
                    "viewer_count": int(item.get("viewer_count") or 0),
                    "category": "Slots & Casino",
                    "profile_pic": ch_data.get("profile_picture") or item.get("thumbnail", {}).get("url", ""),
                    "playback_url": ch_data.get("playback_url") or "",
                    "is_live": True,
                })
        return results

    def _check_channels_status(self, channel_slugs: List[str]) -> List[Dict[str, Any]]:
        results = []
        for slug in channel_slugs:
            try:
                url = f"https://kick.com/api/v2/channels/{slug}"
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                livestream = data.get("livestream")
                if livestream and isinstance(livestream, dict):
                    title = livestream.get("session_title") or "Live Slots"
                    results.append({
                        "channel": slug,
                        "channel_slug": slug,
                        "title": title,
                        "session_title": title,
                        "viewer_count": int(livestream.get("viewer_count") or 0),
                        "category": "Slots & Casino",
                        "profile_pic": data.get("user", {}).get("profile_pic") or "",
                        "playback_url": data.get("playback_url") or "",
                        "is_live": True,
                    })
            except Exception:
                continue
        return results
