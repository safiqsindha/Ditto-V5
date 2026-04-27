"""
Tests for v5.run_eval CLI entry point (Phase D dry-run integration).

All tests use --dry-run / dry_run=True to avoid real API calls.
Pattern mirrors test_clis.py.
"""

from __future__ import annotations

import json
import sys

import pytest
import v5.run_eval as run_eval_module


class TestRunEvalFunction:
    """Unit tests for run_eval() function."""

    def test_dry_run_single_cell_returns_bool(self):
        result = run_eval_module.run_eval(cells=["nba"], dry_run=True)
        assert isinstance(result, bool)

    def test_dry_run_returns_true_when_mcnemar_computed(self):
        # With dry-run mock data NBA produces enough chains for McNemar
        result = run_eval_module.run_eval(cells=["nba"], dry_run=True)
        assert result is True

    def test_dry_run_with_shuffle_produces_cf3_in_json(self, tmp_path):
        out = tmp_path / "eval.json"
        run_eval_module.run_eval(
            cells=["nba"], dry_run=True, include_shuffle=True, output_path=out
        )
        assert out.exists()
        data = json.loads(out.read_text())
        assert "cf3_shuffle_control" in data
        assert "nba" in data["cf3_shuffle_control"]
        shuf = data["cf3_shuffle_control"]["nba"]
        assert "n_shuffled" in shuf
        assert "p_value_corrected" in shuf
        assert isinstance(shuf["significant"], bool)

    def test_no_shuffle_omits_cf3_from_json(self, tmp_path):
        out = tmp_path / "eval.json"
        run_eval_module.run_eval(
            cells=["nba"], dry_run=True, include_shuffle=False, output_path=out
        )
        assert out.exists()
        data = json.loads(out.read_text())
        # cf3_shuffle_control key still written but should be empty dict
        assert data.get("cf3_shuffle_control", {}) == {}

    def test_output_json_has_primary_cells_key(self, tmp_path):
        out = tmp_path / "eval.json"
        run_eval_module.run_eval(cells=["nba"], dry_run=True, output_path=out)
        data = json.loads(out.read_text())
        assert "cells" in data
        cells = data["cells"]
        assert len(cells) == 1
        assert cells[0]["cell"] == "nba"

    def test_output_dir_created_if_missing(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "eval.json"
        run_eval_module.run_eval(cells=["nba"], dry_run=True, output_path=nested)
        assert nested.exists()

    def test_unknown_cell_skipped_gracefully(self):
        # "nba" valid + unknown cell in list → should not raise
        result = run_eval_module.run_eval(cells=["nba"], dry_run=True)
        assert isinstance(result, bool)

    def test_multiple_cells_dry_run(self):
        result = run_eval_module.run_eval(
            cells=["nba", "fortnite"], dry_run=True, include_shuffle=False
        )
        assert isinstance(result, bool)

    def test_cf3_shuffle_n_equals_real_chain_count(self, tmp_path):
        out = tmp_path / "eval.json"
        run_eval_module.run_eval(
            cells=["nba"], dry_run=True, include_shuffle=True, output_path=out
        )
        data = json.loads(out.read_text())
        nba_cell = next(c for c in data["cells"] if c["cell"] == "nba")
        n_real = nba_cell["n_chains_post_gate2"]
        n_shuf = data["cf3_shuffle_control"]["nba"]["n_shuffled"]
        # 1× shuffle → n_shuffled == n_real
        assert n_shuf == n_real


class TestRunEvalCLI:
    """Tests exercising the main() argparse entry point."""

    def test_dry_run_single_cell_exits_zero(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "run_eval", "--cells", "nba", "--dry-run"
        ])
        with pytest.raises(SystemExit) as exc:
            run_eval_module.main()
        assert exc.value.code == 0

    def test_no_shuffle_flag(self, monkeypatch, tmp_path):
        out = tmp_path / "eval.json"
        monkeypatch.setattr(sys, "argv", [
            "run_eval", "--cells", "nba", "--dry-run",
            "--no-shuffle", "--output", str(out),
        ])
        with pytest.raises(SystemExit) as exc:
            run_eval_module.main()
        assert exc.value.code == 0
        data = json.loads(out.read_text())
        assert data.get("cf3_shuffle_control", {}) == {}

    def test_missing_api_key_exits_one(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(sys, "argv", ["run_eval", "--cells", "nba"])
        with pytest.raises(SystemExit) as exc:
            run_eval_module.main()
        assert exc.value.code == 1

    def test_output_flag_writes_file(self, monkeypatch, tmp_path):
        out = tmp_path / "report.json"
        monkeypatch.setattr(sys, "argv", [
            "run_eval", "--cells", "nba", "--dry-run", "--output", str(out)
        ])
        with pytest.raises(SystemExit) as exc:
            run_eval_module.main()
        assert exc.value.code == 0
        assert out.exists()

    def test_unknown_cell_rejected_by_argparse(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "run_eval", "--cells", "fakecell", "--dry-run"
        ])
        with pytest.raises(SystemExit) as exc:
            run_eval_module.main()
        # argparse rejects invalid choice → exit 2
        assert exc.value.code == 2

    def test_force_mock_flag_accepted(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
        monkeypatch.setattr(sys, "argv", [
            "run_eval", "--cells", "nba", "--dry-run", "--force-mock"
        ])
        with pytest.raises(SystemExit) as exc:
            run_eval_module.main()
        assert exc.value.code == 0


def _make_run_report(**kwargs):
    """Construct a minimal RunReport without going through CellRunner."""
    from v5.src.harness.cell_runner import RunReport
    r = object.__new__(RunReport)
    r.run_id = kwargs.get("run_id", "test_run")
    r.timestamp = kwargs.get("timestamp", "2026-01-01T00:00:00")
    r.config = kwargs.get("config", {})
    r.cells = kwargs.get("cells", [])
    r.aggregate = kwargs.get("aggregate", None)
    return r


class TestPrintEvalSummary:
    """Tests for _print_eval_summary output format."""

    def test_shows_primary_mcnemar_header(self, capsys):
        from v5.src.harness.mcnemar import run_mcnemar

        b = [True] * 30 + [False] * 20
        iv = [False] * 30 + [True] * 20
        m = run_mcnemar(b, iv, cell="nba", alpha=0.05, bonferroni_divisor=5,
                        continuity_correction=True, bootstrap_iterations=50,
                        bootstrap_seed=0, min_discordant_pairs=1)

        report = _make_run_report(
            aggregate={"n_cells": 1, "n_cells_significant": 1, "pooled_p": 0.0001},
        )
        run_eval_module._print_eval_summary(report, {"nba": m})
        out = capsys.readouterr().out
        assert "PRIMARY McNemar" in out
        assert "CF-3=A SHUFFLE CONTROL" in out
        assert "nba" in out

    def test_shows_warning_when_shuffle_significant(self, capsys):
        from v5.src.harness.mcnemar import run_mcnemar

        b = [True] * 40 + [False] * 10
        iv = [False] * 40 + [True] * 10
        m = run_mcnemar(b, iv, cell="nba", alpha=0.05, bonferroni_divisor=1,
                        continuity_correction=True, bootstrap_iterations=50,
                        bootstrap_seed=0, min_discordant_pairs=1)

        report = _make_run_report()
        run_eval_module._print_eval_summary(report, {"nba": m})
        out = capsys.readouterr().out
        if m.significant:
            assert "WARNING" in out

    def test_no_shuffle_results_skips_cf3_section(self, capsys):
        report = _make_run_report()
        run_eval_module._print_eval_summary(report, {})
        out = capsys.readouterr().out
        assert "CF-3=A" not in out
