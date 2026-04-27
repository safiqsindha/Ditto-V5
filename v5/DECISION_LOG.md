# v5 Decision Log

**Session:** Infrastructure build, 2026-04-27  
**Format:** Each decision logged per instructions with Default/Alternative/Reversibility framing.

---

## Decision D-0: Reference Repos Inaccessible

**Context:** Beginning the build. User specified "Reference experiments are v3 and v4 main, both in the repo."

**Question:** v3 (safiqsindha/Project-Ditto-V3) and v4 (safiqsindha/Project-Ditto-V4) are in separate GitHub repositories. The MCP session is scoped only to safiqsindha/Ditto-V5. How do we handle the lack of reference code?

**Default chosen:** Build infrastructure from first principles using the detailed description in the build prompt (ACTIONABLE_TYPES, McNemar pipeline, v1.1 amendments, Gate 2 floor, event schema) as the authoritative specification. No speculative inference beyond what's described.

**Reasoning:** The prompt is sufficiently detailed to reconstruct the harness. Attempting to infer undescribed v3/v4 specifics risks introducing artifacts. Building from the explicit specification is safer than building from inferred code.

**Alternatives considered:**
- Clone v3/v4 repos via git: Would require external network access not available in session.
- Ask user to wait: Violates the "don't block, pick a defensible default" instruction.

**Reversibility:** Moderate — if v3/v4 have subtly different McNemar implementations or ACTIONABLE_TYPES, individual harness files will need adjustment. File-level changes, not architectural.

**Needs review before SPEC sign-off:** Yes — please review `src/harness/` against v3/v4 implementations to confirm alignment.

---

## Decision D-1: Sample Size — Fortnite

**Context:** Setting sample target for Fortnite data acquisition pipeline.

**Question:** How many tournament matches to pull for Fortnite? No specific number given beyond "~1,200 chains worth of upstream data per cell."

**Default chosen:** 200 tournament matches. Breakdown: 140 FNCS Chapter 5 Season 1 (70%) + 60 Cash Cup 2024 (30%).

**Reasoning:** At ~120 events/match and window_size=5/step=3, a 200-match corpus produces ~8,000 chain candidates (4 chains per stream segment), well above the 2,000-3,000 needed to hit 1,200 post-Gate2. This leaves headroom for real T's lower extraction rate.

**Alternatives considered:**
- 100 matches: Would produce ~4,000 candidates, borderline if real T retains <50%.
- 500 matches: Overkill for infrastructure phase; acquisition takes longer and storage is larger.

**Reversibility:** Easy — config/cells.yaml `sample_target_matches` is a single integer.

**Needs review before SPEC sign-off:** Yes — confirm adequacy of 200 once T extraction rate is estimated.

---

## Decision D-2: Sample Size — NBA

**Context:** Setting sample target for NBA pipeline.

**Question:** How many games? NBA season has 1,230 regular season games + 82-105 playoff games.

**Default chosen:** 300 games: 240 regular season (80%) + 60 playoffs (20%). Season: 2023-24.

**Reasoning:** NBA play-by-play has ~220 rows per game, of which ~100-150 are decision events (types 1-10). 300 games × 120 events = 36,000 events upstream. At window_size=5/step=3, ~12,000 chains pre-filter. Well above target.

**Alternatives considered:**
- Use both 2022-23 and 2023-24 seasons: More data but broader time range introduces roster/strategy changes that complicate interpretation.
- 500 games: More representative but acquisition time is proportionally longer.

**Reversibility:** Easy — `sample_target_games` in config.

**Needs review before SPEC sign-off:** Yes — confirm 2023-24 single-season scope is appropriate. Also: [REQUIRES SIGN-OFF] whether to include All-Star game (excluded by default).

---

## Decision D-3: Sample Size — CS:GO/CS2

**Context:** Setting sample target for CS:GO pipeline.

**Question:** How many maps? Each HLTV best-of-3 series has 2-3 maps.

**Default chosen:** 150 maps from 2024 S-tier events: IEM Katowice 2024 (~50), BLAST Premier 2024 (~50), ESL One 2024 (~50).

**Reasoning:** 150 maps × ~300 events (round-level granularity) = 45,000 events. At window_size=5, ~15,000 chain candidates. Well-sized for the target. Three tournaments provides stylistic diversity (different meta phases of 2024 CS2).

**Alternatives considered:**
- All 2024 S-tier maps (~300+): More comprehensive but demo download time becomes a bottleneck.
- Single tournament (IEM Katowice): Lower diversity; one tournament's meta may not generalize.

**Reversibility:** Easy — config stratification fractions and `sample_target_maps`.

**Needs review before SPEC sign-off:** Yes — confirm tournament tier definition (S-tier per HLTV ranking).

---

## Decision D-4: Sample Size — Rocket League

**Context:** Setting sample target for Rocket League pipeline.

**Question:** How many RLCS replays?

