# v5 Experiment Specification

**Status:** DRAFT — PENDING PRE-REGISTRATION SIGN-OFF  
**Version:** 0.1 (infrastructure build, 2026-04-27)  
**Authors:** [both authors required for sign-off]  
**Subject model:** Claude Haiku (claude-haiku-4-5-20251001)  
**Reference experiments:** v3 (Chess/Checkers), v4 (single-cell methodology characterization)

---

## 1. Research Question

Does the constraint-chain detection methodology from v3 — which demonstrated [result from v3] on Chess and Checkers — generalize across five new game domains when applied identically?

Specifically: does Claude Haiku's rate of actionable-chain detection differ significantly from chance across five diverse game domains (Fortnite, NBA, CS:GO/CS2, Rocket League, Hearthstone)?

---

## 2. Experimental Design

### 2.1 Design Type

Five-cell parallel replication. Each cell is an independent application of the v3 detection methodology to a different game domain. Cells share the statistical harness but have domain-specific data acquisition pipelines and translation functions (T).

### 2.2 Subject Model

Claude Haiku (`claude-haiku-4-5-20251001`). Evaluation will run against the API once this SPEC is pre-registered. **No Haiku calls before sign-off.**

### 2.3 Conditions

**Baseline:** Model given a chain without constraint context → generates a response.  
**Intervention:** Model given same chain with constraint context injected → generates a response.

[REQUIRES SIGN-OFF — Q1]: Should baseline and intervention be run in the same API call (paired prompt) or separate calls? Candidates: (a) same call with/without constraint segment, (b) two separate calls per chain.

### 2.4 Cells

| Cell | Domain | Data Source | Sample Target |
|------|---------|-------------|---------------|
| fortnite | Fortnite (FNCS/Cash Cup) | Epic CDN replay archive | 200 matches |
| nba | NBA 2023-24 | NBA Stats API (play-by-play) | 300 games |
| csgo | CS:GO/CS2 2024 S-tier | HLTV demo archive | 150 maps |
| rocket_league | RLCS 2024 | BallChasing.com API | 250 replays |
| hearthstone | HS 2024 Legend ladder | HSReplay.net API | 300 games |

---

## 3. Statistical Methodology

### 3.1 Primary Test

McNemar's test on paired binary outcomes (correct / incorrect per chain), with continuity correction.

```
H₀: P(intervention correct | baseline wrong) = P(baseline correct | intervention wrong)
H₁: P(intervention correct | baseline wrong) ≠ P(baseline correct | intervention wrong)
```

### 3.2 Multiple Comparisons

[REQUIRES SIGN-OFF — Q2]: **Bonferroni divisor.** Candidates:
- **(a) Divisor = 5** (one test per cell, α_corrected = 0.05/5 = 0.01 per cell): Conservative. Controls family-wise error rate across five independent tests.
- **(b) Divisor = 1** (one aggregate test combining all five cells): Less conservative. Appropriate if we view the experiment as testing one hypothesis about generalization, not five separate hypotheses.
- **(c) Mixed**: Per-cell tests uncorrected, plus one pre-specified aggregate test, with Bonferroni applied only to the aggregate.

Recommended default: **(a) Divisor = 5** (implemented in `config/harness.yaml`). Flagged for your override.

### 3.3 Effect Size

Cohen's h for proportion differences. Reported per cell and aggregate.

### 3.4 Confidence Intervals

Bootstrap (10,000 iterations, seed=42) at 95% confidence on the proportion difference (P(intervention) - P(baseline)).

### 3.5 Minimum Sample

n_chains per cell after Gate 2 filtering: aiming for ~1,200. Power analysis:

With Bonferroni divisor=5, α_corrected=0.01, and n=1200 chains:
- MDE ≈ 0.09 (can detect effects of 9+ percentage points with 80% power)
- This is conservative relative to v3's observed effect size.

[REQUIRES SIGN-OFF — Q3]: **Is n=1200 per cell sufficient?** If v3's effect size was smaller than 9pp, we may need more chains or to reconsider Bonferroni.

---

## 4. Data Acquisition

### 4.1 General Principles

- Tournament-tier data only for all cells (no casual/unranked matches)
- 2024 data preferred (most recent available at time of acquisition)
- Stratification by competition tier and/or season phase (see `config/cells.yaml`)
- Mock fallback when credentials unavailable (pilot and infrastructure testing only)

### 4.2 Per-Cell Sources

**Fortnite:** Epic CDN replay archive via xNocken/replay-downloader + SL-x-TnT/FortniteReplayDecompressor. FNCS Chapter 5 Season 1 (70%) + Cash Cup 2024 (30%).

