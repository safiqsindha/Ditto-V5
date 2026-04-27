"""
Rocket League data acquisition pipeline for v5.

Data source: BallChasing.com public API + rrrocket parser.
API key required (free registration): env var BALLCHASING_TOKEN.
Sample target: 250 RLCS replays from 2024.

BallChasing API: https://ballchasing.com/api
  - GET /replays with playlist=rlcs, season filter
  - GET /replays/{id} for individual replay details
  - GET /replays/{id}/download for .replay file

Parser: rrrocket (Rust) or carball (Python wrapper).
Decision D-RL1: Using carball Python package as primary; rrrocket as fallback.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import requests

from ...common.config import CellConfig
from ...common.schema import EventStream
from ..base_pipeline import BasePipeline
from .extractor import RocketLeagueExtractor

logger = logging.getLogger(__name__)

BALLCHASING_API = "https://ballchasing.com/api"
BALLCHASING_RATE_LIMIT_DELAY = 1.0  # seconds between requests (free tier)


class RocketLeaguePipeline(BasePipeline):
    """
    Rocket League pipeline: fetches RLCS replays from BallChasing, parses, extracts events.

    fetch()         → downloads .replay files from BallChasing API
    parse()         → parses .replay files with carball / rrrocket
    extract_events()→ RocketLeagueExtractor.extract() per parsed replay
    """

    def __init__(self, config: CellConfig, data_root: Path | None = None):
        super().__init__(config, data_root or Path(__file__).parent.parent.parent.parent / "data")
        self.extractor = RocketLeagueExtractor()
        self.api_token = os.getenv("BALLCHASING_TOKEN", "")
        self.session = requests.Session()
        if self.api_token:
            self.session.headers.update({"Authorization": self.api_token})

    def fetch(self) -> list[Path]:
        """Fetch RLCS replay files from BallChasing API."""
        replay_ids = self._list_rlcs_replays()
        paths = []
        for replay_id in replay_ids[:self.config.sample_target]:
            out_path = self.raw_dir / f"{replay_id}.replay"
            if out_path.exists():
                paths.append(out_path)
                continue
            try:
                url = f"{BALLCHASING_API}/replays/{replay_id}/download"
                resp = self.session.get(url, timeout=60, stream=True)
                if resp.status_code == 200:
                    with open(out_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    paths.append(out_path)
                    logger.info(f"Downloaded replay {replay_id}")
                elif resp.status_code == 429:
                    logger.warning("BallChasing rate limit hit; backing off 30s")
                    time.sleep(30)
                else:
                    logger.warning(f"BallChasing {resp.status_code} for {replay_id}")
                time.sleep(BALLCHASING_RATE_LIMIT_DELAY)
            except Exception as e:
                logger.error(f"Failed to fetch replay {replay_id}: {e}")
        return paths

    def parse(self, raw_paths: list[Path]) -> list[dict]:
        """Parse .replay files using carball."""
        records = []
        for replay_path in raw_paths:
            json_path = self.processed_dir / (replay_path.stem + ".json")
            if json_path.exists():
                try:
                    with open(json_path) as f:
                        records.append(json.load(f))
                    continue
                except Exception:
                    pass

            data = self._parse_replay(replay_path)
            if data:
                with open(json_path, "w") as f:
                    json.dump(data, f)
                records.append(data)
        return records

    def _parse_replay(self, path: Path) -> dict | None:
        """Try carball first, then rrrocket subprocess."""
        try:
            import carball
            game = carball.decompile_replay(str(path))
            return game.game_metadata.__dict__ | {
                "_hits": [h.__dict__ for h in game.get_hits()],
                "_goals": [g.__dict__ for g in game.game_metadata.goals],
                "_players": [p.id.__dict__ for p in game.players],
            }
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"carball parse error for {path}: {e}")

        # Fallback: rrrocket subprocess
        try:
            import subprocess
            result = subprocess.run(
                ["rrrocket", str(path)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
            logger.warning(f"rrrocket failed for {path}: {result.stderr}")
        except FileNotFoundError:
            logger.error("Neither carball nor rrrocket available")
        except Exception as e:
            logger.debug(f"rrrocket error for {path}: {e}")
        return None

    def extract_events(self, game_records: list[dict]) -> list[EventStream]:
        return [self.extractor.extract(record) for record in game_records if record]

    def generate_mock_data(self) -> list[EventStream]:
        """
        Generate mock Rocket League event streams.
        250 RLCS replays, ~200 events per replay (5 min game × ~40 key events/min
        at decision-event granularity — boost pickups, shots, saves, demos).
        """
        streams = []
        tier_map = {
            "RLCS_World_Championship": int(self.config.sample_target * 0.30),
            "RLCS_Major": int(self.config.sample_target * 0.40),
            "RLCS_Regional": self.config.sample_target
                              - int(self.config.sample_target * 0.30)
                              - int(self.config.sample_target * 0.40),
        }
        i = 0
        for tier, count in tier_map.items():
            for j in range(count):
                stream = self._make_mock_stream(
                    game_id=f"mock_rl_{tier.lower()}_{j:04d}",
                    cell="rocket_league",
                    n_events=200,
                    event_types=RL_MOCK_EVENT_TYPES,
                    actors=["blue_0", "blue_1", "blue_2", "orange_0", "orange_1", "orange_2"],
                    seed=i,
                )
                stream.metadata.update({"tier": tier, "season": "RLCS_2024"})
                streams.append(stream)
                i += 1
        logger.info(f"[rocket_league] Generated {len(streams)} mock streams")
        return streams

    def _list_rlcs_replays(self) -> list[str]:
        """Query BallChasing API for RLCS replay IDs."""
        ids = []
        params = {
            "playlist": "rlcs",
            "season": "f10",  # RLCS 2024 season
            "count": 200,
        }
        try:
            resp = self.session.get(f"{BALLCHASING_API}/replays", params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                ids = [r["id"] for r in data.get("list", [])]
        except Exception as e:
            logger.error(f"BallChasing list error: {e}")
        return ids


RL_MOCK_EVENT_TYPES = [
    "resource_gain",         # boost pickup
    "resource_spend",        # boost use
    "resource_budget",       # low-boost decision (v1.1)
    "engage_decision",       # shot attempt
    "disengage_decision",    # clearing / heading to goal
    "objective_contest",     # 50/50 challenge
    "objective_capture",     # goal scored
    "position_commit",       # rotating back / positioning
    "rotation_commit",       # team rotation
    "team_coordinate",       # passing / setting up teammate
    "risk_accept",           # demo attempt
    "risk_reject",           # avoiding challenge
    "timing_commit",         # aerial timing
    "ability_use",           # power slide / dodge
    "strategy_adapt",        # defensive shift after goal
    "zone_enter",            # entering boost pad zone
    "zone_exit",             # leaving boost pad zone
]
