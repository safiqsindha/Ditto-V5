"""
CS:GO/CS2 event extractor.

Converts awpy DemoParser output to normalized GameEvent stream.

awpy output schema (key fields used here):
  - matchID: string
  - rounds: list of round dicts
    - Each round: {
        roundNum, startTick, endTick, endOfficialTick,
        kills: [...], damages: [...], grenades: [...],
        bombEvents: [...], playerFrames (if parsed at tick level)
      }
  - playerStats: aggregated per-player stats

Decision D-C3: We operate at round-level event granularity, not tick-level.
Tick-level would produce ~100k events per map vs ~300 at round level.
Flagged as [REQUIRES SIGN-OFF] in SPEC.md — this default may need to change
depending on chain-length decisions.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

from ...common.schema import EventStream, GameEvent

logger = logging.getLogger(__name__)

# awpy kill event weapon categories → normalized event types
WEAPON_TYPE_MAP = {
    "rifle": "engage_decision",
    "pistol": "engage_decision",
    "sniper": "engage_decision",
    "smg": "engage_decision",
    "heavy": "engage_decision",
    "knife": "risk_accept",
    "grenade": "ability_use",
    "molotov": "ability_use",
    "c4": "objective_contest",
}

# awpy bomb event types → normalized
BOMB_EVENT_MAP = {
    "plant_begin": "objective_contest",
    "plant": "objective_capture",
    "defuse_begin": "objective_contest",
    "defuse": "objective_capture",
    "explode": "objective_capture",
}

# awpy grenade types → normalized
GRENADE_TYPE_MAP = {
    "flashbang": "ability_use",
    "he_grenade": "ability_use",
    "smoke_grenade": "ability_use",
    "molotov": "ability_use",
    "incgrenade": "ability_use",
    "decoy": "ability_use",
}


class CSGOExtractor:

    def extract(self, record: Dict[str, Any]) -> EventStream:
        game_id = self._get_game_id(record)
        map_name = record.get("mapName", record.get("map", "unknown"))
        stream = EventStream(
            game_id=game_id,
            cell="csgo",
            metadata={"map": map_name, "match_id": game_id},
        )

        seq = 0
        for round_data in record.get("rounds") or record.get("gameRounds", []):
            round_num = round_data.get("roundNum", round_data.get("roundNumber", 0))
            start_tick = float(round_data.get("startTick", round_data.get("bombPlantTick", 0)))
            start_ts = start_tick / 128.0  # CS2 tick rate = 128

            # Kill events
            for kill in round_data.get("kills", []):
                ev = self._parse_kill(kill, game_id, round_num, start_ts, seq)
                if ev:
                    stream.append(ev)
                    seq += 1

            # Grenade events
            for gren in round_data.get("grenades", []):
                ev = self._parse_grenade(gren, game_id, round_num, start_ts, seq)
                if ev:
                    stream.append(ev)
                    seq += 1

            # Bomb events
            for bomb_ev in round_data.get("bombEvents", []):
                ev = self._parse_bomb(bomb_ev, game_id, round_num, start_ts, seq)
                if ev:
                    stream.append(ev)
                    seq += 1

            # Buy events (start of round)
            ev = self._parse_buy_phase(round_data, game_id, round_num, start_ts, seq)
            if ev:
                stream.append(ev)
                seq += 1

        stream.events.sort(key=lambda e: e.timestamp)
        for i, e in enumerate(stream.events):
            e.sequence_idx = i

        return stream

    def _parse_kill(
        self, kill: dict, game_id: str, round_num: int, start_ts: float, seq: int
    ) -> Optional[GameEvent]:
        try:
            tick = float(kill.get("tick", 0))
            ts = start_ts + tick / 128.0
            weapon = kill.get("weapon", kill.get("weaponName", "unknown"))
            weapon_class = kill.get("weaponClass", "rifle")
            etype = WEAPON_TYPE_MAP.get(weapon_class.lower(), "engage_decision")

            return GameEvent(
                timestamp=ts,
                event_type=etype,
                actor=str(kill.get("attackerSteamID", kill.get("attacker", "unknown"))),
                location_context={
                    "round": round_num,
                    "weapon": weapon,
                    "victim": str(kill.get("victimSteamID", kill.get("victim", "unknown"))),
                    "headshot": kill.get("isHeadshot", kill.get("headshot", False)),
                    "attacker_side": kill.get("attackerSide", ""),
                    "x": kill.get("attackerX", 0),
                    "y": kill.get("attackerY", 0),
                },
                raw_data_blob=kill,
                cell="csgo",
                game_id=game_id,
                sequence_idx=seq,
                phase=f"round_{round_num}",
            )
        except Exception as e:
            logger.debug(f"Kill parse error: {e}")
            return None

    def _parse_grenade(
        self, gren: dict, game_id: str, round_num: int, start_ts: float, seq: int
    ) -> Optional[GameEvent]:
        try:
            tick = float(gren.get("throwTick", gren.get("tick", 0)))
            ts = start_ts + tick / 128.0
            gren_type = gren.get("grenadeType", gren.get("weaponClass", "flashbang")).lower()
            etype = GRENADE_TYPE_MAP.get(gren_type, "ability_use")

            return GameEvent(
                timestamp=ts,
                event_type=etype,
                actor=str(gren.get("throwerSteamID", gren.get("thrower", "unknown"))),
                location_context={
                    "round": round_num,
                    "grenade_type": gren_type,
                    "x": gren.get("grenadeX", 0),
                    "y": gren.get("grenadeY", 0),
                },
                raw_data_blob=gren,
                cell="csgo",
                game_id=game_id,
                sequence_idx=seq,
                phase=f"round_{round_num}",
            )
        except Exception as e:
            logger.debug(f"Grenade parse error: {e}")
            return None

    def _parse_bomb(
        self, bomb_ev: dict, game_id: str, round_num: int, start_ts: float, seq: int
    ) -> Optional[GameEvent]:
        try:
            tick = float(bomb_ev.get("tick", 0))
            ts = start_ts + tick / 128.0
            bomb_action = bomb_ev.get("bombAction", bomb_ev.get("type", "plant"))
            etype = BOMB_EVENT_MAP.get(bomb_action, "objective_contest")

            return GameEvent(
                timestamp=ts,
                event_type=etype,
                actor=str(bomb_ev.get("playerSteamID", bomb_ev.get("player", "unknown"))),
                location_context={
                    "round": round_num,
                    "bomb_site": bomb_ev.get("bombSite", ""),
                    "bomb_action": bomb_action,
                },
                raw_data_blob=bomb_ev,
                cell="csgo",
                game_id=game_id,
                sequence_idx=seq,
                phase=f"round_{round_num}",
            )
        except Exception as e:
            logger.debug(f"Bomb parse error: {e}")
            return None

    def _parse_buy_phase(
        self, round_data: dict, game_id: str, round_num: int, start_ts: float, seq: int
    ) -> Optional[GameEvent]:
        """Represent the buy phase as a resource_budget event."""
        try:
            ct_eq = round_data.get("ctEqVal", round_data.get("ctEqValue", 0))
            t_eq = round_data.get("tEqVal", round_data.get("tEqValue", 0))
            return GameEvent(
                timestamp=start_ts,
                event_type="resource_budget",
                actor="round_start",
                location_context={
                    "round": round_num,
                    "ct_equipment_value": ct_eq,
                    "t_equipment_value": t_eq,
                    "ct_spend_type": round_data.get("ctBuyType", ""),
                    "t_spend_type": round_data.get("tBuyType", ""),
                },
                raw_data_blob={"ctEqVal": ct_eq, "tEqVal": t_eq, "roundNum": round_num},
                cell="csgo",
                game_id=game_id,
                sequence_idx=seq,
                phase=f"round_{round_num}",
            )
        except Exception as e:
            logger.debug(f"Buy phase parse error: {e}")
            return None

    @staticmethod
    def _get_game_id(record: dict) -> str:
        match_id = record.get("matchID", record.get("matchId", ""))
        if match_id:
            return f"csgo_{match_id}"
        return "csgo_" + hashlib.md5(str(record)[:256].encode()).hexdigest()[:16]
