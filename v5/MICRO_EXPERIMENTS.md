# v5 Micro-Experiments — Flagged for Post-Hoc Investigation

**Status:** Pre-noted, NOT pre-registered for v5 primary run. These are variants the lead author flagged as "interesting if v5 results justify follow-up."

**Critical rule:** None of these may be implemented as part of the v5 primary run. They are post-v5 work, dependent on v5 results and a separate pre-registration sign-off if pursued.

---

## ME-1: Variable Chain Length (Q4-C)

**Source:** Q4 sign-off — locked at (B) fixed per cell; (C) flagged as variable-bounded chain length variant.

**Premise:** The primary v5 fixes chain length per cell. ME-1 would re-run v5 with chain length variable in [3, 15] events, T choosing per-chain.

**Contingency:** Run only if v5 primary results show significant per-cell effects in ≥ 3 of 5 cells. If primary results are null, ME-1 doesn't add interpretive value.

**Cost estimate:** Same Haiku spend as v5 Phase 1 (~$4) since chain count and number of API calls is unchanged.

**Pre-registration required:** Yes, before any data analysis on this variant.

---

## ME-2: CS:GO Tick-Sampled Granularity (Q5-C)

**Source:** Q5 sign-off — locked at (A) round-level for primary; (C) tick-sampled flagged.

**Premise:** Primary uses round-level events (~300/map). ME-2 would re-acquire CS:GO data at tick-sampled granularity (every 256 ticks ≈ 2 seconds, ~6,750 events/map) and re-run.

**Contingency:** Run only if (a) primary CS:GO cell shows a significant effect, AND (b) we want to test whether finer granularity preserves or strengthens the effect.

**Cost estimate:** Re-acquisition is free (same HLTV demos); re-evaluation = ~$1 in Haiku calls.

**Pre-registration required:** Yes.

---

## ME-3: NBA Play-Level Granularity (Q6-B)

**Source:** Q6 sign-off — locked at (A) possession-level for primary; (B) play-level flagged.

**Premise:** Primary groups plays into possessions (~85 possessions/game × 2-3 events). ME-3 would use raw play-level (~220 events/game).

**Contingency:** Run only if primary NBA cell shows a significant effect AND we want to compare granularities. Conversely, if primary NBA cell is null, ME-3 might be worth running to test whether granularity choice is the cause.

**Cost estimate:** ~$1 re-evaluation.

**Pre-registration required:** Yes.

---

## How These Get Promoted

If v5 primary results justify a micro-experiment:
1. Update this document with the specific question being tested.
2. Pre-register the micro-experiment in a new SPEC version (`v5/SPEC_v0.3_ME-N.md`).
3. Implement the variant in a side-branch (`claude/me-{N}-{shortname}`).
4. Run, score, report — same harness, just the parameter swapped.
5. Cross-reference results in v5/RESULTS/ME_{N}_results.md.
