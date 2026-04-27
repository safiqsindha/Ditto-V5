# v5 End-of-Day Status

**Date:** 2026-04-27  
**Session type:** Infrastructure build — bounded autonomous execution  
**Stop condition reached:** All in-scope tasks completed (the good case)

---

## Summary

All six in-scope infrastructure tasks completed. Pilot validation passes on all five cells with mock data. No Haiku API calls made. T implementations are stubs. Chain construction is stubbed. SPEC has all sign-off questions surfaced. Ready for your review.

---

## What's Done

### Scaffolding
- `v5/` directory tree created, matching v3/v4 pattern
- `src/cells/{fortnite,nba,csgo,rocket_league,hearthstone}/` — one directory per cell
- `src/harness/`, `src/interfaces/`, `src/pilot/`, `src/common/`
- `data/raw/`, `data/processed/`, `data/events/` — one per-domain subdirectory each
- `config/cells.yaml`, `config/harness.yaml`
- `requirements.txt`

### Common Layer
- `src/common/schema.py` — `GameEvent`, `EventStream`, `ChainCandidate` dataclasses
  - `phase_` prefix stripping in `GameEvent.__post_init__` (v1.1 amendment)
  - JSONL serialization/deserialization on `EventStream`
- `src/common/config.py` — `CellConfig`, `HarnessConfig`, YAML-backed loaders

### Statistical Harness
- `src/harness/actionables.py` — ACTIONABLE_TYPES whitelist (v1.1), Gate 2 logic, retention rate
- `src/harness/mcnemar.py` — McNemar's test with continuity correction + Bonferroni + bootstrap CI + effect size
- `src/harness/scoring.py` — chain scoring, binary vector extraction
- `src/harness/variance.py` — bootstrap CIs, post-hoc power, MDE
- `src/harness/cell_runner.py` — five-cell orchestrator; T is injected dependency

### Interface Stubs
- `src/interfaces/translation.py` — `TranslationFunction` ABC + five domain stubs (all raise `NotImplementedError`)
- `src/interfaces/chain_builder.py` — `ChainBuilder` ABC + `DefaultChainBuilder` stub

### Data Acquisition Pipelines (all five)

| Cell | Pipeline | Extractor | Mock Data | Real Fetch |
|------|----------|-----------|-----------|------------|
| Fortnite | `pipeline.py` | `extractor.py` | 200 matches × 120 ev | xNocken/replay-downloader + FortniteReplayDecompressor |
| NBA | `pipeline.py` | `extractor.py` | 300 games × 180 ev | nba_api PlayByPlayV3 |
| CS:GO | `pipeline.py` | `extractor.py` | 150 maps × 300 ev | HLTV demos + awpy |
| Rocket League | `pipeline.py` | `extractor.py` | 250 replays × 200 ev | BallChasing API + carball |
| Hearthstone | `pipeline.py` | `extractor.py` | 300 games × 77 ev | HSReplay API + hslog |

### Pilot Validation Harness
- `src/pilot/mock_t.py` — `MockT`: deterministic sliding-window translation function
- `src/pilot/validator.py` — `PilotValidator`: Gate 2 check, distributions, sample inspection
- `run_pilot.py` — CLI entry point: `python -m v5.run_pilot`

### Pilot Validation Results (Mock Data)

| Cell | Streams | Events | Chains | Retention | Gate 2 |
|------|---------|--------|--------|-----------|--------|
| fortnite | 200 | 24,000 | 8,000 | 100% | PASS |
| nba | 300 | 55,200 | 18,420 | 100% | PASS |
| csgo | 150 | 45,000 | 15,000 | 100% | PASS |
| rocket_league | 250 | 50,000 | 16,750 | 100% | PASS |
| hearthstone | 300 | 23,100 | 7,740 | 100% | PASS |

**Note:** 100% mock retention is expected. MockT only emits windows containing actionable events. Real T retention will be lower — Gate 2's 50% floor is the binding constraint for real data.

### Documentation
- `v5/BUILD_PLAN.md` — sequenced build plan with dependency graph (written first, before any code)
- `v5/SPEC.md` — draft specification with 8 [REQUIRES SIGN-OFF] questions
- `v5/DECISION_LOG.md` — 13 decisions logged with default/alternative/reversibility framing
- `v5/STATUS.md` — this file

