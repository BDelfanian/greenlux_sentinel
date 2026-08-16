"""Unit tests for etl_agent.py: orchestration + GLEIF cross-check wiring, via injected fakes and
patched collaborators -- no live DB/Cosmos/network needed. Mirrors test_report_agent.py's
patch-the-collaborator style; the loaders' own transform/load logic is already covered by
test_etl_load.py and test_etl_transforms.py, not re-tested here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from greenlux_sentinel.agents import etl_agent

_GLEIF_RECORD = {
    "lei": "5299009N55YRQC5FQK92",
    "legal_name": "Company A Asset Management",
    "entity_legal_form": "8888",
    "entity_status": "ACTIVE",
    "country": "LU",
}


class TestCrossCheckLuEntities:
    def test_matches_and_inserts_only_found_records(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [("Company A",), ("Company B",)]
        client = MagicMock()

        def fake_lookup(name, client=None):
            return _GLEIF_RECORD if name == "Company A" else None

        with patch("greenlux_sentinel.mcp_servers.gleif_server.lookup_lei", side_effect=fake_lookup):
            matched = etl_agent.cross_check_lu_entities(conn, client=client)

        assert matched == 1
        insert_calls = [c for c in cur.execute.call_args_list if "INSERT INTO lu_legal_entities" in c.args[0]]
        assert len(insert_calls) == 1
        assert insert_calls[0].args[1] == _GLEIF_RECORD
        audit_calls = [c for c in cur.execute.call_args_list if "audit_log" in c.args[0]]
        assert len(audit_calls) == 1
        assert not client.close.called  # caller-owned client

    def test_no_matches_writes_zero_count_audit_row(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [("Company A",)]

        with patch("greenlux_sentinel.mcp_servers.gleif_server.lookup_lei", return_value=None):
            matched = etl_agent.cross_check_lu_entities(conn, client=MagicMock())

        assert matched == 0
        insert_calls = [c for c in cur.execute.call_args_list if "INSERT INTO lu_legal_entities" in c.args[0]]
        assert len(insert_calls) == 0


class TestResolveDataDir:
    def test_returns_data_dir_unchanged_when_files_already_present(self, tmp_path):
        for name in etl_agent._REQUIRED_FILES:
            (tmp_path / name).write_text("x")

        result = etl_agent._resolve_data_dir(tmp_path)

        assert result == tmp_path

    def test_downloads_from_landing_container_when_files_missing(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        container = MagicMock()
        # A real ADLS Gen2 listing includes directory placeholder entries alongside real files
        # (infra/modules/storage.bicep has isHnsEnabled: true) -- included here so this test
        # covers the exact bug hit live in Phase 5: a "verified_holdings" directory marker
        # colliding with the real file written under that same path.
        blob_dir = SimpleNamespace(name="verified_holdings", metadata={"hdi_isfolder": "true"})
        blob_a = SimpleNamespace(name="morningstar_european_mutual_funds.csv", metadata=None)
        blob_b = SimpleNamespace(name="verified_holdings/verified_SUAS_ishares_msci_usa_sri.csv", metadata=None)
        container.list_blobs.return_value = [blob_dir, blob_a, blob_b]
        container.download_blob.return_value.readall.return_value = b"csv,data"

        with tempfile.TemporaryDirectory() as fake_tempdir:
            with patch("tempfile.mkdtemp", return_value=fake_tempdir):
                result = etl_agent._resolve_data_dir(empty_dir, container=container)

            assert result == Path(fake_tempdir)
            assert (result / "morningstar_european_mutual_funds.csv").read_bytes() == b"csv,data"
            assert (
                result / "verified_holdings" / "verified_SUAS_ishares_msci_usa_sri.csv"
            ).read_bytes() == b"csv,data"

    def test_raises_clearly_when_no_local_data_and_no_landing_storage_configured(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with patch(
            "greenlux_sentinel.config.get_settings",
            return_value=SimpleNamespace(landing_storage_account_name=""),
        ), pytest.raises(FileNotFoundError):
            etl_agent._resolve_data_dir(empty_dir)


class TestScoreCompositionAnomalies:
    def test_scores_and_returns_written_count(self):
        conn = MagicMock()
        with (
            patch("greenlux_sentinel.agents.ml_risk_agent._resolve_model_path", return_value=Path("model.joblib")),
            patch("greenlux_sentinel.ml.greenwashing_risk_model.load_model", return_value="fake-bundle"),
            patch("greenlux_sentinel.ml.train_greenwashing_risk_model.load_training_data", return_value="fake-df") as m_load,
            patch("greenlux_sentinel.ml.train_greenwashing_risk_model.score_all_funds", return_value=41) as m_score,
        ):
            result = etl_agent._score_composition_anomalies(conn)

        assert result == {"composition_anomaly_scores_written": 41}
        m_load.assert_called_once_with(conn=conn)
        m_score.assert_called_once_with("fake-bundle", "fake-df", conn=conn)

    def test_missing_model_artifact_is_best_effort_not_raised(self):
        # No trained artifact yet (e.g. a fresh environment's very first ETL run) must not fail
        # the whole ingestion run -- see _score_composition_anomalies()'s own docstring.
        conn = MagicMock()
        with patch(
            "greenlux_sentinel.agents.ml_risk_agent._resolve_model_path",
            side_effect=FileNotFoundError("no artifact"),
        ):
            result = etl_agent._score_composition_anomalies(conn)

        assert result == {"composition_anomaly_scoring_error": "no artifact"}


class TestRunIngestion:
    def test_orchestrates_all_stages_and_commits(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        container = MagicMock()
        data_dir = Path("fake/data/dir")

        with (
            patch("greenlux_sentinel.agents.etl_agent._resolve_data_dir", return_value=data_dir),
            patch("greenlux_sentinel.etl.load_funds_postgres.load", return_value=12) as mock_funds,
            patch("greenlux_sentinel.etl.load_esg_cosmos.load", return_value=4) as mock_top100,
            patch("greenlux_sentinel.etl.load_verified_holdings_cosmos.load", return_value=5) as mock_verified,
            patch("greenlux_sentinel.agents.etl_agent.cross_check_lu_entities", return_value=3) as mock_gleif,
            patch(
                "greenlux_sentinel.agents.etl_agent._score_composition_anomalies",
                return_value={"composition_anomaly_scores_written": 7},
            ) as mock_score,
        ):
            summary = etl_agent.run_ingestion(data_dir=data_dir, conn=conn, container=container)

        mock_score.assert_called_once_with(conn)

        mock_funds.assert_called_once_with(
            data_dir / "morningstar_european_mutual_funds.csv", data_dir / "morningstar_european_etfs.csv", conn=conn
        )
        mock_top100.assert_called_once_with(
            data_dir / "top100_etf_holdings.csv", data_dir / "public_company_esg_ratings.csv", container=container
        )
        mock_verified.assert_called_once_with(
            data_dir / "verified_holdings", data_dir / "public_company_esg_ratings.csv", container=container
        )
        mock_gleif.assert_called_once_with(conn)

        assert summary == {
            "funds_loaded": 12,
            "top100_holdings_docs": 4,
            "verified_holdings_docs": 5,
            "gleif_matched": 3,
            "composition_anomaly_scores_written": 7,
        }
        audit_calls = [c for c in cur.execute.call_args_list if "audit_log" in c.args[0]]
        assert len(audit_calls) == 1
        assert conn.commit.called
        assert not conn.close.called  # caller-owned connection
