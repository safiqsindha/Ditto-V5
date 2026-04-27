"""
CS:GO / CS2 data acquisition pipeline for v5.

Data sources:
  - HLTV demo archive (publicly accessible .dem files for completed matches)
  - awpy Python package (wraps markus-wa/demoinfocs-golang) for demo parsing

No credentials required for HLTV public demos (decision D-C2).
Sample target: 150 S-tier tournament maps from 2024.

Note on CS2: HLTV serves CS2 demos since August 2023. awpy handles both
CS:GO and CS2 demo formats transparently (decision D-C1).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

from ...common.config import CellConfig
from ...common.schema import EventStream
from ..base_pipeline import BasePipeline
from .extractor import CSGOExtractor

logger = logging.getLogger(__name__)

HLTV_BASE = "https://www.hltv.org"

# 2024 S-tier tournament match IDs (HLTV match IDs for demo downloads)
# These are representative IDs — real pipeline fetches from HLTV results page.
HLTV_2024_MATCH_IDS = {
    "IEM_Katowice_2024": list(range(2370000, 2370050)),
    "BLAST_Premier_2024": list(range(2380000, 2380050)),
    "ESL_One_2024": list(range(2390000, 2390050)),
}

HLTV_DEMO_URL_TEMPLATE = "https://www.hltv.org/download/demo/{match_id}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; v5-research-pipeline/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
}


class CSGOPipeline(BasePipeline):
    """
    CS:GO/CS2 pipeline: downloads HLTV demos, parses with awpy, extracts events.

    fetch()         → downloads .dem files from HLTV
    parse()         → runs awpy DemoParser per .dem file
    extract_events()→ CSGOExtractor.extract() per parsed demo
    """

    def __init__(self, config: CellConfig, data_root: Path | None = None):
        super().__init__(config, data_root or Path(__file__).parent.parent.parent.parent / "data")
        self.extractor = CSGOExtractor()

    def fetch(self) -> list[Path]:
        """Download .dem files from HLTV demo archive."""
        paths = []
        match_ids = self._get_target_match_ids()
        session = requests.Session()
        session.headers.update(HEADERS)

        for match_id in match_ids[:self.config.sample_target]:
            out_path = self.raw_dir / f"{match_id}.dem"
            if out_path.exists():
                paths.append(out_path)
                continue
            url = HLTV_DEMO_URL_TEMPLATE.format(match_id=match_id)
            try:
                resp = session.get(url, timeout=60, stream=True)
                if resp.status_code == 200:
                    with open(out_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    paths.append(out_path)
                    logger.info(f"Downloaded demo {match_id}")
                else:
                    logger.warning(f"HLTV returned {resp.status_code} for match {match_id}")
                time.sleep(1.5)  # Be respectful of HLTV rate limits
            except Exception as e:
                logger.error(f"Failed to fetch demo {match_id}: {e}")
        return paths

    def parse(self, raw_paths: list[Path]) -> list[dict]:
        """Parse .dem files using awpy."""
        try:
            from awpy import DemoParser
        except ImportError:
            logger.error("awpy not installed. Run: pip install awpy")
            return []

        records = []
        for dem_path in raw_paths:
            json_path = self.processed_dir / (dem_path.stem + ".json")
            if json_path.exists():
                try:
                    with open(json_path) as f:
                        records.append(json.load(f))
                    continue
                except Exception:
                    pass
            try:
                parser = DemoParser(path=str(dem_path))
                data = parser.parse()
                with open(json_path, "w") as f:
                    json.dump(data, f)
                records.append(data)
                logger.info(f"Parsed {dem_path.name}")
            except Exception as e:
                logger.error(f"awpy parse error for {dem_path}: {e}")
        return records

    def extract_events(self, game_records: list[dict]) -> list[EventStream]:
        return [self.extractor.extract(record) for record in game_records if record]

    def generate_mock_data(self) -> list[EventStream]:
        """
        Generate mock CS2 event streams.
        150 tournament maps, ~300 events per map (full match ~2700 ticks,
        filtered to ~300 actionable decision events).
        """
        streams = []
        events_per_event_group = {
            "IEM_Katowice_2024": 50,
            "BLAST_Premier_2024": 50,
            "ESL_One_2024": 50,
        }
        i = 0
        for event_name, n in events_per_event_group.items():
            for j in range(n):
                game_id = f"mock_csgo_{event_name.lower()}_{j:04d}"
                stream = self._make_mock_stream(
                    game_id=game_id,
                    cell="csgo",
                    n_events=300,
                    event_types=CSGO_MOCK_EVENT_TYPES,
                    actors=[f"ct_player_{k}" for k in range(5)] +
                           [f"t_player_{k}" for k in range(5)],
                    seed=i,
                )
                stream.metadata.update({
                    "tournament": event_name,
                    "map": ["de_mirage", "de_dust2", "de_inferno",
                            "de_nuke", "de_overpass", "de_ancient"][j % 6],
                    "format": "CS2",
                })
                streams.append(stream)
                i += 1
        logger.info(f"[csgo] Generated {len(streams)} mock streams")
        return streams

    def _get_target_match_ids(self) -> list[int]:
        ids = []
        for event_group in HLTV_2024_MATCH_IDS.values():
            ids.extend(event_group)
        return ids


CSGO_MOCK_EVENT_TYPES = [
    "engage_decision",       # shooting / engaging
    "disengage_decision",    # retreating / holding
    "resource_gain",         # picking up weapon / money
    "resource_spend",        # buying weapons (buy phase)
    "resource_budget",       # eco/force-buy decision (v1.1)
    "position_commit",       # taking a position
    "ability_use",           # grenade / utility use
    "rotation_commit",       # rotating sites
    "target_select",         # targeting specific player
    "zone_enter",            # entering bombsite
    "zone_exit",             # retaking / exiting bombsite
    "objective_contest",     # bomb plant / defuse contest
    "objective_capture",     # bomb planted / defused
    "team_coordinate",       # calling strategy
    "timing_commit",         # timing push / lurk
    "risk_accept",           # aggro peek
    "risk_reject",           # passive hold
    "strategy_adapt",        # mid-round call change
]
