"""
Fortnite event extractor.

Converts FortniteReplayDecompressor JSON output to normalized GameEvent stream.

The decompressor JSON schema (SL-x-TnT format) contains:
  - header: match metadata
  - playerEliminations: list of elimination events with timestamp, eliminator, eliminated
  - playerMovements: (optional) position snapshots
  - gameEvents: general match events
  - stormEvents: storm phase transitions
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

from ...common.schema import EventStream, GameEvent

logger = logging.getLogger(__name__)


class FortniteExtractor:
    """
    Extracts normalized GameEvents from a decompressed Fortnite replay JSON.
    """

    def extract(self, record: Dict[str, Any]) -> EventStream:
        """Convert a replay JSON record to a normalized EventStream."""
        header = record.get("header", {})
        game_id = self._make_game_id(record, header)
        stream = EventStream(
            game_id=game_id,
            cell="fortnite",
            metadata={
                "event_type": header.get("eventType", "unknown"),
                "region": header.get("region", "unknown"),
                "season": header.get("season", "unknown"),
                "timestamp_utc": header.get("timestamp", ""),
            },
        )

        seq = 0
        # Extract storm events (zone transitions = high-decision-weight events)
        for ev in record.get("stormEvents", []):
            game_event = self._parse_storm_event(ev, game_id, seq)
            if game_event:
                stream.append(game_event)
                seq += 1

        # Extract player eliminations (engagement outcomes)
        for ev in record.get("playerEliminations", []):
            game_event = self._parse_elimination(ev, game_id, seq)
            if game_event:
                stream.append(game_event)
                seq += 1

        # Extract general game events
        for ev in record.get("gameEvents", []):
            game_event = self._parse_game_event(ev, game_id, seq)
            if game_event:
                stream.append(game_event)
                seq += 1

        # Sort by timestamp and re-index
        stream.events.sort(key=lambda e: e.timestamp)
        for i, e in enumerate(stream.events):
            e.sequence_idx = i

        return stream

    def _parse_storm_event(self, ev: dict, game_id: str, seq: int) -> Optional[GameEvent]:
        try:
            return GameEvent(
                timestamp=float(ev.get("elapsedTime", ev.get("timestamp", 0))),
                event_type="zone_enter",  # storm circle = zone constraint
                actor="storm",
                location_context={
                    "storm_phase": ev.get("phase", 0),
                    "circle_x": ev.get("circleCenterX", 0),
                    "circle_y": ev.get("circleCenterY", 0),
                    "circle_radius": ev.get("circleRadius", 0),
                },
                raw_data_blob=ev,
                cell="fortnite",
                game_id=game_id,
                sequence_idx=seq,
                phase=f"storm_phase_{ev.get('phase', 0)}",
            )
        except Exception as e:
            logger.debug(f"Storm event parse error: {e}")
            return None

    def _parse_elimination(self, ev: dict, game_id: str, seq: int) -> Optional[GameEvent]:
        try:
            return GameEvent(
                timestamp=float(ev.get("time", ev.get("timestamp", 0))),
                event_type="engage_decision",
                actor=ev.get("eliminator", {}).get("id", "unknown"),
                location_context={
                    "victim": ev.get("eliminated", {}).get("id", "unknown"),
                    "weapon": ev.get("gunType", "unknown"),
                    "knocked": ev.get("knocked", False),
                },
                raw_data_blob=ev,
                cell="fortnite",
                game_id=game_id,
                sequence_idx=seq,
                actor_team=ev.get("eliminator", {}).get("team", None),
            )
        except Exception as e:
            logger.debug(f"Elimination parse error: {e}")
            return None

    def _parse_game_event(self, ev: dict, game_id: str, seq: int) -> Optional[GameEvent]:
        raw_type = ev.get("type", ev.get("eventType", "unknown"))
        normalized_type = self._normalize_event_type(raw_type)
        if normalized_type is None:
            return None
        try:
            return GameEvent(
                timestamp=float(ev.get("time", ev.get("timestamp", 0))),
                event_type=normalized_type,
                actor=ev.get("playerId", ev.get("actorId", "unknown")),
                location_context={
                    "x": ev.get("posX", 0),
                    "y": ev.get("posY", 0),
                    "z": ev.get("posZ", 0),
                },
                raw_data_blob=ev,
                cell="fortnite",
                game_id=game_id,
                sequence_idx=seq,
            )
        except Exception as e:
            logger.debug(f"Game event parse error ({raw_type}): {e}")
            return None

    @staticmethod
    def _normalize_event_type(raw_type: str) -> Optional[str]:
        """Map raw Fortnite event types to normalized actionable types."""
        mapping = {
            "BuildWall": "resource_spend",
            "BuildFloor": "resource_spend",
            "BuildStair": "resource_spend",
            "BuildRoof": "resource_spend",
            "HarvestItem": "resource_gain",
            "OpenChest": "resource_gain",
            "ConsumeItem": "item_use",
            "WeaponSwitch": "target_select",
            "PlayerJump": None,         # Not actionable
            "PlayerLand": None,
            "MapMarker": "team_coordinate",
            "PingLocation": "team_coordinate",
            "StormSurge": "risk_accept",
            "PhaseChange": "rotation_commit",
            "AbilityActivated": "ability_use",
            "Heal": "item_use",
            "Revive": "team_coordinate",
            "VehicleEnter": "rotation_commit",
            "LootDrop": "resource_gain",
        }
        return mapping.get(raw_type, None)

    @staticmethod
    def _make_game_id(record: dict, header: dict) -> str:
        candidate = header.get("replayId") or header.get("matchId") or ""
        if candidate:
            return f"fnc_{candidate}"
        content = str(record)[:256]
        return "fnc_" + hashlib.md5(content.encode()).hexdigest()[:16]