**Default chosen:** 250 replays. Breakdown: 75 World Championship (30%) + 100 Majors (40%) + 75 Regionals (30%). Season: RLCS 2024.

**Reasoning:** RL replays average ~200 hit-level events per 5-minute game. 250 × 200 = 50,000 events. At window_size=5, ~16,750 chain candidates. Good headroom. World Championship overrepresented slightly relative to volume (fewer games played) because highest competitive quality.

**Alternatives considered:**
- 500 replays: More comprehensive but BallChasing free tier rate limits would make acquisition slower.
- Only World Championship: Too few games total (~40-50 in 2024 WC) for statistical adequacy.

**Reversibility:** Easy — config.

**Needs review before SPEC sign-off:** Yes — confirm RLCS 2024 season dates and BallChasing playlist filter string.

---

## Decision D-5: Sample Size — Hearthstone

**Context:** Setting sample target for Hearthstone pipeline.

**Question:** How many games? HSReplay tracks millions of games but Legend-rank games are rarer.

**Default chosen:** 300 Legend-rank games: 120 legend 1-100 (40%) + 180 legend 101-1000 (60%). Year: 2024.

**Reasoning:** HS games average ~15 turns per player × 5-6 decisions/turn = ~80 decision events per game. 300 × 80 = 24,000 events. At window_size=5, ~7,740 chain candidates. Adequate. Top-legend (1-100) oversampled relative to population to capture highest-skill decision-making.

**Alternatives considered:**
- Standard ladder (non-Legend): Decision quality lower; harder to attribute decisions to strategic constraint application.
- All-legend (not stratified): Less control over rank distribution; top-100 decisions may be qualitatively different.

**Reversibility:** Easy — config.

**Needs review before SPEC sign-off:** Yes — confirm "Legend" is the right rank tier (vs Diamond 1+ or Top 500).

---

## Decision D-6: Time Range — 2024 Calendar Year

**Context:** Setting time range for all five data sources.

**Question:** Should we use 2024 calendar year or most recent 12 months from date of acquisition?

**Default chosen:** 2024 calendar year (Jan 1 – Dec 31, 2024) for all cells.

**Reasoning:** Aligns all five cells to the same temporal scope, avoiding cross-cell confounds from different meta/patch environments. Calendar year is a clean, pre-specifiable boundary.

**Alternatives considered:**
- "Most recent N months": Risk of inconsistent cut-offs if acquisition happens over multiple days.
- 2023-2024 combined: More data but introduces two-season variation in strategy/meta.

**Reversibility:** Easy — date parameters in config.

**Needs review before SPEC sign-off:** Yes — flag any cell where 2024 data is sparse (Hearthstone rotation, RL off-season periods).

---

## Decision D-7: CS:GO Granularity Default (Round-Level)

**Context:** CS2 demo files are 128Hz tick-rate. Must choose event granularity.

**Question:** Operate at round-level, tick-sampled, or clutch-level?

**Default chosen:** Round-level — kill events, grenade events, bomb events, and buy-phase events. ~300 events per map.

**Reasoning:** Round-level provides semantically clear decision units (each kill/utility represents a discrete agent decision). Tick-level would produce ~100k events per map which is incompatible with chain-length constraints and T's expected operating scale. This default is flagged in SPEC.md Q5 as [REQUIRES SIGN-OFF].

**Alternatives considered:**
- Tick-sampled (every 256 ticks = 2 seconds): ~6,750 events/map; more granular but generates mostly non-decision frames.
- Clutch-level: Semantically meaningful but adds complexity in defining "clutch" situation without T review.

**Reversibility:** Moderate — extractor.py would need reworking; event schema is unchanged.

**Needs review before SPEC sign-off:** YES — marked BLOCKING in SPEC.md.

---

## Decision D-8: Rocket League Parser — carball Primary, rrrocket Fallback

**Context:** Two viable parsers exist: carball (Python) and rrrocket (Rust binary).

**Question:** Which parser to use as primary?

**Default chosen:** `carball` as primary (pip-installable Python package), `rrrocket` subprocess as fallback.

**Reasoning:** carball is directly pip-installable in the Python environment, produces structured Python objects, and provides hit-level abstraction out of the box. rrrocket produces raw JSON requiring more post-processing.

**Alternatives considered:**
- rrrocket primary: Better performance for large replay sets but requires Rust compilation or pre-built binary.
- Use only carball: Carball may not be maintained for all replay versions; rrrocket fallback provides robustness.

**Reversibility:** Easy — `_parse_replay()` method in pipeline.py; parser output schema is normalized in extractor.

**Needs review before SPEC sign-off:** No — this is a tooling choice, not a methodological one.

---

## Decision D-9: Hearthstone Granularity Default (Per-Action)

**Context:** HS hslog provides per-packet granularity (card plays, attacks, hero power, battlecries).

**Question:** Per-action or per-turn granularity?

