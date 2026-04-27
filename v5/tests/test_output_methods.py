"""
Tests for output/print methods that aren't covered by CLI tests:
- CellPilotReport.print_summary
- PilotReport.print_summary
- McnemarResult.summary
- BasePipeline.load_saved_streams + _clear_events_dir
"""

from __future__ import annotations

import pytest
from v5.src.cells.fortnite.pipeline import FortnitePipeline
from v5.src.common.config import load_cell_configs
from v5.src.common.schema import EventStream, GameEvent
from v5.src.harness.mcnemar import run_mcnemar
from v5.src.pilot.mock_t import MockT
from v5.src.pilot.validator import PilotValidator


def _stream(cell: str, n: int = 50, seed: int = 0) -> EventStream:
    s = EventStream(game_id=f"g{seed}", cell=cell)
    for i in range(n):
        s.append(GameEvent(
            timestamp=float(i), event_type="engage_decision",
            actor=f"p{i % 3}", location_context={}, raw_data_blob={},
            cell=cell, game_id=f"g{seed}", sequence_idx=i,
        ))
    return s


class TestPilotReportPrint:
    def test_cell_print_summary(self, capsys):
        validator = PilotValidator()
        validator.register_cell("nba", MockT(cell="nba"))
        report = validator.run({"nba": [_stream("nba", n=50, seed=i) for i in range(3)]})
        report.cells[0].print_summary()
        out = capsys.readouterr().out
        assert "[NBA]" in out
        assert "Pilot Validation" in out
        assert "Streams:" in out
        assert "Top event types:" in out

    def test_aggregate_print_summary(self, capsys):
        validator = PilotValidator()
        validator.register_cell("nba", MockT(cell="nba"))
        validator.register_cell("csgo", MockT(cell="csgo"))
        streams = {
            "nba": [_stream("nba", seed=i) for i in range(2)],
            "csgo": [_stream("csgo", seed=i) for i in range(2)],
        }
        report = validator.run(streams)
        report.print_summary()
        out = capsys.readouterr().out
        assert "AGGREGATE PILOT RESULT" in out

    def test_print_summary_with_warnings_and_errors(self, capsys):
        from v5.src.pilot.validator import CellPilotReport
        report = CellPilotReport(
            cell="nba", n_streams=1, n_events_total=10,
            n_chains_raw=2, n_chains_post_gate2=1, retention_rate=0.50,
            gate2_floor=0.50, gate2_pass=True,
            chain_length_mean=5, chain_length_min=5, chain_length_max=5,
            chain_length_median=5, actionable_frac_mean=0.6,
            actionable_frac_min=0.5, actionable_frac_max=0.7,
            event_type_distribution={"engage_decision": 5},
            sample_chain_summaries=[],
            warnings=["test warn"], errors=["test err"],
        )
        report.print_summary()
        out = capsys.readouterr().out
        assert "WARN: test warn" in out
        assert "ERROR: test err" in out


class TestMcnemarSummary:
    def test_summary_string(self):
        result = run_mcnemar(
            baseline_correct=[True] * 30 + [False] * 70,
            intervention_correct=[True] * 60 + [False] * 40,
            cell="nba",
            bootstrap_iterations=50,
        )
        s = result.summary()
        assert "[nba]" in s
        assert "McNemar" in s
        assert "p=" in s
        assert "h=" in s


class TestBasePipelineUtilities:
    def test_load_saved_streams_roundtrip(self, tmp_path):
        pipeline = FortnitePipeline(
            config=load_cell_configs()["fortnite"], data_root=tmp_path,
        )
        # Generate + save
        streams_orig = pipeline.generate_mock_data()[:3]
        pipeline._save_streams(streams_orig)
        # Load back
        loaded = pipeline.load_saved_streams()
        assert len(loaded) == 3
        # Game IDs should match
        orig_ids = {s.game_id for s in streams_orig}
        loaded_ids = {s.game_id for s in loaded}
        assert orig_ids == loaded_ids

    def test_load_saved_streams_handles_corrupt(self, tmp_path):
        pipeline = FortnitePipeline(
            config=load_cell_configs()["fortnite"], data_root=tmp_path,
        )
        # Write corrupt jsonl
        bad = pipeline.events_dir / "bad.jsonl"
        bad.write_text("not valid jsonl")
        # Should not crash
        loaded = pipeline.load_saved_streams()
        assert loaded == []

    def test_clear_events_dir(self, tmp_path):
        pipeline = FortnitePipeline(
            config=load_cell_configs()["fortnite"], data_root=tmp_path,
        )
        streams = pipeline.generate_mock_data()[:2]
        pipeline._save_streams(streams)
        files_before = list(pipeline.events_dir.glob("*.jsonl"))
        assert len(files_before) == 2
        pipeline._clear_events_dir()
        files_after = list(pipeline.events_dir.glob("*.jsonl"))
        assert files_after == []

    def test_run_with_clear_existing(self, tmp_path):
        pipeline = FortnitePipeline(
            config=load_cell_configs()["fortnite"], data_root=tmp_path,
        )
        # First run
        pipeline.config.sample_target = 5  # smaller for test speed
        pipeline.run(force_mock=True, clear_existing=False)
        first = sorted(p.name for p in pipeline.events_dir.glob("*.jsonl"))
        # Second run with clear_existing=True (default) overwrites
        pipeline.run(force_mock=True, clear_existing=True)
        second = sorted(p.name for p in pipeline.events_dir.glob("*.jsonl"))
        assert first == second  # Same set of files (deterministic mock)


