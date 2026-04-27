"""
Tests for FixedPerCellChainBuilder (Q4-B chain construction).
"""

import pytest
from v5.src.common.schema import EventStream, GameEvent
from v5.src.interfaces.chain_builder import (
    DefaultChainBuilder,
    FixedPerCellChainBuilder,
    _uniform_subsample,
)


def _stream(cell: str, n_events: int, game_id: str = "g1") -> EventStream:
    s = EventStream(game_id=game_id, cell=cell)
    for i in range(n_events):
        s.append(GameEvent(
            timestamp=float(i),
            event_type="engage_decision",
            actor=f"player_{i % 3}",
            location_context={},
            raw_data_blob={},
            cell=cell,
            game_id=game_id,
            sequence_idx=i,
        ))
    return s


class TestFixedPerCellChainBuilder:
    def test_unset_cell_raises(self):
        builder = FixedPerCellChainBuilder()
        with pytest.raises(ValueError, match="not set"):
            builder.get_chain_length("nba")

    def test_zero_or_negative_raises(self):
        builder = FixedPerCellChainBuilder({"nba": 0})
        with pytest.raises(ValueError, match=">= 1"):
            builder.get_chain_length("nba")

    def test_locked_per_cell_lengths(self):
        builder = FixedPerCellChainBuilder({"nba": 6, "csgo": 10})
        assert builder.get_chain_length("nba") == 6
        assert builder.get_chain_length("csgo") == 10

    def test_non_overlapping_windows(self):
        builder = FixedPerCellChainBuilder({"nba": 5})
        streams = [_stream("nba", 20)]
        chains = builder.build_from_streams(streams, cell="nba")
        # 20 events / chain_length 5 = 4 chains
        assert len(chains) == 4
        # Verify windows are non-overlapping
        for i, chain in enumerate(chains):
            expected_start = i * 5
            assert chain.events[0].sequence_idx == expected_start
            assert chain.events[-1].sequence_idx == expected_start + 4

    def test_partial_tail_dropped(self):
        builder = FixedPerCellChainBuilder({"nba": 5})
        streams = [_stream("nba", 23)]  # 4 full chains, 3 leftover
        chains = builder.build_from_streams(streams, cell="nba")
        assert len(chains) == 4

    def test_too_short_stream_yields_no_chains(self):
        builder = FixedPerCellChainBuilder({"nba": 10})
        streams = [_stream("nba", 5)]  # < chain_length
        chains = builder.build_from_streams(streams, cell="nba")
        assert chains == []

    def test_overlap_mode(self):
        builder = FixedPerCellChainBuilder({"nba": 5}, overlap=True)
        streams = [_stream("nba", 10)]
        chains = builder.build_from_streams(streams, cell="nba")
        # With overlap=True, step=1, so 10-5+1 = 6 chains
        assert len(chains) == 6

    def test_max_chains_subsamples(self):
        builder = FixedPerCellChainBuilder({"nba": 5})
        # 4 streams × 4 chains each = 16 raw chains
        streams = [_stream("nba", 20, f"g{i}") for i in range(4)]
        chains = builder.build_from_streams(streams, cell="nba", max_chains=8)
        assert len(chains) == 8

    def test_wrong_cell_stream_skipped(self):
        builder = FixedPerCellChainBuilder({"nba": 5})
        streams = [_stream("csgo", 20)]  # wrong cell
        chains = builder.build_from_streams(streams, cell="nba")
        assert chains == []

    def test_chain_metadata_set(self):
        builder = FixedPerCellChainBuilder({"nba": 5})
        streams = [_stream("nba", 10)]
        chains = builder.build_from_streams(streams, cell="nba")
        for chain in chains:
            assert chain.chain_metadata["chain_length"] == 5
            assert chain.chain_metadata["builder"] == "FixedPerCellChainBuilder"
            assert chain.chain_metadata["overlap"] is False

    def test_chain_ids_unique_within_stream(self):
        builder = FixedPerCellChainBuilder({"nba": 5})
        streams = [_stream("nba", 20)]
        chains = builder.build_from_streams(streams, cell="nba")
        ids = [c.chain_id for c in chains]
        assert len(ids) == len(set(ids))

    def test_build_dispatches_event_streams(self):
        builder = FixedPerCellChainBuilder({"nba": 5})
        streams = [_stream("nba", 20)]
        chains = builder.build(streams)
        assert len(chains) == 4

    def test_build_passes_through_chain_candidates(self):
        builder = FixedPerCellChainBuilder({"nba": 5})
        streams = [_stream("nba", 10)]
        first = builder.build_from_streams(streams, cell="nba")
        # Pass chains back through .build() — should pass through unchanged
        same = builder.build(first)
        assert len(same) == len(first)

    def test_build_invalid_input_raises(self):
        builder = FixedPerCellChainBuilder({"nba": 5})
        with pytest.raises(TypeError):
            builder.build([{"not_a_stream": True}])

    def test_default_chain_builder_alias(self):
        # Backwards-compat alias
        assert DefaultChainBuilder is FixedPerCellChainBuilder


def test_uniform_subsample():
    items = list(range(100))
    sub = _uniform_subsample(items, 10)
    assert len(sub) == 10
    # Should be roughly evenly spaced
    diffs = [sub[i+1] - sub[i] for i in range(len(sub)-1)]
    assert all(d >= 9 for d in diffs)


def test_uniform_subsample_k_larger_than_n():
    items = list(range(5))
    assert _uniform_subsample(items, 100) == items


def test_uniform_subsample_k_zero():
    assert _uniform_subsample([1, 2, 3], 0) == [1, 2, 3]
