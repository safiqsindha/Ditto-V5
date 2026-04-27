"""
Rocket League event extractor.

Converts carball / rrrocket output to normalized GameEvent stream.

carball output has:
  - game_metadata (duration, map, teams, goals)
  - hits (per-hit objects with actor, position, ball data)
  - players (list of player objects)

rrrocket JSON output has:
  - properties (game metadata)
  - network_frames (tick-by-tick actor data)

Decision D-RL2: We use carball's hit-level abstraction rather than raw ticks.
This gives ~150-300 events per 5-min game at a meaningful decision granularity.
Flagged [REQUIRES SIGN-OFF] if continuous-state handling is needed at tick level.
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
    "low_boost": "resource_budget",  # v1.1 amendment: ResourceBudget
}


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
        goals = record.get("_goals", [])
        goal_times = {float(g.get("frame_number", g.get("frame", 0))) / 30.0
                      for g in goals}

        seq = 0
        for hit in record.get("_hits", []):
            ev = self._parse_carball_hit(hit, stream.game_id, seq)
            if ev:
                stream.append(ev)
                seq += 1

        # Boost events from player data
        for player in record.get("_players", []):
            for boost_ev in player.get("boost_events", []):
                ev = self._parse_boost_event(boost_ev, player, stream.game_id, seq)
                if ev:
                    stream.append(ev)
                    seq += 1

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
