"""
Evaluation prompt template + response parser for v5.

Per Q1 sign-off (D-16): two separate API calls per chain — one baseline (no
constraint context), one intervention (with constraint context). This module
defines the prompt template that turns a ChainCandidate into the user-message
string sent to the subject model.

PER-CELL PROMPT CONTENT IS DELIBERATELY GENERIC HERE.
The cell-specific phrasing (constraint description, prediction question) requires
T-design context and lands in Phase B (joint authoring). Per-cell PromptBuilder
subclasses can override `format_constraint_context()` and `format_question()`
once T is designed.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from ..common.schema import ChainCandidate, GameEvent

logger = logging.getLogger(__name__)


@dataclass
class PromptPair:
    """The two prompts (baseline + intervention) for one chain."""
    chain_id: str
    cell: str
    baseline_prompt: str
    intervention_prompt: str
    metadata: dict


class PromptBuilder:
    """
    Builds baseline + intervention prompts for one cell.

    Subclasses override per-cell hooks:
      - format_constraint_context(chain) → str
      - format_question(chain) → str
      - format_event(event, idx) → str (optional)
    """

    def __init__(self, cell: str):
        self.cell = cell

    # --- Public entry point -------------------------------------------------
    def build(self, chain: ChainCandidate) -> PromptPair:
        if chain.cell != self.cell:
            raise ValueError(
                f"PromptBuilder for cell '{self.cell}' got chain for cell '{chain.cell}'"
            )

        chain_block = self.format_chain(chain)
        question = self.format_question(chain)
        constraint_block = self.format_constraint_context(chain)

        baseline_prompt = self._compose(
            chain_block=chain_block,
            constraint_block=None,
            question=question,
        )
        intervention_prompt = self._compose(
            chain_block=chain_block,
            constraint_block=constraint_block,
            question=question,
        )

        return PromptPair(
            chain_id=chain.chain_id,
            cell=self.cell,
            baseline_prompt=baseline_prompt,
            intervention_prompt=intervention_prompt,
            metadata={
                "n_events": len(chain.events),
                "chain_length": len(chain.events),
                "actor_count": len({e.actor for e in chain.events}),
            },
        )

    # --- Composition --------------------------------------------------------
    @staticmethod
    def _compose(chain_block: str, constraint_block: Optional[str], question: str) -> str:
        parts: List[str] = []
        if constraint_block:
            parts.append("## Constraint Context\n" + constraint_block.strip())
        parts.append("## Event Chain\n" + chain_block.strip())
        parts.append("## Question\n" + question.strip())
        return "\n\n".join(parts)

    # --- Per-cell hooks (override in subclasses) ----------------------------
    def format_chain(self, chain: ChainCandidate) -> str:
        """Default: render each event on its own line. Subclasses can prettify."""
        lines = []
        for i, ev in enumerate(chain.events):
            lines.append(self.format_event(ev, i))
        return "\n".join(lines)

    def format_event(self, event: GameEvent, idx: int) -> str:
        """Default: 'idx | t=TIME | TYPE by ACTOR (context_summary)'."""
        ctx_summary = self._summarize_context(event.location_context)
        return (
            f"{idx:>3}. t={event.timestamp:>7.1f}s | "
            f"{event.event_type:<22} | actor={event.actor:<24} "
            f"| {ctx_summary}"
        )

    def format_constraint_context(self, chain: ChainCandidate) -> str:
        """
        TBD per cell — pre-registered at T-design time (Phase B).

        Default placeholder explains why this is unset.
        """
        return (
            f"[CONSTRAINT CONTEXT FOR {self.cell.upper()} — TO BE DEFINED AT T-DESIGN]\n"
            "Per SPEC §6 (T design), the constraint context language is locked "
            "during the T-design joint authoring session. This default is a "
            "placeholder so prompt construction can be tested infrastructure-side."
        )

    def format_question(self, chain: ChainCandidate) -> str:
        """
        TBD per cell — pre-registered at T-design time (Phase B).
        """
        return (
            "[QUESTION TBD AT T-DESIGN]\n"
            "Predict the actor or event-type that follows. "
            "Reply with a single token only."
        )

    @staticmethod
    def _summarize_context(ctx: dict) -> str:
        if not ctx:
            return ""
        # Cap at 6 keys, 80 chars total to keep prompt compact
        items = list(ctx.items())[:6]
        s = ", ".join(f"{k}={_short(v)}" for k, v in items)
        return s[:120]


def _short(v) -> str:
    if isinstance(v, float):
        return f"{v:.2f}"
    s = str(v)
    return s if len(s) <= 32 else s[:29] + "..."


# ---------------------------------------------------------------------------
# Per-cell PromptBuilder stubs.
# These hold the per-cell hooks; cell-specific prompt content is filled in
# at T-design time (Phase B).
# ---------------------------------------------------------------------------

class FortnitePromptBuilder(PromptBuilder):
    def __init__(self):
        super().__init__(cell="fortnite")


class NBAPromptBuilder(PromptBuilder):
    def __init__(self):
        super().__init__(cell="nba")


class CSGOPromptBuilder(PromptBuilder):
    def __init__(self):
        super().__init__(cell="csgo")


class RocketLeaguePromptBuilder(PromptBuilder):
    def __init__(self):
        super().__init__(cell="rocket_league")


class HearthstonePromptBuilder(PromptBuilder):
    def __init__(self):
        super().__init__(cell="hearthstone")


PER_CELL_PROMPT_BUILDERS = {
    "fortnite": FortnitePromptBuilder,
    "nba": NBAPromptBuilder,
    "csgo": CSGOPromptBuilder,
    "rocket_league": RocketLeaguePromptBuilder,
    "hearthstone": HearthstonePromptBuilder,
}


# ---------------------------------------------------------------------------
# Response parser — converts model text to a normalized prediction string.
# ---------------------------------------------------------------------------

# Common abstain phrases the model might emit
_ABSTAIN_PATTERNS = re.compile(
    r"^\s*(i\s*don'?t\s*know|abstain|n/?a|unknown|cannot\s*determine|insufficient|"
    r"no\s*answer|skip)\s*\.?\s*$",
    re.IGNORECASE,
)


def parse_model_response(raw: str, allowed_predictions: Optional[List[str]] = None) -> str:
    """
    Parse a model response string into a normalized prediction.

    Returns:
      - "" if the response is empty / abstain (scoring layer treats this as -1)
      - First matched token if allowed_predictions is given and one matches
      - The first stripped non-empty line of the response otherwise

    Per Q1 sign-off (separate calls), parsing is shared between baseline and
    intervention responses.
    """
    if not raw or not raw.strip():
        return ""

    s = raw.strip()
    if _ABSTAIN_PATTERNS.match(s):
        return ""

    # If the model wrapped the answer in JSON, try to extract it
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                for k in ("answer", "prediction", "response", "value"):
                    if k in obj:
                        return str(obj[k]).strip().lower()
        except json.JSONDecodeError:
            pass

    # First line, lowercased, stripped of trailing punctuation
    first_line = s.splitlines()[0].strip().rstrip(".!?,").lower()

    if allowed_predictions:
        # Try exact match first
        for pred in allowed_predictions:
            if first_line == pred.lower():
                return pred.lower()
        # Fall through to substring match
        for pred in allowed_predictions:
            if pred.lower() in first_line:
                return pred.lower()
        # No match → return empty (will score as abstain)
        logger.debug(f"Response '{first_line[:60]}' did not match any allowed prediction")
        return ""

    return first_line
