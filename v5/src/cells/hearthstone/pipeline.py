"""
Hearthstone data acquisition pipeline for v5.

Data source: MOCK only.

HSReplay.net does not provide a public bulk replay API; partner access is
required and out of scope for this project.  The pipeline generates a
deterministic synthetic dataset that preserves Hearthstone's turn-based
decision structure (card plays, attacks, hero powers, mana management) at
Legend-rank quality.

300 games × ~80 events/game → ~24,000 events, sufficient for HearthstoneT
chain generation.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...common.config import CellConfig
from ...common.schema import EventStream
from ..base_pipeline import BasePipeline
from .extractor import HearthstoneExtractor

logger = logging.getLogger(__name__)


class HearthstonePipeline(BasePipeline):
    """
    Hearthstone pipeline (mock-only).

    fetch()          → returns [] (no real API available)
    parse()          → returns [] (no real API available)
    extract_events() → returns [] (not called in mock path)
    generate_mock_data() → 300 deterministic Legend-rank game streams
    """

    def __init__(self, config: CellConfig, data_root: Path | None = None):
        super().__init__(config, data_root or Path(__file__).parent.parent.parent.parent / "data")
        self.extractor = HearthstoneExtractor()

    def fetch(self) -> list[Path]:
        logger.info("[hearthstone] No real API available; mock data will be used.")
        return []

    def parse(self, raw_paths: list[Path]) -> list[dict]:
        return []

    def extract_events(self, game_records: list[dict]) -> list[EventStream]:
        return [self.extractor.extract(record) for record in game_records if record]

    def generate_mock_data(self) -> list[EventStream]:
        """
        Generate mock Hearthstone event streams.
        300 Legend games, ~80 events per game
        (~10-15 turns × 5-8 decisions/turn).
        Events carry phase="turn_N" so HearthstoneT groups by turn.
        """
        streams = []
        n_top = int(self.config.sample_target * 0.40)    # legend 1-100
        n_mid = self.config.sample_target - n_top         # legend 101-1000

        for i in range(n_top):
            stream = self._make_mock_stream(
                game_id=f"mock_hs_legend_top_{i:04d}",
                cell="hearthstone",
                n_events=80,
                event_types=HS_MOCK_EVENT_TYPES,
                actors=["player_1", "player_2"],
                seed=i,
            )
            stream.metadata.update({
                "rank_bucket": "legend_1_100",
                "format": "standard",
                "year": "2024",
            })
            _stamp_hs_turns(stream, n_turns=14)
            streams.append(stream)

        for i in range(n_mid):
            stream = self._make_mock_stream(
                game_id=f"mock_hs_legend_mid_{i:04d}",
                cell="hearthstone",
                n_events=75,
                event_types=HS_MOCK_EVENT_TYPES,
                actors=["player_1", "player_2"],
                seed=10000 + i,
            )
            stream.metadata.update({
                "rank_bucket": "legend_101_1000",
                "format": "standard",
                "year": "2024",
            })
            _stamp_hs_turns(stream, n_turns=14)
            streams.append(stream)

        logger.info(f"[hearthstone] Generated {len(streams)} mock streams")
        return streams


HS_MOCK_EVENT_TYPES = [
    "draft_pick",            # playing a card
    "ability_use",           # hero power
    "resource_gain",         # drawing a card
    "resource_spend",        # spending mana
    "resource_budget",       # mana budget decision (v1.1)
    "target_select",         # targeting minion/face
    "engage_decision",       # attacking
    "disengage_decision",    # choosing not to trade
    "objective_contest",     # trading minions
    "team_coordinate",       # combo activation
    "timing_commit",         # playing on curve vs holding
    "risk_accept",           # greedy play
    "risk_reject",           # tempo vs value choice
    "strategy_adapt",        # reactive play to opponent's board
    "position_commit",       # minion positioning for AoE dodging
    "zone_enter",            # playing into opponent's zone
    "concede",               # concession (rare, but decision event)
]


def _stamp_hs_turns(stream, n_turns: int = 14) -> None:
    """Assign phase='turn_N' to events so HearthstoneT can group by turn."""
    n = len(stream.events)
    if n == 0:
        return
    per_turn = max(1, n // n_turns)
    for idx, ev in enumerate(stream.events):
        turn = min(n_turns, idx // per_turn + 1)
        ev.phase = f"turn_{turn}"