**NBA:** NBA Stats API (`nba_api` package, no key required). PlayByPlayV3 endpoint. 2023-24 season: 80% regular season, 20% playoffs. Note: Second Spectrum tracking data (spatial) is NOT publicly available; this cell uses play-by-play events only.

**CS:GO/CS2:** HLTV public demo archive. CS2 format (post-August 2023). 2024 S-tier events: IEM Katowice (~33%), BLAST Premier (~34%), ESL One (~33%). Parsed with `awpy` (demoinfocs-golang wrapper).

**Rocket League:** BallChasing.com API (free tier, key required). RLCS 2024: World Championship (30%), Majors (40%), Regionals (30%). Parsed with `carball` Python package.

**Hearthstone:** HSReplay.net API (key required for bulk access). Legend-rank ladder 2024: legend 1-100 (40%), legend 101-1000 (60%). Parsed with HearthSim `hslog` package.

---

## 5. Event Extraction

### 5.1 Normalized Event Schema

All cells produce `GameEvent` objects with fields:
```
timestamp        : float  (seconds from game start, monotonic)
event_type       : str    (normalized; phase_ prefix stripped — v1.1 amendment)
actor            : str    (player/team identifier, consistent within domain)
location_context : dict   (domain-specific spatial/situational data)
raw_data_blob    : dict   (full source record)
cell             : str    (domain identifier)
game_id          : str    (unique match/game identifier)
sequence_idx     : int    (0-based ordinal within game)
```

### 5.2 Sizing Target

Each cell targets upstream event volumes sufficient for ~1,200 chains after filtering. Assuming 40-60% retention through Gate 2:
- Raw chain candidates needed: ~2,000-3,000 per cell
- Raw events needed: ~6,000-15,000 per cell (depending on chain length)
- Mock data validates this sizing; real data acquisition may require adjustment.

---

## 6. Translation Function (T)

### 6.1 Interface

T is a `TranslationFunction` that accepts an `EventStream` and returns `List[ChainCandidate]`. Interface defined in `src/interfaces/translation.py`. All domain T implementations inherit from this base class.

### 6.2 Out of Scope for Infrastructure Build

All five T implementations (`FortniteT`, `NBAT`, `CSGOT`, `RocketLeagueT`, `HearthstoneT`) are **stubs** that raise `NotImplementedError`. They require both-author review per the v6-discipline upgrade. **Do not implement T until SPEC is signed off.**

[REQUIRES SIGN-OFF — Q4]: **Chain length consistency.** Candidates:
- **(a) Fixed length across all cells** (e.g., all chains = N events): Maximizes comparability. Requires a single N agreed upon pre-registration.
- **(b) Fixed length per cell, varying across cells**: Allows domain-appropriate granularity. Requires pre-registering N per cell.
- **(c) Variable length, bounded (e.g., 3-15 events)**: Maximum flexibility. Requires pre-registering the bound and how T selects length.

[REQUIRES SIGN-OFF — Q5]: **Granularity for CS:GO.** The CS2 demo file is tick-rate 128 (128 events/second). Candidates:
- **(a) Round-level** (current default: ~300 events per map): Highest-level strategic decisions only.
- **(b) Clutch-level** (subset of rounds marked as high-stakes): Semantically richer but requires additional filtering logic in T.
- **(c) Tick-sampled** (every N ticks, e.g., N=256 ≈ 2 seconds): Most granular, ~6,750 events/map.

[REQUIRES SIGN-OFF — Q6]: **Granularity for NBA.** Play-by-play has ~220 rows per game. Candidates:
- **(a) Possession-level** (group plays by possession): ~85 possessions per game × 2-3 events each = ~200 events/game.
- **(b) Play-level** (each row = one event): ~220 events/game. Simplest mapping.
- **(c) Clutch + non-clutch stratified**: Separate sampling of high-leverage vs routine plays.

[REQUIRES SIGN-OFF — Q7]: **Continuous-state handling for Rocket League.** The Rocket League physics engine produces continuous positional data (60Hz). Candidates:
- **(a) Hit-level** (current default: ~150-300 hits per 5-min game): Discretizes continuous state to ball contact events.
- **(b) Possession-level** (group hits by continuous ball possession): ~40-80 possessions per game.
- **(c) Boost-event-enriched hit-level**: Adds boost pickups/use as interleaved events with hits.