---

## What's Pending (Out of Scope for Today — Do Not Build)

| Item | Why Blocked | What's Needed |
|------|-------------|---------------|
| T implementations (all 5) | Requires both-author review | SPEC sign-off, then T design session |
| Chain construction | Depends on chain-length pre-registration | Answer Q4 in SPEC |
| Real data acquisition | No API credentials in session; pipelines are ready | Credentials + network access |
| Haiku evaluation runs | SPEC not pre-registered | SPEC sign-off |
| Fortnite Mew work | Out of scope per instructions | Separate scope |

---

## Decisions Needing Your Review Before SPEC Sign-Off

See `DECISION_LOG.md` for full framing. Quick summary:

| Decision | What I defaulted | Override? |
|----------|-----------------|-----------|
| D-0 | Built from prompt description (v3/v4 inaccessible) | Compare against actual v3/v4 harness code |
| D-1 | Fortnite: 200 matches | Adjust if T extraction rate differs |
| D-2 | NBA: 300 games, 2023-24 only | Confirm season scope |
| D-3 | CS:GO: 150 maps, 3 tournaments | Confirm tournament tier list |
| D-4 | RL: 250 replays, WC/Major/Regional split | Confirm BallChasing filter string |
| D-5 | HS: 300 Legend games, top-100 oversampled | Confirm Legend as right rank tier |
| D-6 | Time range: 2024 calendar year all cells | Confirm no sparse-data issues |
| D-7 | CS:GO at round-level granularity | BLOCKING — see SPEC Q5 |
| D-8 | Carball primary / rrrocket fallback | Tooling choice, no sign-off needed |
| D-9 | HS per-action granularity | BLOCKING — see SPEC Q8 |
| D-10 | NBA: play-by-play only (no spatial tracking) | Note limitation in final SPEC |
| D-11 | ACTIONABLE_TYPES v1.1 adopted as-is | Compare to v4 implementation |
| D-12 | No chain construction defaults set | BLOCKING |
| D-13 | Mock data sizing per cell | No sign-off needed |

---

## SPEC Sign-Off Blockers

Eight questions in `SPEC.md` require both-author pre-registration before T can be built:

1. **Q1**: Baseline/intervention prompt structure (same call vs two calls?)
2. **Q2**: Bonferroni divisor (5 vs 1 vs mixed?) — **most consequential for statistical design**
3. **Q3**: Is n=1,200/cell adequate given your observed v3 effect size?
4. **Q4**: Chain length consistency (fixed global / fixed per-cell / variable bounded?)
5. **Q5**: CS:GO granularity (round-level / clutch-level / tick-sampled?) — **BLOCKING on T**
6. **Q6**: NBA granularity (possession / play-level / stratified?) — **BLOCKING on T**
7. **Q7**: Rocket League state handling (hit-level / possession / boost-enriched?) — **BLOCKING on T**
8. **Q8**: Hearthstone granularity (per-action / per-turn?) — **BLOCKING on T**

---

## Fortnite Pipeline: User Note

During the session, the user flagged that FortniteTracker (TRN) API and Replay.io provide aggregated stats (placement, eliminations) rather than raw spatial telemetry. The current pipeline (xNocken/replay-downloader + FortniteReplayDecompressor) extracts full replay data including spatial positions.

**User recommendation:** Stick with current pipeline + use a burner Epic account + proxy/rate-limiter. User offered a Node.js async queue snippet for handling 200 matches without triggering rate limits.

**Action needed:** Add the Node.js queue snippet to `src/cells/fortnite/` once provided. This is a tooling addition, not a methodological decision.

---

## How to Run the Pilot

```bash
# From repo root
cd /path/to/Ditto-V5
python -m v5.run_pilot

# Or with specific cells only
python -m v5.run_pilot --cells fortnite nba

# Save report
python -m v5.run_pilot --output v5/RESULTS/pilot_report_mock.json
```

---

## Next Steps (for your return)

1. **Review DECISION_LOG.md** — override any defaults you disagree with
2. **Answer SPEC Q1-Q8** — these are the blocking pre-registration decisions
3. **Sign SPEC** — both authors
4. **Then:** Build T implementations (both-author session required per v6-discipline)
5. **Then:** Run real data acquisition with credentials
6. **Then:** Run Haiku evaluation
