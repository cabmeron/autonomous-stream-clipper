import aiohttp
import asyncio
import logging
import os
import re
import time
import uuid
from typing import Dict, List, Optional
from dotenv import load_dotenv

from services.ingest.stream_buffer import clean_channel_name

logger = logging.getLogger(__name__)

TWITCH_GQL_URL = "https://gql.twitch.tv/gql"
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"

REACTION_KEYWORDS = [
    "reacting", "react", "reaction", "reactions",
    "watching", "watchparty", "watch party", "watch-party",
    "costream", "co-stream", "viewing", "spectating",
    "rewatch", "vod review", "vods", "clips"
]


class WatchPartyFinderService:
    """Discovers and evaluates live broadcasters streaming themselves watching a target channel."""

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        gemini_model: str = "gemini-3.6-flash",
        client_id: str = TWITCH_CLIENT_ID,
        gql_url: str = TWITCH_GQL_URL,
        timeout_seconds: float = 8.0,
    ):
        self.explicit_key = gemini_api_key is not None
        self.gemini_api_key = (
            gemini_api_key if self.explicit_key else (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "")
        )
        self.gemini_model = gemini_model
        self.client_id = client_id
        self.gql_url = gql_url
        self.timeout_seconds = timeout_seconds

        # Cache of latest discovery results per channel: channel -> dict
        self._cached_results: Dict[str, dict] = {}

    def get_cached_results(self, channel: str) -> Optional[dict]:
        clean = clean_channel_name(channel)
        return self._cached_results.get(clean)

    async def search_twitch_watchers(self, target_channel: str, limit: int = 15) -> List[dict]:
        """Queries Twitch GQL for live channels matching target channel name and watch party terms."""
        clean_target = clean_channel_name(target_channel)
        if not clean_target:
            return []

        search_queries = [
            f"watching {clean_target}",
            f"{clean_target} react",
            f"{clean_target} watch party",
            clean_target,
        ]

        found_map: Dict[str, dict] = {}
        headers = {
            "Client-ID": self.client_id,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            for query_term in search_queries:
                payload = {
                    "query": """
                    query SearchWatchers($query: String!) {
                      searchFor(userQuery: $query, platform: "web") {
                        channels {
                          items {
                            id
                            displayName
                            login
                            profileImageURL(width: 70)
                            stream {
                              id
                              title
                              viewersCount
                              game {
                                name
                              }
                              previewImageURL(width: 320, height: 180)
                            }
                          }
                        }
                      }
                    }
                    """,
                    "variables": {"query": query_term},
                }

                max_retries = 2
                retry_delay = 2.0
                data = None

                for attempt in range(max_retries + 1):
                    try:
                        async with session.post(
                            self.gql_url,
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
                        ) as resp:
                            if resp.status == 429:
                                if attempt < max_retries:
                                    retry_header = resp.headers.get("Retry-After")
                                    wait_time = float(retry_header) if retry_header and retry_header.isdigit() else retry_delay
                                    logger.warning(
                                        "[WatchPartyFinder] Twitch GQL rate limited (HTTP 429). Backing off for %.1fs (attempt %d/%d)...",
                                        wait_time, attempt + 1, max_retries,
                                    )
                                    await asyncio.sleep(wait_time)
                                    retry_delay *= 2.0
                                    continue
                                else:
                                    logger.warning("[WatchPartyFinder] Twitch GQL 429 rate limit exceeded. Aborting query to protect IP.")
                                    break
                            elif resp.status != 200:
                                logger.debug("[WatchPartyFinder] Twitch GQL returned HTTP %d for query '%s'", resp.status, query_term)
                                break

                            data = await resp.json()
                            break
                    except Exception as e:
                        logger.debug("[WatchPartyFinder] Query '%s' attempt %d failed: %s", query_term, attempt + 1, e)
                        if attempt < max_retries:
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 1.5
                        else:
                            break

                if not data or not isinstance(data, dict):
                    continue

                items = (
                    data.get("data", {})
                    .get("searchFor", {})
                    .get("channels", {})
                    .get("items", [])
                )

                for item in items:
                    login = clean_channel_name(item.get("login", ""))
                    # Discard self, empty login, or streams that are offline
                    stream = item.get("stream")
                    if not login or login == clean_target or not stream:
                        continue

                    if login not in found_map:
                        preview_url = stream.get("previewImageURL") or ""
                        if preview_url:
                            preview_url = preview_url.replace("{width}", "320").replace("{height}", "180")

                        found_map[login] = {
                            "id": item.get("id") or str(uuid.uuid4()),
                            "login": login,
                            "display_name": item.get("displayName") or login,
                            "profile_image_url": item.get("profileImageURL") or "",
                            "preview_image_url": preview_url,
                            "title": stream.get("title") or "",
                            "viewers": int(stream.get("viewersCount") or 0),
                            "game": (stream.get("game") or {}).get("name") or "Live Stream",
                        }

        raw_candidates = list(found_map.values())
        raw_candidates.sort(key=lambda c: c.get("viewers", 0), reverse=True)
        return raw_candidates[:limit]

    def evaluate_candidates(self, target_channel: str, candidates: List[dict]) -> List[dict]:
        """Evaluates each candidate stream and assigns agent determinations (HOOK_IN, POTENTIAL, DISMISS)."""
        clean_target = clean_channel_name(target_channel)
        evaluated = []

        for cand in candidates:
            title = cand.get("title", "")
            title_lower = title.lower()
            viewers = cand.get("viewers", 0)
            game = cand.get("game", "")
            game_lower = game.lower()

            # 1. Term Matching
            target_in_title = bool(clean_target in title_lower)
            matched_keywords = [kw for kw in REACTION_KEYWORDS if kw in title_lower]

            # 2. Base Confidence & Classification
            confidence = 0.10
            match_type = "UNRELATED"

            if target_in_title and any(k in ("watching", "watchparty", "watch party", "watch-party", "costream", "co-stream") for k in matched_keywords):
                confidence = 0.95
                match_type = "WATCH_PARTY"
            elif target_in_title and any(k in ("reacting", "react", "reaction", "reactions") for k in matched_keywords):
                confidence = 0.90
                match_type = "DIRECT_REACTION"
            elif target_in_title and any(k in ("vods", "vod review", "clips", "rewatch") for k in matched_keywords):
                confidence = 0.82
                match_type = "VOD_REVIEW"
            elif target_in_title:
                confidence = 0.65
                match_type = "CASUAL_MENTION"
            elif matched_keywords and game_lower in ("just chatting", "special events", "watch parties"):
                confidence = 0.45
                match_type = "POTENTIAL_GENERIC"
            else:
                confidence = 0.15
                match_type = "UNRELATED"

            # 3. Viewer count weighting
            if viewers >= 1000:
                confidence = min(0.99, confidence + 0.05)
            elif viewers >= 100:
                confidence = min(0.98, confidence + 0.02)
            elif viewers < 5:
                confidence = max(0.05, confidence - 0.10)

            # 4. Decision thresholding
            if confidence >= 0.75:
                decision = "HOOK_IN"
            elif confidence >= 0.50:
                decision = "POTENTIAL"
            else:
                decision = "DISMISS"

            # 5. Natural Agent Rationale
            reasoning = self._craft_reasoning(clean_target, cand, decision, match_type, matched_keywords)

            evaluated.append({
                **cand,
                "decision": decision,
                "confidence": round(confidence, 2),
                "match_type": match_type,
                "matched_keywords": matched_keywords,
                "target_in_title": target_in_title,
                "reasoning": reasoning,
            })

        # Sort: HOOK_IN first, then POTENTIAL, then DISMISS (sub-sorted by viewers)
        decision_priority = {"HOOK_IN": 0, "POTENTIAL": 1, "DISMISS": 2}
        evaluated.sort(key=lambda x: (decision_priority.get(x["decision"], 3), -x.get("viewers", 0)))
        return evaluated

    def _craft_reasoning(
        self,
        target_channel: str,
        cand: dict,
        decision: str,
        match_type: str,
        matched_keywords: List[str],
    ) -> str:
        login = cand.get("display_name") or cand.get("login")
        viewers = cand.get("viewers", 0)
        game = cand.get("game", "")

        if decision == "HOOK_IN":
            kw_str = ", ".join(f"'{k}'" for k in matched_keywords[:3]) if matched_keywords else "watch-party tags"
            if match_type == "WATCH_PARTY":
                return f"Agent Analysis: Broadcast title directly confirms live watch party / co-stream of #{target_channel} with {viewers:,} viewers in {game}. High-priority multi-angle hook."
            elif match_type == "DIRECT_REACTION":
                return f"Agent Analysis: Broadcaster is actively reacting to #{target_channel} ({kw_str}) with {viewers:,} viewers. Optimal reaction candidate."
            else:
                return f"Agent Analysis: Title contains strong alignment with #{target_channel} ({kw_str}) and strong viewer presence ({viewers:,} viewers). Recommended to hook in."

        elif decision == "POTENTIAL":
            if cand.get("target_in_title"):
                return f"Agent Analysis: Stream mentions #{target_channel} with {viewers:,} viewers, but lacks explicit reaction keywords. Potential co-player, host, or discussion."
            else:
                return f"Agent Analysis: Broadcaster is in {game} ({viewers:,} viewers) with general reaction tags, but doesn't name #{target_channel} explicitly. Monitoring recommended."

        else:
            if viewers < 10:
                return f"Agent Analysis: Negligible viewer presence ({viewers} viewers) or weak keyword match. Hook-in dismissed to preserve local resources."
            return f"Agent Analysis: Stream appears unrelated to #{target_channel} (playing {game} with {viewers:,} viewers). Dismissed."

    def generate_simulation_candidates(self, target_channel: str) -> List[dict]:
        """Generates realistic simulation candidates for instant testing and UI demonstration."""
        clean_target = clean_channel_name(target_channel) or "marlon"
        cands = [
            {
                "id": "sim_reactor_1",
                "login": f"tarik_{clean_target}_reacts",
                "display_name": f"TarikReacts",
                "profile_image_url": "https://static-cdn.jtvnw.net/jtv_user_pictures/f04d2a14-8d63-4cd5-a469-7ec2cd6e5ce3-profile_image-70x70.png",
                "preview_image_url": "https://static-cdn.jtvnw.net/previews-ttv/live_user_tarik-320x180.jpg",
                "title": f"🔴 REACTING TO {clean_target.upper()} CLUTCHES & HIGHLIGHTS | LIVE WATCH PARTY",
                "game": "Just Chatting",
                "viewers": 3420,
                "is_simulation": True,
            },
            {
                "id": "sim_reactor_2",
                "login": f"esports_watch_{clean_target}",
                "display_name": f"EsportsWatchdesk",
                "profile_image_url": "https://static-cdn.jtvnw.net/jtv_user_pictures/6a055236-16b3-4a72-b2b2-1c1bf17ea0d2-profile_image-70x70.png",
                "preview_image_url": "https://static-cdn.jtvnw.net/previews-ttv/live_user_pybertatsquad-320x180.jpg",
                "title": f"Co-Stream & VOD Review: Breaking down {clean_target}'s gameplay and insane rounds",
                "game": "Special Events",
                "viewers": 1150,
                "is_simulation": True,
            },
            {
                "id": "sim_reactor_3",
                "login": "chill_vibes_tv",
                "display_name": "ChillVibesTV",
                "profile_image_url": "https://static-cdn.jtvnw.net/jtv_user_pictures/0a42b016-9c92-4a96-b6d4-bc157ce6652d-profile_image-70x70.jpg",
                "preview_image_url": "https://static-cdn.jtvnw.net/previews-ttv/live_user_latari-320x180.jpg",
                "title": f"Late Night Just Chatting | Mentioning {clean_target} drama later | !discord",
                "game": "Just Chatting",
                "viewers": 185,
                "is_simulation": True,
            },
            {
                "id": "sim_reactor_4",
                "login": "random_grinder_99",
                "display_name": "Grinder99",
                "profile_image_url": "https://static-cdn.jtvnw.net/jtv_user_pictures/49db48ef-331a-404c-a5cf-5a97661790d5-profile_image-70x70.png",
                "preview_image_url": "https://static-cdn.jtvnw.net/previews-ttv/live_user_tajikjr-320x180.jpg",
                "title": "Ranked grind to Radiant | Solo Q only | No distractions",
                "game": "VALORANT",
                "viewers": 8,
                "is_simulation": True,
            },
        ]
        return self.evaluate_candidates(clean_target, cands)

    async def discover_and_evaluate(
        self,
        target_channel: str,
        include_simulation_if_empty: bool = True,
        force_simulation: bool = False,
    ) -> dict:
        """Runs the complete discovery pipeline: searches live Twitch, evaluates, and caches results."""
        clean_target = clean_channel_name(target_channel)
        start_time = time.time()

        if force_simulation:
            candidates = self.generate_simulation_candidates(clean_target)
            scanned_count = len(candidates)
        else:
            raw_candidates = await self.search_twitch_watchers(clean_target)
            scanned_count = len(raw_candidates)

            if raw_candidates:
                candidates = self.evaluate_candidates(clean_target, raw_candidates)
            elif include_simulation_if_empty:
                logger.info("[WatchPartyFinder] 0 live results found on Twitch for '%s'; providing simulated preview candidates", clean_target)
                candidates = self.generate_simulation_candidates(clean_target)
            else:
                candidates = []

        hook_count = sum(1 for c in candidates if c.get("decision") == "HOOK_IN")
        potential_count = sum(1 for c in candidates if c.get("decision") == "POTENTIAL")
        dismiss_count = sum(1 for c in candidates if c.get("decision") == "DISMISS")

        result = {
            "target_channel": clean_target,
            "searched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_seconds": round(time.time() - start_time, 2),
            "total_scanned": scanned_count,
            "candidates_count": len(candidates),
            "hook_recommendations": hook_count,
            "potential_count": potential_count,
            "dismiss_count": dismiss_count,
            "candidates": candidates,
        }

        self._cached_results[clean_target] = result
        logger.info(
            "[WatchPartyFinder] Discovery for #%s completed: %d scanned, %d recommended to hook in (%.2fs)",
            clean_target,
            scanned_count,
            hook_count,
            result["elapsed_seconds"],
        )
        return result
