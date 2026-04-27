"""
Base class for all v5 data acquisition pipelines.

Each domain pipeline subclasses BasePipeline and implements:
  - fetch(): downloads raw data files
  - parse(): converts raw data to structured dicts
  - extract_events(): calls the domain extractor to produce GameEvent streams
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator, List, Optional

from ..common.config import CellConfig
from ..common.schema import EventStream, GameEvent

logger = logging.getLogger(__name__)

DATA_ROOT = Path(__file__).parent.parent.parent / "data"


class BasePipeline(ABC):
    """
    Abstract data acquisition pipeline.

    Subclasses must implement fetch(), parse(), and extract_events().
    When credentials/tools are unavailable, generate_mock_data() is called
    instead of fetch() + parse(), providing a deterministic synthetic dataset
    for harness testing.
    """

    def __init__(self, config: CellConfig, data_root: Path = DATA_ROOT):
        self.config = config
        self.data_root = data_root
        self.cell = config.cell_id
        self.raw_dir = data_root / "raw" / self.cell
        self.processed_dir = data_root / "processed" / self.cell
        self.events_dir = data_root / "events" / self.cell
        for d in [self.raw_dir, self.processed_dir, self.events_dir]:
            d.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def fetch(self) -> List[Path]:
        """Download raw data files. Returns list of paths to downloaded files."""
        ...

    @abstractmethod
    def parse(self, raw_paths: List[Path]) -> List[dict]:
        """Parse raw files into structured game records."""
        ...

    @abstractmethod
    def extract_events(self, game_records: List[dict]) -> List[EventStream]:
        """Convert structured game records to normalized EventStream objects."""
        ...

    def run(self, force_mock: bool = False) -> List[EventStream]:
        """
        Full pipeline: fetch → parse → extract, with mock fallback.
        Saves event streams to data/events/{cell}/.

        Parameters
        ----------
        force_mock : bool
            If True, skip fetch/parse and use mock data regardless of credentials.
            Used for pilot validation and infrastructure testing.
        """
        if force_mock or self.config.should_use_mock():
            reason = "force_mock=True" if force_mock else f"credentials not satisfied ({self.config.env_vars})"
            logger.warning(f"[{self.cell}] Using mock data: {reason}")
            streams = self.generate_mock_data()
        else:
            logger.info(f"[{self.cell}] Fetching real data...")
            raw_paths = self.fetch()
            logger.info(f"[{self.cell}] Parsing {len(raw_paths)} files...")
            records = self.parse(raw_paths)
            logger.info(f"[{self.cell}] Extracting events from {len(records)} records...")
            streams = self.extract_events(records)

        logger.info(f"[{self.cell}] Saving {len(streams)} event streams...")
        self._save_streams(streams)
        self._print_summary(streams)
        return streams

    @abstractmethod
    def generate_mock_data(self) -> List[EventStream]:
        """
        Generate a deterministic synthetic dataset for testing.
        Must return enough streams to support ~1200 chains after filtering.
        Default implementation generates domain-generic mock events.
        Subclasses should override with domain-realistic mock data.
        """
        ...

    def _save_streams(self, streams: List[EventStream]) -> None:
        for stream in streams:
            path = self.events_dir / f"{stream.game_id}.jsonl"
            stream.to_jsonl(path)

    def _print_summary(self, streams: List[EventStream]) -> None:
        total_events = sum(len(s) for s in streams)
        logger.info(
            f"[{self.cell}] Summary: {len(streams)} games, "
            f"{total_events} total events, "
            f"avg {total_events / max(len(streams), 1):.1f} events/game"
        )

    def load_saved_streams(self) -> List[EventStream]:
        """Load previously saved event streams from disk."""
        streams = []
        for path in sorted(self.events_dir.glob("*.jsonl")):
            try:
                streams.append(EventStream.from_jsonl(path))
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")
        return streams

    @staticmethod
    def _make_mock_stream(
        game_id: str,
        cell: str,
        n_events: int,
        event_types: List[str],
        actors: List[str],
        seed: int = 0,
    ) -> EventStream:
        """Utility: generate a synthetic EventStream with realistic structure."""
        import random
        rng = random.Random(seed)
        stream = EventStream(game_id=game_id, cell=cell,
                             metadata={"mock": True, "seed": seed})
        t = 0.0
        for i in range(n_events):
            t += rng.uniform(0.5, 10.0)
            etype = rng.choice(event_types)
            actor = rng.choice(actors)
            stream.append(GameEvent(
                timestamp=round(t, 3),
                event_type=etype,
                actor=actor,
                location_context={"x": rng.uniform(0, 100), "y": rng.uniform(0, 100)},
                raw_data_blob={"mock": True, "raw_type": etype, "tick": i},
                cell=cell,
                game_id=game_id,
                sequence_idx=i,
                phase="mock_phase",
                metadata={"mock": True},
            ))
        return stream
