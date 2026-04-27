"""
ChainBuilder interface for v5.

ChainBuilder takes the output of T (ChainCandidates) and applies
chain-construction parameters (length, granularity, overlap policy)
to produce the final chain set for evaluation.

Chain construction is OUT OF SCOPE for today. Parameters such as:
  - Chain length (fixed vs variable)
  - Granularity (tick-level vs round-level vs possession-level)
  - Overlap policy (sliding window vs non-overlapping)

...REQUIRE SIGN-OFF before any implementation is finalized.
See v5/SPEC.md [REQUIRES SIGN-OFF] sections.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..common.schema import ChainCandidate


class ChainBuilder(ABC):
    """
    Abstract base class for chain construction.

    Takes a list of ChainCandidates from T and applies construction
    parameters to produce the final chain set.
    """

    @abstractmethod
    def build(
        self,
        candidates: List[ChainCandidate],
        chain_length: Optional[int] = None,
        overlap: bool = False,
    ) -> List[ChainCandidate]:
        """
        Build final chains from candidates.

        Parameters
        ----------
        candidates   : raw ChainCandidates from T
        chain_length : fixed chain length; None = variable (domain-determined)
        overlap      : allow overlapping chains

        Returns
        -------
        List[ChainCandidate]
            Constructed chains ready for Gate 2 and evaluation.

        Raises
        ------
        NotImplementedError
            Always, for stub implementations.
        """
        raise NotImplementedError(
            "ChainBuilder requires sign-off on chain-length and granularity decisions. "
            "See v5/SPEC.md [REQUIRES SIGN-OFF] sections."
        )


class DefaultChainBuilder(ChainBuilder):
    """
    Default chain builder stub — raises NotImplementedError.
    Replace with a concrete implementation after SPEC sign-off.
    """

    def build(
        self,
        candidates: List[ChainCandidate],
        chain_length: Optional[int] = None,
        overlap: bool = False,
    ) -> List[ChainCandidate]:
        raise NotImplementedError(
            "DefaultChainBuilder: chain construction not yet implemented. "
            "Requires pre-registration of chain_length, granularity, and overlap policy."
        )