[REQUIRES SIGN-OFF — Q8]: **Hearthstone granularity.** Candidates:
- **(a) Per-action** (current default): Each card play, attack, hero power = one event. ~5-8 events/turn, ~80 events/game.
- **(b) Per-turn**: One event per player turn. ~15-20 events/game. Simpler chains, less information.

---

## 7. Chain Construction

### 7.1 Interface

`ChainBuilder` defined in `src/interfaces/chain_builder.py`. Stub only — raises `NotImplementedError`.

### 7.2 Out of Scope for Infrastructure Build

Chain construction parameters (length, overlap policy, sampling strategy) are not pre-registered and must not be defaulted in code. The `DefaultChainBuilder` stub enforces this.

---

## 8. Evaluation Harness

### 8.1 Gate 2 Filter

Before evaluation, chains pass through Gate 2: at least 50% of events in the chain must be actionable under the v1.1 ACTIONABLE_TYPES whitelist.

**v1.1 ACTIONABLE_TYPES whitelist** (see `src/harness/actionables.py`):
- Core types: engage_decision, position_commit, resource_gain/spend/budget, rotation_commit, zone_enter/exit, ability_use, item_use, target_select, team_coordinate, objective_contest/capture/abandon, timing_commit, draft_pick/ban, strategy_adapt, risk_accept/reject, concede, delay_action, force_action

**v1.1 Amendments:**
- `resource_budget` added (was absent in v1.0)
- `phase_` prefix stripped from event_type before comparison

### 8.2 Scoring

Binary: correct (1) / incorrect (0) / abstain (-1). Abstains excluded from McNemar input by default.

### 8.3 Cell Runner

`CellRunner` in `src/harness/cell_runner.py` orchestrates per-cell runs:
1. Translate event streams to chains via T
2. Gate 2 filter
3. Score chains against model responses
4. McNemar test per cell
5. Variance analysis per cell
6. Aggregate report

---

## 9. Pilot Validation

Pilot harness (`src/pilot/validator.py`) runs 50-100 sample chains per cell through the full pipeline using `MockT` (deterministic sliding-window heuristic, not a real T). Validates:
- Event stream generation
- Gate 2 retention rate (>= 50% floor)
- Chain length and actionable-fraction distributions
- Event type distribution sanity

**Pilot status as of infrastructure build:** ALL FIVE CELLS PASS with mock data.
- Fortnite: 200 streams, 24,000 events, 8,000 chains (100% retention)
- NBA: 300 streams, 55,200 events, 18,420 chains (100% retention)
- CS:GO: 150 streams, 45,000 events, 15,000 chains (100% retention)
- Rocket League: 250 streams, 50,000 events, 16,750 chains (100% retention)
- Hearthstone: 300 streams, 23,100 events, 7,740 chains (100% retention)

Note: 100% retention with mock data is expected because MockT only selects actionable events. Real T may have lower retention.

---

## 10. Pre-Registration Sign-Off Required

The following decisions are **BLOCKING** on pre-registration. They must be signed by both authors before any T implementation or evaluation run.

| # | Question | Candidates | Current Default | Blocking? |
|---|----------|-----------|-----------------|-----------|
| Q1 | Baseline/intervention prompt structure | (a) same call, (b) two calls | Not chosen | YES |
| Q2 | Bonferroni divisor | (a) 5, (b) 1, (c) mixed | 5 (in config) | YES |
| Q3 | Is n=1200/cell sufficient? | Yes / No / Need power analysis | — | YES |
| Q4 | Chain length consistency | (a) fixed global, (b) fixed per-cell, (c) variable bounded | Not chosen | YES |
| Q5 | CS:GO granularity | (a) round-level, (b) clutch-level, (c) tick-sampled | round-level | YES |
| Q6 | NBA granularity | (a) possession, (b) play-level, (c) stratified | play-level | YES |
| Q7 | Rocket League state handling | (a) hit-level, (b) possession-level, (c) boost-enriched | hit-level | YES |
| Q8 | Hearthstone granularity | (a) per-action, (b) per-turn | per-action | YES |

---

## 11. References

- v3 Experiment: safiqsindha/Project-Ditto-V3 (Chess & Checkers)
- v4 Experiment: safiqsindha/Project-Ditto-V4 (single-cell methodology characterization)
- McNemar (1947): "Note on the Sampling Error of the Difference Between Correlated Proportions"
- Cohen (1988): "Statistical Power Analysis for the Behavioral Sciences" (h effect size)
- nba_api: github.com/swar/nba_api
- awpy: github.com/pnxenopoulos/awpy
- BallChasing API: ballchasing.com/api
- HearthSim: github.com/HearthSim
