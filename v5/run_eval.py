"""
v5 Phase D evaluation entry point.

Runs the full evaluation pipeline across all five cells:
  real data (or mock) → T → Gate 2 → PromptBuilder → Haiku API → McNemar → report

Requires ANTHROPIC_API_KEY in environment for real evaluation.
Use --dry-run for a zero-cost integration check with mock API responses.

Usage
-----
# Dry run (no API spend, deterministic responses):
  python -m v5.run_eval --dry-run --output v5/RESULTS/eval_dry_run.json

# Real evaluation (requires ANTHROPIC_API_KEY, ~$15 for 1,200 chains/cell × 5 cells):
  python -m v5.run_eval --output v5/RESULTS/eval_phase_d.json

# Single cell only:
  python -m v5.run_eval --cells nba --dry-run

# Force mock data even if credentials are present:
  python -m v5.run_eval --force-mock --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("v5.run_eval")

ALL_CELLS = ["fortnite", "nba", "csgo", "rocket_league", "hearthstone"]


def run_eval(
    cells: list[str],
    output_path: Path | None = None,
    dry_run: bool = False,
    force_mock: bool = False,
) -> bool:
    from v5.src.cells.csgo.pipeline import CSGOPipeline
    from v5.src.cells.fortnite.pipeline import FortnitePipeline
    from v5.src.cells.hearthstone.pipeline import HearthstonePipeline
    from v5.src.cells.nba.pipeline import NBAPipeline
    from v5.src.cells.rocket_league.pipeline import RocketLeaguePipeline
    from v5.src.common.config import load_cell_configs, load_harness_config
    from v5.src.harness.cell_runner import CellRunner
    from v5.src.harness.model_evaluator import HAIKU_MODEL, ModelEvaluator
    from v5.src.harness.prompts import PER_CELL_PROMPT_BUILDERS
    from v5.src.interfaces.chain_builder import FixedPerCellChainBuilder
    from v5.src.interfaces.translation import DOMAIN_T_STUBS

    cell_configs = load_cell_configs()
    harness_config = load_harness_config()

    pipeline_map = {
        "fortnite": FortnitePipeline,
        "nba": NBAPipeline,
        "csgo": CSGOPipeline,
        "rocket_league": RocketLeaguePipeline,
        "hearthstone": HearthstonePipeline,
    }

    # Per-cell N values from harness.yaml
    chain_lengths = {
        "fortnite": 8, "nba": 5, "csgo": 10,
        "rocket_league": 12, "hearthstone": 6,
    }

    chain_builder = FixedPerCellChainBuilder(per_cell_chain_length=chain_lengths)
    runner = CellRunner(config=harness_config, chain_builder=chain_builder)
    evaluator = ModelEvaluator(
        model=HAIKU_MODEL,
        dry_run=dry_run,
        allowed_predictions=["yes", "no"],
    )

    streams_by_cell: dict = {}
    baseline_responses: dict = {}
    intervention_responses: dict = {}
    ground_truths: dict = {}

    for cell in cells:
        if cell not in pipeline_map:
            logger.warning(f"Unknown cell '{cell}', skipping")
            continue

        config = cell_configs.get(cell)
        if config is None:
            logger.error(f"No config for cell '{cell}'")
            continue

        logger.info(f"[{cell}] Fetching event streams...")
        pipeline = pipeline_map[cell](config=config)
        streams = pipeline.run(force_mock=force_mock or dry_run)
        streams_by_cell[cell] = streams
        logger.info(f"[{cell}] {len(streams)} streams, "
                    f"{sum(len(s) for s in streams)} events")

        # Register real T
        t_fn = DOMAIN_T_STUBS.get(cell)
        if t_fn is None:
            logger.error(f"No T for cell '{cell}'")
            continue
        runner.register_cell(cell, t_fn)

        # Translate → Gate 2 → build prompts
        logger.info(f"[{cell}] Translating streams to chains...")
        candidates = []
        for stream in streams:
            candidates.extend(t_fn.translate(stream))
        chains = chain_builder.build_from_candidates(candidates, cell=cell)

        from v5.src.harness.actionables import compute_retention_rate
        retention = compute_retention_rate(chains, floor=harness_config.gate2_retention_floor)
        chains_passed = [c for c in chains if c.is_actionable]
        logger.info(
            f"[{cell}] {len(chains)} chains pre-Gate2 → "
            f"{len(chains_passed)} post-Gate2 "
            f"(retention {retention['retention_rate']:.1%})"
        )

        if not chains_passed:
            logger.warning(f"[{cell}] No chains passed Gate 2, skipping evaluation")
            continue

        builder_cls = PER_CELL_PROMPT_BUILDERS.get(cell)
        if builder_cls is None:
            logger.error(f"No PromptBuilder for cell '{cell}'")
            continue
        prompt_builder = builder_cls()
        pairs = [prompt_builder.build(c) for c in chains_passed]

        logger.info(
            f"[{cell}] Evaluating {len(pairs)} prompt pairs "
            f"({'dry-run' if dry_run else HAIKU_MODEL})..."
        )
        _, b_responses, i_responses = evaluator.evaluate_pairs(pairs)
        baseline_responses[cell] = b_responses
        intervention_responses[cell] = i_responses
        ground_truths[cell] = ["yes"] * len(chains_passed)

    logger.info("Running McNemar analysis across all cells...")
    report = runner.run(
        streams_by_cell,
        baseline_responses=baseline_responses,
        intervention_responses=intervention_responses,
        ground_truths=ground_truths,
    )

    _print_eval_summary(report)

    if output_path:
        report.save(output_path)
        logger.info(f"Report saved to {output_path}")

    # Return True only if all cells ran McNemar (even non-significant results are OK)
    return all(r.mcnemar is not None for r in report.cells)


def _print_eval_summary(report) -> None:
    print(f"\n{'='*70}")
    print(f"v5 PHASE D EVALUATION — {report.run_id}")
    print(f"{'='*70}")
    for r in report.cells:
        if r.mcnemar:
            m = r.mcnemar
            sig = "**SIGNIFICANT**" if m.significant else "not significant"
            print(
                f"  [{r.cell:<14}] chains={r.n_chains_post_gate2:>5} "
                f"b={m.b:>4} c={m.c:>4} "
                f"p_corr={m.p_value_corrected:.4f} h={m.effect_size_h:+.4f} "
                f"→ {sig}"
            )
        else:
            errs = "; ".join(r.errors[:2]) if r.errors else "no responses"
            print(f"  [{r.cell:<14}] SKIPPED ({errs})")

    agg = report.aggregate
    if agg:
        print(f"\n  Pooled: n_cells={agg.get('n_cells',0)} "
              f"significant={agg.get('n_cells_significant',0)} "
              f"pooled_p={agg.get('pooled_p', 1.0):.4f}")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description="v5 Phase D Evaluation")
    parser.add_argument(
        "--cells", nargs="+", default=ALL_CELLS,
        choices=ALL_CELLS, help="Cells to evaluate"
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Path to save JSON report"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Use mock API responses (no ANTHROPIC_API_KEY needed, no cost)"
    )
    parser.add_argument(
        "--force-mock", action="store_true",
        help="Use mock event data even if real credentials are present"
    )
    args = parser.parse_args()

    if not args.dry_run:
        import os
        if not os.getenv("ANTHROPIC_API_KEY"):
            logger.error(
                "ANTHROPIC_API_KEY not set. "
                "Use --dry-run for a zero-cost integration check, "
                "or set the env var for real evaluation."
            )
            sys.exit(1)

    success = run_eval(
        cells=args.cells,
        output_path=args.output,
        dry_run=args.dry_run,
        force_mock=args.force_mock,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
