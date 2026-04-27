"""
Rocket League event extractor.

Per Q7 sign-off (D-22): boost-enriched hit-level extraction.
Hits and boost events are merged into a single chronologically-sorted stream
so the model sees both ball-contact decisions and boost-economy decisions
interleaved as they happen in the match.

Granularity contract:
  - Each ball contact (hit/save/shot/aerial/etc.) → one GameEvent
  - Each boost pickup (big or small) → resource_gain GameEvent
  - Each boost depletion (use crossing zero) → resource_spend GameEvent
  - Each low-boost transition (player drops below LOW_BOOST_THRESHOLD) →
    resource_budget GameEvent (v1.1 amendment)

Expected per-game event count: ~250-400 (vs hit-only's 150-300).

Input formats:
  - carball: game_metadata + hits[] + players[].boost_events
  - rrrocket: properties + network_frames (tick-level; summarized)
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

from ...common.schema import EventStream, GameEvent

logger = logging.getLogger(__name__)

# carball hit type mapping → normalized event types
CARBALL_HIT_TYPE_MAP = {
    "shot": "engage_decision",
    "save": "disengage_decision",
    "goal": "objective_capture",
    "assist": "team_coordinate",
    "epic_save": "disengage_decision",
    "hit": "objective_contest",
    "pass": "team_coordinate",
    "dribble": "position_commit",
    "aerial": "timing_commit",
    "clear": "disengage_decision",
    "demo": "risk_accept",
}

BOOST_EVENT_MAP = {
    "pickup_big": "resource_gain",
    "pickup_small": "resource_gain",
    "use": "resource_spend",
    "depleted": "resource_spend",
    "low_boost": "resource_budget",  # v1.1 amendment: ResourceBudget
}

# Threshold below which a player is considered "low boost" (Q7-C).
# carball boost_amount is 0-100. RL community wisdom: under 25 is "low".
LOW_BOOST_THRESHOLD = 25


class RocketLeagueExtractor:

    def extract(self, record: Dict[str, Any]) -> EventStream:
        game_id = self._get_game_id(record)
        stream = EventStream(game_id=game_id, cell="rocket_league")

        # Try carball format first
        if "_hits" in record:
            self._extract_carball(record, stream)
        elif "network_frames" in record:
            self._extract_rrrocket(record, stream)
        else:
            logger.warning(f"Unknown replay format for {game_id}")

        stream.events.sort(key=lambda e: e.timestamp)
        for i, e in enumerate(stream.events):
            e.sequence_idx = i

        return stream

    def _extract_carball(self, record: dict, stream: EventStream) -> None:
        """Boost-enriched extraction (Q7-C): merge hits and boost events into
        one stream, then derive low-boost (resource_budget) events from boost
        amount transitions per player."""
        seq = 0

        # 1. Hits
        for hit in record.get("_hits", []):
            ev = self._parse_carball_hit(hit, stream.game_id, seq)
            if ev:
                stream.append(ev)
                seq += 1

        # 2. Direct boost events (pickup, use)
        for player in record.get("_players", []):
            for boost_ev in player.get("boost_events", []):
                ev = self._parse_boost_event(boost_ev, player, stream.game_id, seq)
                if ev:
                    stream.append(ev)
                    seq += 1

        # 3. Derived low-boost transitions (resource_budget per v1.1)
        for player in record.get("_players", []):
            boost_history = player.get("boost_history", [])  # [(frame, amount), ...]
            prev_amount = None
            for frame, amount in boost_history:
                if prev_amount is not None:
                    crossed_low = prev_amount >= LOW_BOOST_THRESHOLD and amount < LOW_BOOST_THRESHOLD
                    if crossed_low:
                        stream.append(GameEvent(
                            timestamp=float(frame) / 30.0,
                            event_type="resource_budget",
                            actor=str(player.get("id", {}).get("id", "unknown")),
                            location_context={
                                "boost_amount": amount,
                                "threshold": LOW_BOOST_THRESHOLD,
                                "transition": "high_to_low",
                            },
                            raw_data_blob={"frame": frame, "amount": amount},
                            cell="rocket_league",
                            game_id=stream.game_id,
                            sequence_idx=seq,
                        ))
                        seq += 1
                prev_amount = amount

    def _extract_rrrocket(self, record: dict, stream: EventStream) -> None:
        """Extract events from rrrocket tick-level data (summarized to key events)."""
        props = record.get("properties", {})
        goals = props.get("Goals", {}).get("value", [])
        seq = 0
        for goal in goals:
            frame = goal.get("frame", 0)
            ts = frame / 30.0
            player_name = goal.get("PlayerName", {}).get("value", "unknown")
            stream.append(GameEvent(
                timestamp=ts,
                event_type="objective_capture",
                actor=player_name,
                location_context={"frame": frame, "goal_data": goal},
                raw_data_blob=goal,
                cell="rocket_league",
                game_id=stream.game_id,
                sequence_idx=seq,
            ))
            seq += 1

    def _parse_carball_hit(
        self, hit: dict, game_id: str, seq: int
    ) -> Optional[GameEvent]:
        try:
            ts = float(hit.get("frame_number", hit.get("frame", 0))) / 30.0
            actor_id = str(hit.get("player_id", {}).get("id", "unknown"))
            hit_type = hit.get("hit_type", "hit").lower()
            etype = CARBALL_HIT_TYPE_MAP.get(hit_type, "objective_contest")

            return GameEvent(
                timestamp=ts,
                event_type=etype,
                actor=actor_id,
                location_context={
                    "ball_x": hit.get("ball_data", {}).get("pos_x", 0),
                    "ball_y": hit.get("ball_data", {}).get("pos_y", 0),
                    "ball_z": hit.get("ball_data", {}).get("pos_z", 0),
                    "hit_type": hit_type,
                    "distance_to_goal": hit.get("distance_to_goal", 0),
                },
                raw_data_blob=hit,
                cell="rocket_league",
                game_id=game_id,
                sequence_idx=seq,
                actor_team=str(hit.get("team", "")),
            )
        except Exception as e:
            logger.debug(f"Carball hit parse error: {e}")
            return None

    def _parse_boost_event(
        self, boost_ev: dict, player: dict, game_id: str, seq: int
    ) -> Optional[GameEvent]:
        try:
            boost_type = boost_ev.get("type", "pickup_big")
            etype = BOOST_EVENT_MAP.get(boost_type, "resource_gain")
            ts = float(boost_ev.get("frame", 0)) / 30.0
            return GameEvent(
                timestamp=ts,
                event_type=etype,
                actor=str(player.get("id", {}).get("id", "unknown")),
                location_context={"boost_type": boost_type,
                                   "boost_amount": boost_ev.get("amount", 0)},
                raw_data_blob=boost_ev,
                cell="rocket_league",
                game_id=game_id,
                sequence_idx=seq,
            )
        except Exception as e:
            logger.debug(f"Boost event parse error: {e}")
            return None

    @staticmethod
    def _get_game_id(record: dict) -> str:
        replay_id = (record.get("properties", {}).get("Id", {}).get("value")
                     or record.get("id")
                     or "")
        if replay_id:
            return f"rl_{replay_id}"
        return "rl_" + hashlib.md5(str(record)[:256].encode()).hexdigest()[:16]
