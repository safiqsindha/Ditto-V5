"""
ChainBuilder for v5.

Per Q4 sign-off (D-19): chain length is fixed PER CELL, varying across cells.
Per-cell N values are pre-registered at T-design time (joint authoring session).

Overlap policy: non-overlapping (sliding window with step = chain_length).
Sampling: sequential within game; cells subsample chains uniformly to hit n_chains target.

Variant (C) variable-bounded chain length is flagged for ME-1 micro-experiment.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from ..common.schema import ChainCandidate, EventStream, GameEvent

logger = logging.getLogger(__name__)


class ChainBuilder(ABC):
    """Abstract base. See FixedPerCellChainBuilder for the v5 implementation."""

    @abstractmethod
    def build(
        self,
        candidates_or_streams,
        chain_length: Optional[int] = None,
        overlap: bool = False,
    ) -> List[ChainCandidate]:
        ...


class FixedPerCellChainBuilder(ChainBuilder):
    """
    Q4-locked chain builder. Constructs fixed-length non-overlapping chains
    from EventStreams using a per-cell `chain_length` map.

    Per-cell N values are pre-registered (None = not yet locked). The builder
    raises if asked to build for a cell with N still unset, ensuring no
    accidental defaulting.

    Usage
    -----
    builder = FixedPerCellChainBuilder(per_cell_chain_length={
        "fortnite": 8, "nba": 6, "csgo": 10, "rocket_league": 12, "hearthstone": 5,
    })
    chains = builder.build_from_streams(streams, cell="nba")
    """

    def __init__(
        self,
        per_cell_chain_length: Optional[Dict[str, Optional[int]]] = None,
        overlap: bool = False,
        sampling: str = "sequential",
    ):
        # Per Q4-locked config: non-overlapping, sequential
        self.per_cell_chain_length: Dict[str, Optional[int]] = per_cell_chain_length or {
            "fortnite": None,
            "nba": None,
            "csgo": None,
            "rocket_league": None,
            "hearthstone": None,
        }
        self.overlap = overlap
        self.sampling = sampling

    def get_chain_length(self, cell: str) -> int:
        """Return the locked chain length for the cell, or raise if not set."""
        n = self.per_cell_chain_length.get(cell)
        if n is None:
            raise ValueError(
                f"chain_length for cell '{cell}' is not set. "
                "Per Q4 sign-off, per-cell N values must be locked at T-design time. "
                "Set via FixedPerCellChainBuilder(per_cell_chain_length={...}) or in "
                "config/harness.yaml chain_length.per_cell.{cell}."
            )
        if n < 1:
            raise ValueError(f"chain_length for '{cell}' must be >= 1, got {n}")
        return n

    def build_from_streams(
        self,
        streams: List[EventStream],
        cell: str,
        max_chains: Optional[int] = None,
    ) -> List[ChainCandidate]:
        """
        Build chains from a list of EventStreams for one cell.

        max_chains caps the total number of chains returned across all streams.
        Sampling is sequential (deterministic, in-order); to get an
        evenly-distributed sample, the caller should pass max_chains and the
        builder will subsample uniformly across streams.
        """
        chain_length = self.get_chain_length(cell)
        all_chains: List[ChainCandidate] = []

        for stream in streams:
            if stream.cell != cell:
                logger.warning(
                    f"Stream {stream.game_id} has cell={stream.cell} != requested {cell}; skipping"
                )
                continue
            stream_chains = self._build_one_stream(stream, chain_length)
            all_chains.extend(stream_chains)

        if max_chains is None or len(all_chains) <= max_chains:
            return all_chains

        # Uniform subsample across the full chain list
        return _uniform_subsample(all_chains, max_chains)

    def _build_one_stream(
        self, stream: EventStream, chain_length: int
    ) -> List[ChainCandidate]:
        """Slide a fixed window over the stream's events. Non-overlapping."""
        chains: List[ChainCandidate] = []
        events = stream.events
        if len(events) < chain_length:
            return chains

        step = chain_length if not self.overlap else 1
        for i in range(0, len(events) - chain_length + 1, step):
            window = events[i:i + chain_length]
            chain_id = f"{stream.game_id}_chain_{i // step:04d}"
            chains.append(ChainCandidate(
                chain_id=chain_id,
                game_id=stream.game_id,
                cell=stream.cell,
                events=window,
                chain_metadata={
                    "chain_length": chain_length,
                    "window_start": i,
                    "overlap": self.overlap,
                    "builder": "FixedPerCellChainBuilder",
                },
            ))
        return chains

    # Legacy interface compatibility — accepts either a list of ChainCandidates
    # or a list of EventStreams. The runner uses build_from_streams() directly;
    # this is here so the abstract method signature matches.
    def build(
        self,
        candidates_or_streams,
        chain_length: Optional[int] = None,
        overlap: bool = False,
    ) -> List[ChainCandidate]:
        if not candidates_or_streams:
            return []
        first = candidates_or_streams[0]
        if isinstance(first, EventStream):
            cell = first.cell
            return self.build_from_streams(candidates_or_streams, cell=cell)
        if isinstance(first, ChainCandidate):
            # Already chains; pass through
            return list(candidates_or_streams)
        raise TypeError(
            f"build() expected list of EventStream or ChainCandidate, got {type(first).__name__}"
        )


def _uniform_subsample(items: list, k: int) -> list:
    """Return k items roughly uniformly from items. Deterministic order-preserving."""
    n = len(items)
    if k >= n or k <= 0:
        return items
    step = n / k
    return [items[int(i * step)] for i in range(k)]


# Backwards-compat alias — the original DefaultChainBuilder name is referenced
# in older docs. The post-sign-off implementation IS this class.
DefaultChainBuilder = FixedPerCellChainBuilder
