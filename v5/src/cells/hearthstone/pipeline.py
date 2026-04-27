"""
Hearthstone data acquisition pipeline for v5.

Data source: HSReplay.net API + HearthSim hslog package.
API key required for bulk access: env var HSREPLAY_API_KEY.
Fallback: parse locally provided .log files using hslog (HearthSim).

Sample target: 300 Legend-rank ladder games from 2024.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from ...common.config import CellConfig
from ...common.schema import EventStream
from ..base_pipeline import BasePipeline
from .extractor import HearthstoneExtractor

logger = logging.getLogger(__name__)

HSREPLAY_API = "https://hsreplay.net/api/v1"
HSREPLAY_REPLAYS_ENDPOINT = f"{HSREPLAY_API}/replays/"

LEGEND_RANK_RANGE = "legend"


class HearthstonePipeline(BasePipeline):
    """
    Hearthstone pipeline: fetches Legend replays from HSReplay, parses hslog, extracts events.

    fetch()         → downloads .hsreplay files from HSReplay API or HSLog files
    parse()         → parses with hearthstone.hslog packet parser
    extract_events()→ HearthstoneExtractor.extract() per game log
    """

    def __init__(self, config: CellConfig, data_root: Optional[Path] = None):
        super().__init__(config, data_root or Path(__file__).parent.parent.parent.parent / "data")
        self.extractor = HearthstoneExtractor()
        self.api_key = os.getenv("HSREPLAY_API_KEY", "")
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"X-Api-Key": self.api_key})

    def fetch(self) -> List[Path]:
        """Fetch replay files from HSReplay API."""
        paths = []
        replay_ids = self._list_legend_replays()

        for replay_id in replay_ids[:self.config.sample_target]:
            out_path = self.raw_dir / f"{replay_id}.hsreplay"
            if out_path.exists():
                paths.append(out_path)
                continue
            try:
                url = f"{HSREPLAY_REPLAYS_ENDPOINT}{replay_id}/"
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    replay_xml = data.get("replay_xml", "")
                    if replay_xml:
                        with open(out_path, "w") as f:
                            f.write(replay_xml)
                        paths.append(out_path)
                elif resp.status_code == 403:
                    logger.error(
                        "HSReplay API key required for bulk replay access. "
                        "Set HSREPLAY_API_KEY. Falling back to mock data."
                    )
                    break
                elif resp.status_code == 429:
                    logger.warning("HSReplay rate limit; backing off 60s")
                    time.sleep(60)
                time.sleep(1.0)
            except Exception as e:
                logger.error(f"HSReplay fetch error for {replay_id}: {e}")
        return paths

    def parse(self, raw_paths: List[Path]) -> List[dict]:
        """Parse .hsreplay XML files using hearthstone.hslog."""
        try:
            from hearthstone.hslog.export import EntityTreeExporter
            from hearthstone.hslog.parser import LogParser
        except ImportError:
            logger.error("hearthstone package not installed. Run: pip install hearthstone")
            return []

        records = []
        for path in raw_paths:
            try:
                parser = LogParser()
                with open(path) as f:
                    content = f.read()
                parser.read(content)
                exporter = EntityTreeExporter(parser.games[0])
                game_tree = exporter.export()
                records.append({
                    "game_id": path.stem,
                    "game_tree": game_tree,
                    "raw_path": str(path),
                })
            except Exception as e:
                logger.warning(f"hslog parse error for {path}: {e}")
        return records

    def extract_events(self, game_records: List[dict]) -> List[EventStream]:
        return [self.extractor.extract(record) for record in game_records if record]

    def generate_mock_data(self) -> List[EventStream]:
        """
        Generate mock Hearthstone event streams.
        300 Legend games, ~80 events per game
        (typical HS game ~10-15 turns × 5-8 decisions/turn).
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
            streams.append(stream)

        logger.info(f"[hearthstone] Generated {len(streams)} mock streams")
        return streams

    def _list_legend_replays(self) -> List[str]:
        """Query HSReplay API for Legend replay IDs."""
        ids = []
        params = {
            "rank": LEGEND_RANK_RANGE,
            "format": "standard",
            "limit": self.config.sample_target,
        }
        try:
            resp = self.session.get(HSREPLAY_REPLAYS_ENDPOINT, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                ids = [r.get("shortid", r.get("id", "")) for r in data.get("results", [])]
        except Exception as e:
            logger.error(f"HSReplay list error: {e}")
        return [r for r in ids if r]


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
