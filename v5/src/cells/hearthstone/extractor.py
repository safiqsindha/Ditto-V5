"""
Hearthstone event extractor.

Converts hearthstone.hslog entity tree output to normalized GameEvent stream.

hslog entity tree structure:
  - game_tree.game: root Game entity
  - game_tree.game.players: [Player, Player]
  - game_tree.game.turns: list of Turn objects
    - Each turn has entities and packets (actions)

Decision D-HS1: Using per-action (per-card-play/attack/hero-power) granularity,
not per-turn. A single turn may contain 3-8 decisions.
Flagged [REQUIRES SIGN-OFF] in SPEC.md — per-turn vs per-action to be confirmed.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

from ...common.schema import EventStream, GameEvent

logger = logging.getLogger(__name__)

# HS packet tag types → normalized event types
# Based on hearthstone.enums.PacketType
HS_PACKET_TYPE_MAP = {
    "play_card": "draft_pick",
    "PLAY": "draft_pick",
    "attack": "engage_decision",
    "ATTACK": "engage_decision",
    "hero_power": "ability_use",
    "POWER": "ability_use",
    "choose_option": "target_select",
    "trigger": "team_coordinate",     # combo / battlecry trigger
    "death": "objective_contest",
    "concede": "concede",
    "mana_crystal": "resource_gain",
    "draw_card": "resource_gain",
    "discard": "resource_spend",
}

# HS zone IDs
ZONE_MAP = {0: "INVALID", 1: "PLAY", 2: "DECK", 3: "HAND", 4: "GRAVEYARD",
            5: "REMOVEDFROMGAME", 6: "SETASIDE", 7: "SECRET"}


class HearthstoneExtractor:

    def extract(self, record: Dict[str, Any]) -> EventStream:
        game_id = f"hs_{record.get('game_id', hashlib.md5(str(record)[:64].encode()).hexdigest()[:12])}"
        stream = EventStream(game_id=game_id, cell="hearthstone")

        game_tree = record.get("game_tree")
        if game_tree is None:
            logger.warning(f"No game_tree in HS record for {game_id}")
            return stream

        try:
            self._walk_game_tree(game_tree, stream)
        except Exception as e:
            logger.warning(f"HS tree walk error for {game_id}: {e}")

        return stream

    def _walk_game_tree(self, game_tree: Any, stream: EventStream) -> None:
        """Walk the entity tree and emit GameEvents for player decisions."""
        seq = 0
        turn_num = 0

        game = getattr(game_tree, "game", game_tree)
        packets = getattr(game, "packets", []) or getattr(game, "turns", [])

        for packet in packets:
            packet_type = self._get_packet_type(packet)

            if packet_type == "turn_change":
                turn_num += 1
                continue

            etype = HS_PACKET_TYPE_MAP.get(packet_type)
            if etype is None:
                continue

            ts = self._get_timestamp(packet, turn_num)
            actor = self._get_actor(packet)
            location = self._get_location(packet, turn_num)

            stream.append(GameEvent(
                timestamp=ts,
                event_type=etype,
                actor=actor,
                location_context=location,
                raw_data_blob=self._serialize_packet(packet),
                cell="hearthstone",
                game_id=stream.game_id,
                sequence_idx=seq,
                phase=f"turn_{turn_num}",
            ))
            seq += 1

            # Recurse into sub-packets (battlecry / targeting)
            for sub in getattr(packet, "packets", []) or []:
                sub_type = self._get_packet_type(sub)
                sub_etype = HS_PACKET_TYPE_MAP.get(sub_type)
                if sub_etype:
                    stream.append(GameEvent(
                        timestamp=ts + 0.001,
                        event_type=sub_etype,
                        actor=self._get_actor(sub),
                        location_context=self._get_location(sub, turn_num),
                        raw_data_blob=self._serialize_packet(sub),
                        cell="hearthstone",
                        game_id=stream.game_id,
                        sequence_idx=seq,
                        phase=f"turn_{turn_num}",
                    ))
                    seq += 1

        for i, e in enumerate(stream.events):
            e.sequence_idx = i

    @staticmethod
    def _get_packet_type(packet: Any) -> str:
        return (getattr(packet, "type", None)
                or getattr(packet, "packet_type", None)
                or getattr(packet, "_type", "unknown")
                or "unknown")

    @staticmethod
    def _get_timestamp(packet: Any, turn_num: int) -> float:
        ts = getattr(packet, "timestamp", None) or getattr(packet, "time", None)
        if ts is not None:
            try:
                return float(ts)
            except (TypeError, ValueError):
                pass
        return float(turn_num * 30)

    @staticmethod
    def _get_actor(packet: Any) -> str:
        entity = getattr(packet, "entity", None)
        if entity is not None:
            controller = getattr(entity, "controller", None)
            if controller:
                return str(getattr(controller, "account_lo", controller))
        player = getattr(packet, "player", getattr(packet, "source", None))
        if player:
            return str(getattr(player, "account_lo", player))
        return "unknown"

    @staticmethod
    def _get_location(packet: Any, turn_num: int) -> dict:
        return {
            "turn": turn_num,
            "target": str(getattr(packet, "target", "")),
            "zone": ZONE_MAP.get(getattr(packet, "zone", 0), "unknown"),
        }

    @staticmethod
    def _serialize_packet(packet: Any) -> dict:
        """Minimal safe serialization of hslog packet for raw_data_blob."""
        try:
            return {
                "type": str(getattr(packet, "type", "")),
                "entity_id": str(getattr(getattr(packet, "entity", None), "id", "")),
                "ts": str(getattr(packet, "timestamp", "")),
            }
        except Exception:
            return {"error": "serialization_failed"}