class TestSchemaEdgeCases:
    def test_event_stream_jsonl_missing_header(self, tmp_path):
        path = tmp_path / "nohdr.jsonl"
        path.write_text('{"timestamp": 0, "event_type": "x"}\n')
        with pytest.raises(ValueError, match="header"):
            EventStream.from_jsonl(path)

    def test_event_stream_jsonl_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        with pytest.raises(ValueError, match="Empty"):
            EventStream.from_jsonl(path)

    def test_event_stream_jsonl_malformed_header(self, tmp_path):
        path = tmp_path / "malformed.jsonl"
        path.write_text("not valid json\n")
        with pytest.raises(ValueError, match="Malformed header"):
            EventStream.from_jsonl(path)


class TestTranslationImplementations:
    """T classes are now fully implemented (Phase B locked 2026-04-27)."""

    @pytest.mark.parametrize("t_class,cell_name", [
        ("FortniteT", "fortnite"),
        ("NBAT", "nba"),
        ("CSGOT", "csgo"),
        ("RocketLeagueT", "rocket_league"),
        ("HearthstoneT", "hearthstone"),
    ])
    def test_each_t_has_correct_cell_name(self, t_class, cell_name):
        from v5.src.interfaces import translation
        cls = getattr(translation, t_class)
        instance = cls()
        assert instance.cell == cell_name

    @pytest.mark.parametrize("t_class,cell_name", [
        ("FortniteT", "fortnite"),
        ("NBAT", "nba"),
        ("CSGOT", "csgo"),
        ("RocketLeagueT", "rocket_league"),
        ("HearthstoneT", "hearthstone"),
    ])
    def test_each_t_translate_returns_list(self, t_class, cell_name):
        from v5.src.interfaces import translation
        cls = getattr(translation, t_class)
        instance = cls()
        stream = EventStream(game_id="x", cell=cell_name)
        # Empty stream → empty list (no crash)
        result = instance.translate(stream)
        assert isinstance(result, list)

    def test_batch_translate_returns_list(self):
        from v5.src.interfaces.translation import FortniteT
        t = FortniteT()
        result = t.batch_translate([EventStream(game_id="x", cell="fortnite")])
        assert isinstance(result, list)

    def test_domain_t_registry_complete(self):
        from v5.src.common.schema import VALID_CELLS
        from v5.src.interfaces.translation import DOMAIN_T_STUBS
        assert set(DOMAIN_T_STUBS.keys()) == VALID_CELLS


class TestPromptBuilderPlaceholder:
    """A1 risk: placeholder constraint context is used in real eval — must be detectable."""

    def test_default_constraint_context_contains_marker(self):
        from v5.src.common.schema import ChainCandidate, GameEvent
        from v5.src.harness.prompts import PromptBuilder

        events = [GameEvent(
            timestamp=0.0, event_type="engage_decision",
            actor="p1", location_context={}, raw_data_blob={},
            cell="nba", game_id="g1", sequence_idx=0,
        )]
        chain = ChainCandidate(
            chain_id="c1", game_id="g1", cell="nba",
            events=events, chain_metadata={},
        )
        builder = PromptBuilder(cell="nba")
        ctx = builder.format_constraint_context(chain)
        assert "TO BE DEFINED AT T-DESIGN" in ctx, (
            "Placeholder marker must remain in default constraint context so "
            "callers can detect it before a real eval run."
        )

    def test_default_question_contains_marker(self):
        from v5.src.common.schema import ChainCandidate, GameEvent
        from v5.src.harness.prompts import PromptBuilder

        events = [GameEvent(
            timestamp=0.0, event_type="engage_decision",
            actor="p1", location_context={}, raw_data_blob={},
            cell="nba", game_id="g1", sequence_idx=0,
        )]
        chain = ChainCandidate(
            chain_id="c1", game_id="g1", cell="nba",
            events=events, chain_metadata={},
        )
        builder = PromptBuilder(cell="nba")
        q = builder.format_question(chain)
        assert "TBD AT T-DESIGN" in q


