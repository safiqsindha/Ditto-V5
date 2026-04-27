"""
Cell runner for v5 — orchestrates parallel cell evaluation.

Accepts a TranslationFunction (T) for each cell and runs the full
McNemar pipeline: event stream → chains (via T) → Gate 2 filter →
scoring → McNemar test → cell-level + aggregate report.

T is injected as a pluggable dependency. Until T implementations
are built and pre-registered, use the MockT from src/pilot/mock_t.py.

NOTE: No real Haiku API calls are made in this module. The `evaluate_chains`
method is a stub that requires a real ModelEvaluator to be injected.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..common.schema import ChainCandidate, EventStream, GameEvent
from ..common.config import HarnessConfig, load_harness_config
from ..interfaces.translation import TranslationFunction
from .actionables import compute_retention_rate, gate2_check
from .mcnemar import McnemarResult, aggregate_results, run_mcnemar
from .scoring import ChainScore, extract_binary_vectors, score_batch
from .variance import mcnemar_power, minimum_detectable_effect, variance_summary


@dataclass
class CellResult:
    """Complete result for one cell's evaluation run."""
    cell: str
    n_events_total: int
    n_chains_pre_gate2: int
    n_chains_post_gate2: int
    retention_rate: float
    gate2_pass: bool
    mcnemar: Optional[McnemarResult]
    variance_baseline: Optional[dict]
    variance_intervention: Optional[dict]
    power: Optional[float]
    mde: Optional[float]
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.mcnemar:
            d["mcnemar_summary"] = self.mcnemar.summary()
        return d


@dataclass
class RunReport:
    """Aggregate report across all cells."""
    run_id: str
    timestamp: str
    config: dict
    cells: List[CellResult]
    aggregate: dict

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "config": self.config,
            "cells": [c.to_dict() for c in self.cells],
            "aggregate": self.aggregate,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


class CellRunner:
    """
    Orchestrates evaluation across all five v5 cells.

    Usage
    -----
    runner = CellRunner(config=harness_config)
    runner.register_cell("fortnite", translation_fn=MyFortniteT())
    runner.register_cell("nba", translation_fn=MockT(cell="nba"))
    ...
    report = runner.run(event_streams_by_cell)
    """

    def __init__(self, config: Optional[HarnessConfig] = None):
        self.config = config or load_harness_config()
        self._cell_translations: Dict[str, TranslationFunction] = {}

    def register_cell(self, cell: str, translation_fn: TranslationFunction) -> None:
        self._cell_translations[cell] = translation_fn

    def run(
        self,
        event_streams: Dict[str, List[EventStream]],
        baseline_responses: Optional[Dict[str, List[str]]] = None,
        intervention_responses: Optional[Dict[str, List[str]]] = None,
        ground_truths: Optional[Dict[str, List[str]]] = None,
    ) -> RunReport:
        """
        Run the full pipeline for all registered cells.

        Parameters
        ----------
        event_streams         : {cell: [EventStream, ...]}
        baseline_responses    : {cell: [model_response_str, ...]}  (per chain)
        intervention_responses: {cell: [model_response_str, ...]}
        ground_truths         : {cell: [ground_truth_str, ...]}

        When baseline/intervention/ground_truth are None, scoring is skipped
        (useful for infrastructure validation without real model calls).
        """
        import datetime
        run_id = f"v5_run_{int(time.time())}"
        ts = datetime.datetime.utcnow().isoformat() + "Z"

        cell_results = []
        mcnemar_results = []

        for cell in self.config.cells:
            streams = event_streams.get(cell, [])
            t_fn = self._cell_translations.get(cell)

            result = self._run_cell(
                cell=cell,
                streams=streams,
                translation_fn=t_fn,
                baseline_responses=(baseline_responses or {}).get(cell),
                intervention_responses=(intervention_responses or {}).get(cell),
                ground_truths=(ground_truths or {}).get(cell),
            )
            cell_results.append(result)
            if result.mcnemar:
                mcnemar_results.append(result.mcnemar)

        agg = aggregate_results(mcnemar_results) if mcnemar_results else {}

        return RunReport(
            run_id=run_id,
            timestamp=ts,
            config=asdict(self.config),
            cells=cell_results,
            aggregate=agg,
        )

    def _run_cell(
        self,
        cell: str,
        streams: List[EventStream],
        translation_fn: Optional[TranslationFunction],
        baseline_responses: Optional[List[str]],
        intervention_responses: Optional[List[str]],
        ground_truths: Optional[List[str]],
    ) -> CellResult:
        errors = []
        n_events = sum(len(s) for s in streams)

        # Step 1: Translate event streams to chain candidates via T
        chains: List[ChainCandidate] = []
        if translation_fn is None:
            errors.append(f"No TranslationFunction registered for cell '{cell}'")
        else:
            try:
                for stream in streams:
                    chains.extend(translation_fn.translate(stream))
            except NotImplementedError:
                errors.append(f"T not implemented for cell '{cell}' (stub)")
            except Exception as e:
                errors.append(f"T raised exception for cell '{cell}': {e}")

        n_pre_gate2 = len(chains)

        # Step 2: Gate 2 filter
        retention_info = compute_retention_rate(
            chains, floor=self.config.gate2_retention_floor
        )
        chains_passed = [c for c in chains if c.is_actionable]
        n_post_gate2 = len(chains_passed)

        # Step 3: Scoring (skipped if no model responses provided)
        mcnemar_result = None
        var_baseline = None
        var_intervention = None
        power = None
        mde_val = None

        if baseline_responses and intervention_responses and ground_truths:
            n = min(len(chains_passed), len(baseline_responses),
                    len(intervention_responses), len(ground_truths))
            chains_scored = chains_passed[:n]
            b_scores = score_batch(chains_scored, ground_truths[:n], baseline_responses[:n])
            i_scores = score_batch(chains_scored, ground_truths[:n], intervention_responses[:n])

            b_vec, i_vec = extract_binary_vectors(b_scores, i_scores)
            var_baseline = variance_summary([s.correct or False for s in b_scores], cell)
            var_intervention = variance_summary([s.correct or False for s in i_scores], cell)

            mcnemar_result = run_mcnemar(
                baseline_correct=b_vec,
                intervention_correct=i_vec,
                cell=cell,
                alpha=self.config.alpha,
                bonferroni_divisor=self.config.bonferroni_divisor,
                continuity_correction=self.config.continuity_correction,
                bootstrap_iterations=self.config.bootstrap_iterations,
                bootstrap_seed=self.config.bootstrap_seed,
                min_discordant_pairs=self.config.min_discordant_pairs,
            )
            power = mcnemar_power(
                mcnemar_result.b, mcnemar_result.c,
                alpha=self.config.alpha,
                bonferroni_divisor=self.config.bonferroni_divisor,
            )
        else:
            mde_val = minimum_detectable_effect(
                n_chains=n_post_gate2,
                alpha=self.config.alpha,
                bonferroni_divisor=self.config.bonferroni_divisor,
            )

        return CellResult(
            cell=cell,
            n_events_total=n_events,
            n_chains_pre_gate2=n_pre_gate2,
            n_chains_post_gate2=n_post_gate2,
            retention_rate=retention_info["retention_rate"],
            gate2_pass=retention_info["gate2_pass"],
            mcnemar=mcnemar_result,
            variance_baseline=var_baseline,
            variance_intervention=var_intervention,
            power=power,
            mde=mde_val,
            errors=errors,
        )
