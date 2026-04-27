"""
Fortnite data acquisition pipeline for v5.

Data sources:
  - xNocken/replay-downloader (Node.js CLI) for downloading FNCS/Cash Cup
    tournament replays from Epic's CDN
  - SL-x-TnT/FortniteReplayDecompressor (.NET CLI) for binary replay parsing

Credentials required:
  - EPIC_ACCOUNT_ID: Epic Games account ID
  - EPIC_ACCESS_TOKEN: OAuth2 access token for Epic account

When credentials are absent, falls back to mock data (decision D-F1).
Tournament scope: FNCS Chapter 5 Season 1 (2024) + Cash Cup 2024.
Sample target: 200 matches.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...common.config import CellConfig
from ...common.schema import EventStream, GameEvent
from ..base_pipeline import BasePipeline
from .extractor import FortniteExtractor

logger = logging.getLogger(__name__)

# FNCS 2024 tournament event IDs (sourced from Epic's tournament API)
# These are the target event IDs for data acquisition.
FNCS_2024_EVENT_IDS = [
    "fncs-ch5s1-na-east",
    "fncs-ch5s1-na-west",
    "fncs-ch5s1-europe",
    "fncs-ch5s1-brazil",
    "fncs-ch5s1-asia",
]

CASH_CUP_2024_WINDOWS = [
    "cashcup-2024-01", "cashcup-2024-02", "cashcup-2024-03",
    "cashcup-2024-04", "cashcup-2024-05", "cashcup-2024-06",
]

EPIC_REPLAY_API = "https://fn-service-habanero-live-public.ogs.live.on.epicgames.com"


class FortnitePipeline(BasePipeline):
    """
    Fortnite pipeline: downloads tournament replays, decompresses, extracts events.

    Architecture
    ------------
    fetch()         → calls replay-downloader CLI for each event window
    parse()         → calls FortniteReplayDecompressor CLI on each .replay file
    extract_events()→ FortniteExtractor.extract() per decompressed JSON
    """

    def __init__(self, config: CellConfig, data_root: Optional[Path] = None):
        super().__init__(config, data_root or Path(__file__).parent.parent.parent.parent / "data")
        self.extractor = FortniteExtractor()
        self.account_id = os.getenv("EPIC_ACCOUNT_ID", "")
        self.access_token = os.getenv("EPIC_ACCESS_TOKEN", "")

    def fetch(self) -> List[Path]:
        """
        Download tournament replays using replay-downloader CLI.

        Requires: Node.js 18+, npx xnocken/replay-downloader installed.
        Downloads to data/raw/fortnite/{event_id}/*.replay
        """
        downloaded = []
        events = self._get_target_events()
        for event_id in events:
            out_dir = self.raw_dir / event_id
            out_dir.mkdir(exist_ok=True)
            try:
                result = subprocess.run(
                    [
                        "npx", "xnocken/replay-downloader",
                        "--account-id", self.account_id,
                        "--access-token", self.access_token,
                        "--event-id", event_id,
                        "--output", str(out_dir),
                        "--limit", str(self.config.sample_target // len(events)),
                    ],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode != 0:
                    logger.error(f"replay-downloader failed for {event_id}: {result.stderr}")
                    continue
                replay_files = list(out_dir.glob("*.replay"))
                logger.info(f"Downloaded {len(replay_files)} replays for {event_id}")
                downloaded.extend(replay_files)
            except FileNotFoundError:
                logger.error("replay-downloader not found. Install: npm install -g xnocken/replay-downloader")
            except subprocess.TimeoutExpired:
                logger.error(f"replay-downloader timed out for {event_id}")
        return downloaded

    def parse(self, raw_paths: List[Path]) -> List[dict]:
        """
        Decompress .replay files using FortniteReplayDecompressor.
        Produces one JSON dict per replay.
        """
        records = []
        for replay_path in raw_paths:
            json_path = self.processed_dir / (replay_path.stem + ".json")
            try:
                result = subprocess.run(
                    [
                        "dotnet", "FortniteReplayDecompressor.dll",
                        "--replay", str(replay_path),
                        "--output", str(json_path),
                        "--export-json",
                    ],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    logger.error(f"Decompressor failed for {replay_path}: {result.stderr}")
                    continue
                if json_path.exists():
                    with open(json_path) as f:
                        records.append(json.load(f))
            except FileNotFoundError:
                logger.error("FortniteReplayDecompressor not found (.NET runtime required)")
            except Exception as e:
                logger.error(f"Parse error for {replay_path}: {e}")
        return records

    def extract_events(self, game_records: List[dict]) -> List[EventStream]:
        return [
            self.extractor.extract(record)
            for record in game_records
            if record
        ]

    def generate_mock_data(self) -> List[EventStream]:
        """
        Generate mock Fortnite event streams.
        Produces 200 mock matches with Fortnite-realistic event types.
        Each match ~120 events (tournament match ~25 min × ~5 events/min).
        """
        streams = []
        for i in range(self.config.sample_target):
            tier = "FNCS" if i < int(self.config.sample_target * 0.70) else "Cash_Cup"
            game_id = f"mock_fortnite_{tier.lower()}_{i:04d}"
            stream = self._make_mock_stream(
                game_id=game_id,
                cell="fortnite",
                n_events=120,
                event_types=FORTNITE_MOCK_EVENT_TYPES,
                actors=[f"player_{j}" for j in range(100)],
                seed=i,
            )
            stream.metadata.update({
                "tier": tier,
                "season": "Ch5S1",
                "region": ["NA_East", "NA_West", "Europe", "Brazil", "Asia"][i % 5],
            })
            streams.append(stream)
        logger.info(f"[fortnite] Generated {len(streams)} mock streams")
        return streams

    def _get_target_events(self) -> List[str]:
        strat = self.config.stratification
        events = []
        for s in strat:
            tier = s.get("tier", "")
            if tier == "FNCS":
                events.extend(FNCS_2024_EVENT_IDS)
            elif tier == "Cash_Cup":
                events.extend(CASH_CUP_2024_WINDOWS)
        return events or (FNCS_2024_EVENT_IDS + CASH_CUP_2024_WINDOWS)


# Fortnite-realistic event types for mock data
FORTNITE_MOCK_EVENT_TYPES = [
    "rotation_commit",       # storm rotation decision
    "zone_enter",            # moving into zone
    "zone_exit",             # leaving safe zone
    "engage_decision",       # choosing to fight
    "disengage_decision",    # choosing to flee / third-party avoid
    "resource_gain",         # materials gathered
    "resource_spend",        # materials used in builds
    "resource_budget",       # low-material budget decision (v1.1)
    "position_commit",       # high ground / position decision
    "ability_use",           # consumable / utility use
    "item_use",              # medkit, shields, etc.
    "target_select",         # selecting engagement target
    "risk_accept",           # risky play decision
    "risk_reject",           # safe play decision
    "timing_commit",         # timing an engagement or rotate
    "objective_contest",     # storm surge, zone fights
    "team_coordinate",       # (squads) calling rotations
    "strategy_adapt",        # mid-game strategy shift
]