class TestNoisyMockT:
    """M2 risk: NoisyMockT exercises Gate 2 under sub-50% retention."""

    def test_noisy_mock_produces_degraded_chains(self):
        from v5.src.pilot.mock_t import NoisyMockT

        t = NoisyMockT(cell="nba", noise_rate=1.0, target_actionable_frac=0.20)
        stream = _stream("nba", n=30)
        chains = t.translate(stream)
        assert chains, "NoisyMockT must produce at least one chain"
        degraded = [c for c in chains if c.chain_metadata.get("noisy_mock")]
        assert len(degraded) == len(chains), "With noise_rate=1.0 all chains should be degraded"
        # Degraded chains should be below Gate 2 floor (0.50); exact fraction depends
        # on window size, so just verify it's below the gate.
        for c in degraded:
            assert c.chain_metadata["actionable_fraction"] < 0.5

    def test_noisy_mock_zero_noise_identical_to_mock(self):
        from v5.src.pilot.mock_t import MockT, NoisyMockT

        stream = _stream("nba", n=30)
        clean = MockT(cell="nba").translate(stream)
        noisy = NoisyMockT(cell="nba", noise_rate=0.0).translate(stream)
        assert len(clean) == len(noisy)

    def test_noisy_mock_partial_noise_rate(self):
        from v5.src.pilot.mock_t import NoisyMockT

        t = NoisyMockT(cell="nba", noise_rate=0.5)
        stream = _stream("nba", n=50)
        chains = t.translate(stream)
        degraded = [c for c in chains if c.chain_metadata.get("noisy_mock")]
        clean = [c for c in chains if not c.chain_metadata.get("noisy_mock")]
        # With noise_rate=0.5, expect ~50% degraded
        assert len(degraded) > 0
        assert len(clean) > 0


class TestInterimCheck:
    """M1 risk: interim_check.py script runs and recommends pause when delta < 0.04."""

    def test_pause_recommended_when_no_effect(self, tmp_path):
        from v5.scripts.interim_check import check_cell

        # No difference between baseline and intervention → delta ≈ 0
        bl = [True] * 50 + [False] * 50
        iv = [True] * 50 + [False] * 50
        r = check_cell("nba", bl, iv, interim_fraction=1.0, full_n=100)
        assert r.recommend_pause, "No-effect cell should trigger pause"
        assert abs(r.effect_delta) < 0.04

    def test_continue_recommended_when_large_effect(self):
        from v5.scripts.interim_check import check_cell

        # Large effect: c >> b
        bl = [False] * 60 + [True] * 40
        iv = [True] * 60 + [False] * 40
        r = check_cell("nba", bl, iv, interim_fraction=1.0, full_n=100)
        assert not r.recommend_pause, "Large-effect cell should not trigger pause"

    def test_main_exit_code_on_pause(self, tmp_path):
        import json

        from v5.scripts.interim_check import main

        data = {"cells": {"nba": {
            "baseline_correct": [True] * 50 + [False] * 50,
            "intervention_correct": [True] * 50 + [False] * 50,
        }}}
        p = tmp_path / "results.json"
        p.write_text(json.dumps(data))
        code = main(["--results", str(p), "--interim-fraction", "1.0"])
        assert code == 1  # pause → exit 1

    def test_main_exit_code_on_continue(self, tmp_path):
        import json

        from v5.scripts.interim_check import main

        # Intervention much better than baseline
        bl = [False] * 80 + [True] * 20
        iv = [True] * 80 + [False] * 20
        data = {"cells": {"nba": {
            "baseline_correct": bl,
            "intervention_correct": iv,
        }}}
        p = tmp_path / "results.json"
        p.write_text(json.dumps(data))
        code = main(["--results", str(p), "--interim-fraction", "1.0"])
        assert code == 0  # continue → exit 0

    def test_main_missing_file_exits_1(self, tmp_path):
        from v5.scripts.interim_check import main

        code = main(["--results", str(tmp_path / "nonexistent.json")])
        assert code == 1