**Default chosen:** Per-action — each card play, attack, hero power = one GameEvent. Produces ~80 events/game.

**Reasoning:** Per-action preserves the most decision information. A single turn may contain multiple strategically significant decisions (e.g., trading before playing a threat). Per-turn would collapse this into one event and lose sequencing information.

**Alternatives considered:**
- Per-turn: Simpler chains; each chain = one game turn context. But loses intra-turn decision ordering.

**Reversibility:** Moderate — extractor.py tree walker would be reworked. Schema unchanged.

**Needs review before SPEC sign-off:** YES — marked BLOCKING in SPEC.md (Q8).

---

## Decision D-10: NBA Tracking Data Not Available

**Context:** NBA Stats API is public; Second Spectrum spatial tracking data is not.

**Question:** Should NBA cell be built with play-by-play only (no spatial tracking) or should we flag this as a limitation?

**Default chosen:** Build with play-by-play only. Log explicitly that spatial tracking is unavailable. This limits the `location_context` field to play description strings and score, not x/y court coordinates.

**Reasoning:** Play-by-play is sufficient for event extraction at the play-level or possession-level. The location_context field can be populated with period/clock/score as a reasonable substitute. Spatial tracking would require a partnership with Second Spectrum or another licensed provider — out of scope.

**Alternatives considered:**
- Use shot chart API (public, limited): Only covers shots, not all play types.
- Partner data source: Out of scope for infrastructure build.

**Reversibility:** Easy — extractor.py could be extended with spatial data if a source becomes available.

**Needs review before SPEC sign-off:** Yes — flag this limitation in SPEC.md final version. [Already noted in §4.2]

---

## Decision D-11: ACTIONABLE_TYPES Whitelist — v1.1 Adopted as-Is

**Context:** Building the harness. The prompt specifies "Reuse v4's ACTIONABLE_TYPES whitelist and v1.1 amendments (ResourceBudget in actionables, phase_ prefix strip) as defaults."

**Question:** Should any cell's data suggest the whitelist needs adaptation, should we adapt now or flag for review?

**Default chosen:** Adopt v1.1 whitelist exactly as described. Flag in DECISION_LOG (this entry). Do not adapt for any specific cell without sign-off.

**Reasoning:** The pilot run with mock data showed 100% retention across all cells, suggesting the whitelist is broad enough to capture all mock event types. With real data, a narrower retention rate may emerge — if any cell falls below 50% Gate 2 floor with real data, that warrants a sign-off discussion, not a unilateral whitelist change.

**Alternatives considered:**
- Add domain-specific types now: Premature without T review; risk of widening the whitelist beyond what v3 used.

**Reversibility:** Easy — `CELL_ACTIONABLE_OVERRIDES` dict in actionables.py is ready to receive per-cell additions.

**Needs review before SPEC sign-off:** Yes — confirm v1.1 whitelist matches v4's implemented version.

---

## Decision D-12: Chain Construction Interfaces — Not Defaulted

**Context:** Chain construction requires pre-registration of chain length and granularity.

**Question:** Should we set default chain length parameters in the stub to avoid "empty interface" risk?

**Default chosen:** No defaults set. Both `ChainBuilder.build()` and all domain `TranslationFunction.translate()` raise `NotImplementedError` with explicit messages referencing SPEC.md sign-off sections.

**Reasoning:** Setting defaults — even "just for infrastructure" — risks those defaults becoming de facto choices if sign-off is delayed. The user's instructions are explicit: "don't default and proceed" for chain construction.

**Alternatives considered:**
- Set chain_length=5 as placeholder: Violates explicit out-of-scope instruction.

**Reversibility:** N/A — stubs contain no defaults to reverse.

**Needs review before SPEC sign-off:** YES — BLOCKING.

---

## Decision D-13: Mock Data Sizing

**Context:** Mock data must be "sized for ~1,200 chains downstream." MockT uses window_size=5, step_size=3.

**Question:** How many events per mock game to generate?

**Default chosen:**
- Fortnite: 120 events/match (200 matches → 24,000 events)
- NBA: 180-200 events/game (300 games → ~55,200 events)
- CS:GO: 300 events/map (150 maps → 45,000 events)
- Rocket League: 200 events/replay (250 replays → 50,000 events)
- Hearthstone: 75-80 events/game (300 games → ~23,100 events)

Pilot run confirmed 7,740–18,420 chains per cell (all well above 1,200 target).

**Reasoning:** Per-domain estimates based on real expected event rates at chosen granularity. Slightly conservative to account for real T's lower extraction rate.

**Alternatives considered:**
- Uniform 100 events/game across all cells: Doesn't reflect domain-specific event rates.

**Reversibility:** Easy — `n_events` parameter in `generate_mock_data()` per pipeline.

**Needs review before SPEC sign-off:** No — mock sizing doesn't affect pre-registration decisions.
