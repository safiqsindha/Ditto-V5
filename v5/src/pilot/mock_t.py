"""
MockT — deterministic mock TranslationFunction for pilot harness testing.

MockT converts event streams to chain candidates using simple heuristics
(sliding window over actionable events). It is NOT a real T implementation —
it exists solely to let the pilot harness and cell runner run end-to-end
without a real T.

Real T implementations require both-author review and are out of scope.
"""

from __future__ import annotations

import hashlib

from ..common.schema import ChainCandidate, EventStream
from ..harness.actionables import is_actionable
from ..interfaces.translation import TranslationFunction


class MockT(TranslationFunction):
    """
    Deterministic mock translation function.

    Algorithm: sliding window over actionable events in the stream.
    Window size = window_size. Step = step_size.
    Each window becomes one ChainCandidate.

    This is intentionally simplistic — it demonstrates interface compliance
    without making any real constraint-chain decisions.
    """

    def __init__(
        self,
        cell: str,
        window_size: int = 5,
        step_size: int = 3,
        min_actionable_fraction: float = 0.0,
    ):
        self._cell = cell
        self.window_size = window_size
        self.step_size = step_size
        self.min_actionable_fraction = min_actionable_fraction

    @property
    def cell(self) -> str:
        return self._cell

    def translate(self, stream: EventStream) -> list[ChainCandidate]:
        """
        Slide a window over the event stream, emitting one chain per window.
        Only includes events that are actionable under v1.1 rules.
        """
        events = stream.events
        if not events:
            return []

        chains = []
        i = 0
        chain_idx = 0
        while i + self.window_size <= len(events):
            window = events[i:i + self.window_size]
            actionable = [e for e in window if is_actionable(e, self.cell)]

            if not actionable:
                i += self.step_size
                continue

            frac = len(actionable) / len(window)
            if frac < self.min_actionable_fraction:
                i += self.step_size
                continue

            chain_id = self._make_chain_id(stream.game_id, i, chain_idx)
            candidate = ChainCandidate(
                chain_id=chain_id,
                game_id=stream.game_id,
                cell=self.cell,
                events=window,
                chain_metadata={
                    "window_start": i,
                    "window_size": len(window),
                    "n_actionable": len(actionable),
                    "actionable_fraction": frac,
                    "mock": True,
                },
            )
            chains.append(candidate)
            chain_idx += 1
            i += self.step_size

        # Handle partial tail window (if remaining events > 0)
        if i < len(events) and len(events) - i >= 2:
            tail = events[i:]
            actionable = [e for e in tail if is_actionable(e, self.cell)]
            if actionable:
                chain_id = self._make_chain_id(stream.game_id, i, chain_idx)
                chains.append(ChainCandidate(
                    chain_id=chain_id,
                    game_id=stream.game_id,
                    cell=self.cell,
                    events=tail,
                    chain_metadata={
                        "window_start": i,
                        "window_size": len(tail),
                        "n_actionable": len(actionable),
                        "actionable_fraction": len(actionable) / len(tail),
                        "mock": True,
                        "is_tail": True,
                    },
                ))

        return chains

    @staticmethod
    def _make_chain_id(game_id: str, window_start: int, chain_idx: int) -> str:
        raw = f"{game_id}_{window_start}_{chain_idx}"
        return "mock_chain_" + hashlib.md5(raw.encode()).hexdigest()[:12]
