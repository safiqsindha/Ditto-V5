"""
Pipeline real-fetch tests with HTTP and subprocess mocks.

Exercises the fetch+parse paths of each pipeline without making real network
calls or invoking external binaries. Covers code paths that pure-mock-data
tests can't reach.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from v5.src.cells.csgo.pipeline import CSGOPipeline
from v5.src.cells.fortnite.pipeline import FortnitePipeline
from v5.src.cells.hearthstone.pipeline import HearthstonePipeline
from v5.src.cells.nba.pipeline import NBAPipeline
from v5.src.cells.rocket_league.pipeline import RocketLeaguePipeline
from v5.src.common.config import load_cell_configs


@pytest.fixture
def cfgs():
    return load_cell_configs()


# ---------------------------------------------------------------------------
# CS:GO — HLTV demo download via requests
# ---------------------------------------------------------------------------

class TestCSGORealFetch:
    def test_fetch_downloads_demos(self, cfgs, tmp_path):
        pipeline = CSGOPipeline(config=cfgs["csgo"], data_root=tmp_path)
        # Limit sample target to make the test fast
        pipeline.config.sample_target = 2

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content = lambda chunk_size: [b"FAKE_DEMO_BYTES"]

        with patch("v5.src.cells.csgo.pipeline.requests.Session.get",
                   return_value=mock_response) as mock_get:
            paths = pipeline.fetch()
        assert mock_get.called
        assert len(paths) >= 1
        for p in paths:
            assert p.exists()
            assert p.read_bytes() == b"FAKE_DEMO_BYTES"

    def test_fetch_handles_non_200(self, cfgs, tmp_path):
        pipeline = CSGOPipeline(config=cfgs["csgo"], data_root=tmp_path)
        pipeline.config.sample_target = 2
        mock_response = MagicMock()
        mock_response.status_code = 404
        with patch("v5.src.cells.csgo.pipeline.requests.Session.get",
                   return_value=mock_response):
            paths = pipeline.fetch()
        # Non-200 → no download, no path
        assert paths == []

    def test_fetch_skips_already_downloaded(self, cfgs, tmp_path):
        pipeline = CSGOPipeline(config=cfgs["csgo"], data_root=tmp_path)
        pipeline.config.sample_target = 2
        # Pre-create a demo file matching the first match ID
        match_ids = pipeline._get_target_match_ids()
        existing = pipeline.raw_dir / f"{match_ids[0]}.dem"
        existing.write_bytes(b"old")
        with patch("v5.src.cells.csgo.pipeline.requests.Session.get"):
            paths = pipeline.fetch()
        # Existing file should be in paths without HTTP call for it
        assert any(p == existing for p in paths)

    def test_parse_handles_missing_awpy(self, cfgs, tmp_path):
        """awpy not installed → parse returns empty without crashing."""
        pipeline = CSGOPipeline(config=cfgs["csgo"], data_root=tmp_path)
        # Create one fake .dem
        dem = pipeline.raw_dir / "test.dem"
        dem.write_bytes(b"fake")
        with patch.dict("sys.modules", {"awpy": None}):
            records = pipeline.parse([dem])
        assert records == []

    def test_extract_events_filters_falsy(self, cfgs, tmp_path):
        pipeline = CSGOPipeline(config=cfgs["csgo"], data_root=tmp_path)
        # Mix of valid and None records
        valid = {
            "matchID": "test_match",
            "mapName": "de_mirage",
            "rounds": [{"roundNum": 1, "startTick": 0, "kills": [], "grenades": [],
                        "bombEvents": [], "ctEqVal": 4250, "tEqVal": 4350}],
        }
        streams = pipeline.extract_events([valid, None, valid])
        assert len(streams) == 2

    def test_get_target_match_ids(self, cfgs, tmp_path):
        pipeline = CSGOPipeline(config=cfgs["csgo"], data_root=tmp_path)
        ids = pipeline._get_target_match_ids()
        assert len(ids) > 0
        assert all(isinstance(i, int) for i in ids)


# ---------------------------------------------------------------------------
# NBA — nba_api PlayByPlayV3
# ---------------------------------------------------------------------------

class TestNBARealFetch:
    def test_fetch_handles_missing_nba_api(self, cfgs, tmp_path):
        pipeline = NBAPipeline(config=cfgs["nba"], data_root=tmp_path)
        # Force ImportError by patching the import path
        original_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def raising_import(name, *args, **kwargs):
            if "nba_api" in name:
                raise ImportError("nba_api not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=raising_import):
            paths = pipeline.fetch()
        assert paths == []

    def test_fetch_with_mocked_nba_api(self, cfgs, tmp_path):
        pipeline = NBAPipeline(config=cfgs["nba"], data_root=tmp_path)
        pipeline.config.sample_target = 2

        mock_endpoint = MagicMock()
        mock_endpoint.get_dict.return_value = {
            "parameters": {"GameID": "test"},
            "resultSets": [{"headers": [], "rowSet": []}],
        }
        mock_module = MagicMock()
        mock_module.PlayByPlayV3.return_value = mock_endpoint

        with patch.dict("sys.modules", {
            "nba_api": MagicMock(),
            "nba_api.stats": MagicMock(),
            "nba_api.stats.endpoints": MagicMock(playbyplayv3=mock_module),
        }), patch("v5.src.cells.nba.pipeline.time.sleep"):
            paths = pipeline.fetch()
        # Should have written at least one file
        assert len(paths) >= 1

    def test_fetch_skips_existing(self, cfgs, tmp_path):
        pipeline = NBAPipeline(config=cfgs["nba"], data_root=tmp_path)
        pipeline.config.sample_target = 1
        # Pre-create the first game file
        game_ids = pipeline._get_target_game_ids()
        existing = pipeline.raw_dir / f"{game_ids[0]}.json"
        existing.write_text('{"foo": "bar"}')
        # Mock nba_api so the import doesn't fail
        mock_module = MagicMock()
        with patch.dict("sys.modules", {
            "nba_api": MagicMock(),
            "nba_api.stats": MagicMock(),
            "nba_api.stats.endpoints": MagicMock(playbyplayv3=mock_module),
        }), patch("v5.src.cells.nba.pipeline.time.sleep"):
            paths = pipeline.fetch()
        assert any(p == existing for p in paths)

    def test_parse_handles_bad_files(self, cfgs, tmp_path):
        pipeline = NBAPipeline(config=cfgs["nba"], data_root=tmp_path)
        good = pipeline.raw_dir / "good.json"
        good.write_text('{"resultSets": []}')
        bad = pipeline.raw_dir / "bad.json"
        bad.write_text("not valid json")
        records = pipeline.parse([good, bad])
        # Bad file logs warning but doesn't crash
        assert len(records) == 1

    def test_get_target_game_ids(self, cfgs, tmp_path):
        pipeline = NBAPipeline(config=cfgs["nba"], data_root=tmp_path)
        ids = pipeline._get_target_game_ids()
        assert len(ids) > 0


# ---------------------------------------------------------------------------
# Rocket League — BallChasing API + carball/rrrocket
# ---------------------------------------------------------------------------

class TestRLRealFetch:
    # Ballchasing API JSON format (no binary download, no carball/rrrocket).
    # fetch() → GET /replays (list) + GET /replays/{id} (JSON stats per replay).
    # parse() → load saved JSON files from raw_dir.

    _FAKE_REPLAY_JSON = {
        "id": "rep1",
        "duration": 300,
        "blue": {"goals": 2, "players": [
            {"id": {"platform": "steam", "id": "111"}, "name": "P1",
             "stats": {"core": {"shots": 3, "goals": 1, "saves": 1, "assists": 0,
                                "demo": {"inflicted": 0}},
                       "boost": {"bcpm": 200, "count_collected_big": 5,
                                 "count_collected_small": 10}}},
        ]},
        "orange": {"goals": 1, "players": [
            {"id": {"platform": "steam", "id": "222"}, "name": "P2",
             "stats": {"core": {"shots": 2, "goals": 1, "saves": 2, "assists": 1,
                                "demo": {"inflicted": 1}},
                       "boost": {"bcpm": 180, "count_collected_big": 4,
                                 "count_collected_small": 8}}},
        ]},
    }

    def test_fetch_no_token_silently_returns_empty(self, cfgs, tmp_path, monkeypatch):
        monkeypatch.delenv("BALLCHASING_TOKEN", raising=False)
        pipeline = RocketLeaguePipeline(config=cfgs["rocket_league"], data_root=tmp_path)
        # No token → connection fails (realistic: requests.ConnectionError)
        import requests as req_module
        with patch.object(pipeline.session, "get",
                          side_effect=req_module.ConnectionError("no auth")), \
             patch("v5.src.cells.rocket_league.pipeline.time.sleep"):
            paths = pipeline.fetch()
        assert paths == []

    def test_fetch_with_mocked_api(self, cfgs, tmp_path, monkeypatch):
        monkeypatch.setenv("BALLCHASING_TOKEN", "fake_token")
        pipeline = RocketLeaguePipeline(config=cfgs["rocket_league"], data_root=tmp_path)
        pipeline.config.sample_target = 2

        list_resp = MagicMock()
        list_resp.status_code = 200
        list_resp.raise_for_status = MagicMock()
        list_resp.json.return_value = {"list": [{"id": "rep1"}, {"id": "rep2"}]}

        replay_resp = MagicMock()
        replay_resp.status_code = 200
        replay_resp.raise_for_status = MagicMock()
        replay_resp.json.return_value = self._FAKE_REPLAY_JSON

        def get_side_effect(url, *args, **kwargs):
            if "/replays/rep" in url:
                return replay_resp
            return list_resp

        with patch.object(pipeline.session, "get", side_effect=get_side_effect), \
             patch("v5.src.cells.rocket_league.pipeline.time.sleep"):
            paths = pipeline.fetch()
        assert len(paths) == 2
        # Files are .json, not .replay
        assert all(p.suffix == ".json" for p in paths)

    def test_fetch_handles_rate_limit(self, cfgs, tmp_path, monkeypatch):
        monkeypatch.setenv("BALLCHASING_TOKEN", "fake")
        pipeline = RocketLeaguePipeline(config=cfgs["rocket_league"], data_root=tmp_path)
        pipeline.config.sample_target = 1

        list_resp = MagicMock()
        list_resp.status_code = 200
        list_resp.raise_for_status = MagicMock()
        list_resp.json.return_value = {"list": [{"id": "rep1"}]}

        rate_resp = MagicMock()
        rate_resp.status_code = 429
        rate_resp.headers = {"Retry-After": "1"}

        def get_side_effect(url, *args, **kwargs):
            # Rate-limit on individual replay fetch
            if "/replays/rep" in url:
                return rate_resp
            return list_resp

        with patch.object(pipeline.session, "get", side_effect=get_side_effect), \
             patch("v5.src.cells.rocket_league.pipeline.time.sleep"):
            paths = pipeline.fetch()
        # All retries exhausted on 429 → no paths saved
        assert len(paths) == 0

    def test_parse_loads_json_from_raw_dir(self, cfgs, tmp_path):
        pipeline = RocketLeaguePipeline(config=cfgs["rocket_league"], data_root=tmp_path)
        # Write a JSON file directly into raw_dir (as fetch() would produce)
        json_path = pipeline.raw_dir / "rep1.json"
        json_path.write_text(json.dumps(self._FAKE_REPLAY_JSON))
        records = pipeline.parse([json_path])
        assert len(records) == 1
        assert records[0]["id"] == "rep1"

    def test_parse_skips_corrupt_json(self, cfgs, tmp_path):
        pipeline = RocketLeaguePipeline(config=cfgs["rocket_league"], data_root=tmp_path)
        bad_path = pipeline.raw_dir / "bad.json"
        bad_path.write_text("not valid json")
        records = pipeline.parse([bad_path])
        assert records == []

    def test_extract_events_from_ballchasing_json(self, cfgs, tmp_path):
        pipeline = RocketLeaguePipeline(config=cfgs["rocket_league"], data_root=tmp_path)
        streams = pipeline.extract_events([self._FAKE_REPLAY_JSON])
        assert len(streams) == 1
        stream = streams[0]
        # Goals come from per-player stats: P1=1 goal, P2=1 goal → 2 total
        goals = [e for e in stream.events if e.event_type == "objective_capture"]
        assert len(goals) == 2
        # Events should be sorted by timestamp
        ts = [e.timestamp for e in stream.events]
        assert ts == sorted(ts)


# ---------------------------------------------------------------------------
# Hearthstone — HSReplay API + hslog
# ---------------------------------------------------------------------------

class TestHSRealFetch:
    """Hearthstone is mock-only (no public bulk replay API)."""

    def test_fetch_always_returns_empty(self, cfgs, tmp_path):
        pipeline = HearthstonePipeline(config=cfgs["hearthstone"], data_root=tmp_path)
        paths = pipeline.fetch()
        assert paths == []

    def test_parse_always_returns_empty(self, cfgs, tmp_path):
        pipeline = HearthstonePipeline(config=cfgs["hearthstone"], data_root=tmp_path)
        records = pipeline.parse([tmp_path / "nonexistent.hsreplay"])
        assert records == []

    def test_generate_mock_data_hits_sample_target(self, cfgs, tmp_path):
        pipeline = HearthstonePipeline(config=cfgs["hearthstone"], data_root=tmp_path)
        pipeline.config.sample_target = 10
        streams = pipeline.generate_mock_data()
        assert len(streams) == 10

    def test_mock_streams_have_turn_phases(self, cfgs, tmp_path):
        pipeline = HearthstonePipeline(config=cfgs["hearthstone"], data_root=tmp_path)
        pipeline.config.sample_target = 2
        streams = pipeline.generate_mock_data()
        phases = {e.phase for s in streams for e in s.events}
        assert any(p.startswith("turn_") for p in phases)


# ---------------------------------------------------------------------------
# Fortnite — replay-downloader subprocess + decompressor
# ---------------------------------------------------------------------------

class TestFortniteRealFetch:
    # Pure Python Epic API implementation: OAuth client_credentials + JSON event chunks.
    # No Node.js / dotnet subprocess needed.

    _FAKE_EVENTS = [
        {"id": "e1", "group": "PhaseChange",
         "metadata": {"phase": 1, "circleCenterX": 0, "circleCenterY": 0, "circleRadius": 5000},
         "time1_ms": 90000, "time2_ms": 90000},
        {"id": "e2", "group": "playerElim",
         "metadata": {"eliminator": "p1", "eliminated": "p2", "weapon": "AR", "knocked": False},
         "time1_ms": 120000, "time2_ms": 120000},
    ]
    _FAKE_RECORD = {"match_id": "abc123", "events": _FAKE_EVENTS}

    def _mock_pipeline(self, cfgs, tmp_path):
        pipeline = FortnitePipeline(config=cfgs["fortnite"], data_root=tmp_path)
        pipeline.config.sample_target = 1
        return pipeline

    def test_fetch_auth_failure_returns_empty(self, cfgs, tmp_path):
        pipeline = self._mock_pipeline(cfgs, tmp_path)
        # Simulate OAuth failure
        with patch.object(pipeline, "_get_token", return_value=""), \
             patch("v5.src.cells.fortnite.pipeline.time.sleep"):
            paths = pipeline.fetch()
        assert paths == []

    def test_fetch_expired_replay_skipped(self, cfgs, tmp_path):
        pipeline = self._mock_pipeline(cfgs, tmp_path)
        # Metadata returns 404 → replay expired
        with patch.object(pipeline, "_get_token", return_value="tok"), \
             patch.object(pipeline, "_get_metadata", return_value=None), \
             patch("v5.src.cells.fortnite.pipeline.time.sleep"):
            paths = pipeline.fetch()
        assert paths == []

    def test_fetch_writes_json_on_success(self, cfgs, tmp_path):
        pipeline = self._mock_pipeline(cfgs, tmp_path)
        fake_meta = {"Events": [{"Id": "chunk1"}]}
        with patch.object(pipeline, "_get_token", return_value="tok"), \
             patch.object(pipeline, "_get_metadata", return_value=fake_meta), \
             patch.object(pipeline, "_download_chunk", return_value=b""), \
             patch("v5.src.cells.fortnite.pipeline._parse_event_chunk",
                   return_value=self._FAKE_EVENTS[0]), \
             patch("v5.src.cells.fortnite.pipeline.time.sleep"):
            paths = pipeline.fetch()
        assert len(paths) == 1
        assert paths[0].suffix == ".json"

    def test_fetch_skips_existing_file(self, cfgs, tmp_path):
        pipeline = self._mock_pipeline(cfgs, tmp_path)
        # Pre-write the output file
        norm_id = "0fbcece6e1774c9abdd1ebd88fbad4ec"
        existing = pipeline.raw_dir / f"{norm_id}.json"
        existing.write_text(json.dumps(self._FAKE_RECORD))
        with patch.object(pipeline, "_get_token", return_value="tok"):
            paths = pipeline.fetch()
        # Should not call _get_token at all for already-downloaded match
        assert existing in paths

    def test_parse_loads_json_file(self, cfgs, tmp_path):
        pipeline = self._mock_pipeline(cfgs, tmp_path)
        p = pipeline.raw_dir / "abc.json"
        p.write_text(json.dumps(self._FAKE_RECORD))
        records = pipeline.parse([p])
        assert len(records) == 1
        assert records[0]["match_id"] == "abc123"

    def test_parse_skips_corrupt_file(self, cfgs, tmp_path):
        pipeline = self._mock_pipeline(cfgs, tmp_path)
        p = pipeline.raw_dir / "bad.json"
        p.write_text("not json")
        records = pipeline.parse([p])
        assert records == []

    def test_extract_events_from_event_chunks(self, cfgs, tmp_path):
        pipeline = self._mock_pipeline(cfgs, tmp_path)
        streams = pipeline.extract_events([self._FAKE_RECORD])
        assert len(streams) == 1
        stream = streams[0]
        zone = [e for e in stream.events if e.event_type == "zone_enter"]
        engage = [e for e in stream.events if e.event_type == "engage_decision"]
        assert len(zone) == 1
        assert len(engage) == 1
