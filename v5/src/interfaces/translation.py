"""
TranslationFunction (T) interface for v5.

T is the domain-specific function that converts a normalized GameEvent stream
into ChainCandidate objects. Each domain cell has its own T implementation.

T implementations are OUT OF SCOPE for today's build. This module defines
the interface only. All domain T implementations must be both-author reviewed
before use in evaluation.

To implement T for a domain:
  1. Subclass TranslationFunction
  2. Implement the `translate` method
  3. Register with CellRunner via runner.register_cell(cell_id, MyT())
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..common.schema import ChainCandidate, EventStream


class TranslationFunction(ABC):
    """
    Abstract base class for domain-specific translation functions.

    A TranslationFunction takes an EventStream (one game's normalized events)
    and returns a list of ChainCandidates — sequences of events that together
    constitute a candidate constraint chain for evaluation.

    The granularity, length, and semantics of the returned chains are
    domain-specific and REQUIRE SIGN-OFF before any T implementation is
    finalized. See v5/SPEC.md [REQUIRES SIGN-OFF] sections.
    """

    @property
    @abstractmethod
    def cell(self) -> str:
        """Domain cell this T serves. Must match one of VALID_CELLS."""
        ...

    @abstractmethod
    def translate(self, stream: EventStream) -> List[ChainCandidate]:
        """
        Convert a normalized event stream to candidate constraint chains.

        Parameters
        ----------
        stream : EventStream
            Normalized GameEvent sequence for one game/match.

        Returns
        -------
        List[ChainCandidate]
            Candidate chains. May be empty if no chains found in this game.

        Raises
        ------
        NotImplementedError
            Always, for stub implementations.
        """
        raise NotImplementedError(
            f"T not implemented for cell '{self.cell}'. "
            "Translation function requires both-author review before implementation. "
            "See v5/SPEC.md [REQUIRES SIGN-OFF] sections."
        )

    def batch_translate(self, streams: List[EventStream]) -> List[ChainCandidate]:
        """Translate multiple streams. Default: calls translate() per stream."""
        chains = []
        for stream in streams:
            chains.extend(self.translate(stream))
        return chains


# ---------------------------------------------------------------------------
# Per-domain T stubs — one per cell.
# These raise NotImplementedError and serve as placeholders in the registry.
# ---------------------------------------------------------------------------

class FortniteT(TranslationFunction):
    """Translation function for Fortnite cell. NOT IMPLEMENTED."""

    @property
    def cell(self) -> str:
        return "fortnite"

    def translate(self, stream: EventStream) -> List[ChainCandidate]:
        raise NotImplementedError(
            "FortniteT requires both-author review. See SPEC.md §T-Fortnite."
        )


class NBAT(TranslationFunction):
    """Translation function for NBA cell. NOT IMPLEMENTED."""

    @property
    def cell(self) -> str:
        return "nba"

    def translate(self, stream: EventStream) -> List[ChainCandidate]:
        raise NotImplementedError(
            "NBAT requires both-author review. See SPEC.md §T-NBA."
        )


class CSGOT(TranslationFunction):
    """Translation function for CS:GO/CS2 cell. NOT IMPLEMENTED."""

    @property
    def cell(self) -> str:
        return "csgo"

    def translate(self, stream: EventStream) -> List[ChainCandidate]:
        raise NotImplementedError(
            "CSGOT requires both-author review. See SPEC.md §T-CSGO."
        )


class RocketLeagueT(TranslationFunction):
    """Translation function for Rocket League cell. NOT IMPLEMENTED."""

    @property
    def cell(self) -> str:
        return "rocket_league"

    def translate(self, stream: EventStream) -> List[ChainCandidate]:
        raise NotImplementedError(
            "RocketLeagueT requires both-author review. See SPEC.md §T-RocketLeague."
        )


class HearthstoneT(TranslationFunction):
    """Translation function for Hearthstone cell. NOT IMPLEMENTED."""

    @property
    def cell(self) -> str:
        return "hearthstone"

    def translate(self, stream: EventStream) -> List[ChainCandidate]:
        raise NotImplementedError(
            "HearthstoneT requires both-author review. See SPEC.md §T-Hearthstone."
        )


# Registry of domain T stubs — used by CellRunner to auto-populate
DOMAIN_T_STUBS: dict[str, TranslationFunction] = {
    "fortnite": FortniteT(),
    "nba": NBAT(),
    "csgo": CSGOT(),
    "rocket_league": RocketLeagueT(),
    "hearthstone": HearthstoneT(),
}
