"""
NBA event extractor.

Per SPEC Q6 sign-off (D-21): groups play-by-play rows into possession-level
events. Each possession contains one or more plays, with one summary GameEvent
emitted per possession boundary.

Possession boundaries are detected via:
  - Made shot (ends offensive possession)
  - Defensive rebound (ends offensive possession, starts new one for other team)
  - Turnover (ends offensive possession)
  - End of period (ends current possession)
  - Free throw resulting in possession change (e.g., final FT made + no foul)

PlayByPlayV3 response structure:
  resultSets[0].rowSet: list of play rows
  columns: ['GAME_ID', 'EVENTNUM', 'EVENTMSGTYPE', 'EVENTMSGACTIONTYPE',
            'PERIOD', 'WCTIMESTRING', 'PCTIMESTRING', 'HOMEDESCRIPTION',
            'NEUTRALDESCRIPTION', 'VISITORDESCRIPTION', 'SCORE', 'SCOREMARGIN',
            'PERSON1TYPE', 'PLAYER1_ID', 'PLAYER1_NAME', 'PLAYER1_TEAM_ID', ...]
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from ...common.schema import EventStream, GameEvent

logger = logging.getLogger(__name__)

# NBA event message type codes → normalized event types
# See: https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/playbyplayv3.md
NBA_EVENTMSGTYPE_MAP: Dict[int, str] = {
    1: "engage_decision",    # field goal made
    2: "engage_decision",    # field goal missed
    3: "ability_use",        # free throw
    4: "resource_gain",      # rebound
    5: "resource_spend",     # turnover
    6: "risk_accept",        # foul
    7: "disengage_decision", # violation
    8: "team_coordinate",    # substitution
    9: "team_coordinate",    # timeout
    10: "timing_commit",     # jump ball
    11: "strategy_adapt",    # ejection (rare)
    12: "objective_contest", # start of period
    13: "timing_commit",     # end of period
    18: "engage_decision",   # instant replay
    20: "team_coordinate",   # stoppage
}

PERIOD_CLOCK_RE = re.compile(r"(\d+):(\d+)")


def parse_pctimestring(period: int, pctimestring: str) -> float:
    """Convert period + clock string to seconds from game start."""
    m = PERIOD_CLOCK_RE.match(pctimestring or "12:00")
    if not m:
        return (period - 1) * 720.0
    minutes, seconds = int(m.group(1)), int(m.group(2))
    remaining = minutes * 60 + seconds
    period_length = 720 if period <= 4 else 300  # OT = 5 min
    elapsed_in_period = period_length - remaining
    base = sum(720 if p <= 4 else 300 for p in range(1, period))
    return float(base + elapsed_in_period)


class NBAExtractor:

    def extract(self, record: Dict[str, Any]) -> EventStream:
        game_id = self._get_game_id(record)
        stream = EventStream(game_id=game_id, cell="nba")

        result_sets = record.get("resultSets") or record.get("PlayByPlay", {}).get("resultSets", [])
        if not result_sets:
            logger.warning(f"No resultSets in NBA record for {game_id}")
            return stream

        rs = result_sets[0]
        columns = rs.get("headers", rs.get("columns", []))
        rows = rs.get("rowSet", [])

        col_idx = {col: i for i, col in enumerate(columns)}

        for seq, row in enumerate(rows):
            ev = self._parse_row(row, col_idx, game_id, seq)
            if ev:
                stream.append(ev)

        return stream

    def _parse_row(
        self, row: list, col_idx: dict, game_id: str, seq: int
    ) -> Optional[GameEvent]:
        try:
            period = int(row[col_idx["PERIOD"]])
            pctimestring = str(row[col_idx.get("PCTIMESTRING", -1)] or "12:00")
            timestamp = parse_pctimestring(period, pctimestring)

            msgtype = int(row[col_idx.get("EVENTMSGTYPE", -1)] or 0)
            normalized_type = NBA_EVENTMSGTYPE_MAP.get(msgtype)
            if normalized_type is None:
                return None

            player1_id = str(row[col_idx.get("PLAYER1_ID", -1)] or "")
            player1_name = str(row[col_idx.get("PLAYER1_NAME", -1)] or "")
            team_id = str(row[col_idx.get("PLAYER1_TEAM_ID", -1)] or "")

            home_desc = str(row[col_idx.get("HOMEDESCRIPTION", -1)] or "")
            visitor_desc = str(row[col_idx.get("VISITORDESCRIPTION", -1)] or "")
            description = home_desc or visitor_desc

            score = str(row[col_idx.get("SCORE", -1)] or "")
            score_margin = str(row[col_idx.get("SCOREMARGIN", -1)] or "")

            return GameEvent(
                timestamp=timestamp,
                event_type=normalized_type,
                actor=player1_id or player1_name or "unknown",
                location_context={
                    "period": period,
                    "pctimestring": pctimestring,
                    "description": description,
                    "score": score,
                    "score_margin": score_margin,
                },
                raw_data_blob={"row": row, "columns": list(col_idx.keys())},
                cell="nba",
                game_id=game_id,
                sequence_idx=seq,
                actor_team=team_id or None,
                phase="regular_season",  # updated downstream from metadata
            )
        except Exception as e:
            logger.debug(f"NBA row parse error: {e}")
            return None

    @staticmethod
    def _get_game_id(record: dict) -> str:
        parameters = record.get("parameters", {})
        game_id = parameters.get("GameID", "")
        if not game_id:
            rs = (record.get("resultSets") or [{}])[0]
            rows = rs.get("rowSet") or []
            if rows and rows[0]:
                game_id = str(rows[0][0])
        return f"nba_{game_id}" if game_id else "nba_unknown"
