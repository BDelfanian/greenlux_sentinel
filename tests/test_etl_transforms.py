"""Unit tests for the pure ETL transform functions (no DB required).

Run against small synthetic fixtures in tests/fixtures/, built to match the *real* column
shapes confirmed in notebooks/01_data_profiling against the actual downloaded Kaggle files
(see module docstrings in etl/load_funds_postgres.py and etl/load_esg_cosmos.py for the
specific quirks these fixtures exercise: dict-stringified holding names, fraction-vs-percent
weights, case-mismatched tickers, missing management_company/sector/domicile columns).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from greenlux_sentinel.etl import load_esg_cosmos, load_funds_postgres

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def mutual_funds_df() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "morningstar_mutual_funds_sample.csv")


@pytest.fixture
def etfs_df() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "morningstar_etfs_sample.csv")


@pytest.fixture
def holdings_df() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "etf_holdings_sample.csv")


@pytest.fixture
def esg_df() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "company_esg_ratings_sample.csv")


class TestFundsTransform:
    def test_row_count_preserved(self, mutual_funds_df):
        assert len(load_funds_postgres.transform(mutual_funds_df, "mutual_fund")) == len(mutual_funds_df)

    def test_fund_type_set_from_caller_not_a_column(self, mutual_funds_df, etfs_df):
        mf = load_funds_postgres.transform(mutual_funds_df, "mutual_fund")
        etf = load_funds_postgres.transform(etfs_df, "etf")
        assert set(mf["fund_type"]) == {"mutual_fund"}
        assert set(etf["fund_type"]) == {"etf"}

    def test_domicile_derived_from_isin_prefix(self, mutual_funds_df):
        out = load_funds_postgres.transform(mutual_funds_df, "mutual_fund")
        row = out.loc[out["fund_id"] == "F004"].iloc[0]
        assert row["domicile_country"] == "IE"  # isin IE00B4L5Y983

    def test_management_company_parsed_when_dash_present(self, mutual_funds_df):
        out = load_funds_postgres.transform(mutual_funds_df, "mutual_fund")
        row = out.loc[out["fund_id"] == "F001"].iloc[0]
        assert row["management_company"] == "Nordea Investment Funds"

    def test_management_company_null_when_no_dash(self, mutual_funds_df):
        out = load_funds_postgres.transform(mutual_funds_df, "mutual_fund")
        row = out.loc[out["fund_id"] == "F003"].iloc[0]  # "BlueBay Emerging Markets Bond Fund" — no " - "
        assert pd.isna(row["management_company"])

    def test_missing_sustainability_rating_stays_null(self, mutual_funds_df):
        out = load_funds_postgres.transform(mutual_funds_df, "mutual_fund")
        row = out.loc[out["fund_id"] == "F003"].iloc[0]
        assert pd.isna(row["sustainability_rating"])

    def test_missing_column_raises(self, mutual_funds_df):
        with pytest.raises(ValueError, match="missing expected columns"):
            load_funds_postgres.transform(mutual_funds_df.drop(columns=["sustainability_score"]), "mutual_fund")


class TestEsgCosmosTransform:
    def test_one_doc_per_etf(self, holdings_df, esg_df):
        docs = load_esg_cosmos.transform(holdings_df, esg_df)
        assert {d["etf_ticker"] for d in docs} == {"GRNENERGY", "GLBESG50", "EUCLEAN", "WLDSUS"}

    def test_holding_name_dict_artifact_is_parsed(self, holdings_df, esg_df):
        docs = {d["etf_ticker"]: d for d in load_esg_cosmos.transform(holdings_df, esg_df)}
        nee = next(h for h in docs["GRNENERGY"]["holdings"] if h["ticker"] == "NEE")
        assert nee["name"] == "NextEra Energy Inc"  # not the raw "{'t': 'span', ...}" string

    def test_weight_rescaled_from_fraction_to_percent(self, holdings_df, esg_df):
        docs = {d["etf_ticker"]: d for d in load_esg_cosmos.transform(holdings_df, esg_df)}
        nee = next(h for h in docs["GRNENERGY"]["holdings"] if h["ticker"] == "NEE")
        assert nee["weight_pct"] == pytest.approx(9.80)  # raw fixture has 0.0980

    def test_ticker_case_mismatch_still_joins(self, holdings_df, esg_df):
        # holdings use uppercase tickers (NEE), the ESG file uses lowercase (nee) — matches real data
        docs = {d["etf_ticker"]: d for d in load_esg_cosmos.transform(holdings_df, esg_df)}
        nee = next(h for h in docs["GRNENERGY"]["holdings"] if h["ticker"] == "NEE")
        assert nee["esg"] is not None
        assert nee["esg"]["total_esg_score"] == 1450

    def test_partial_overlap_leaves_unmatched_holdings_with_no_esg(self, holdings_df, esg_df):
        docs = {d["etf_ticker"]: d for d in load_esg_cosmos.transform(holdings_df, esg_df)}
        vws = next(h for h in docs["GRNENERGY"]["holdings"] if h["ticker"] == "VWS")
        assert vws["esg"] is None

    def test_esg_coverage_pct_reflects_overlap(self, holdings_df, esg_df):
        docs = {d["etf_ticker"]: d for d in load_esg_cosmos.transform(holdings_df, esg_df)}
        assert docs["GRNENERGY"]["esg_coverage_pct"] == pytest.approx(80.0)  # VWS missing
        assert docs["GLBESG50"]["esg_coverage_pct"] == pytest.approx(80.0)  # ACN missing
        assert docs["EUCLEAN"]["esg_coverage_pct"] == pytest.approx(60.0)  # IBE, VOW3 missing
        assert docs["WLDSUS"]["esg_coverage_pct"] == pytest.approx(100.0)  # full overlap

    def test_holdings_implied_esg_score_is_weighted_average_of_matched_only(self, holdings_df, esg_df):
        docs = {d["etf_ticker"]: d for d in load_esg_cosmos.transform(holdings_df, esg_df)}
        assert docs["GRNENERGY"]["holdings_implied_esg_score"] == pytest.approx(1361.69, abs=0.01)

    def test_no_esg_matches_yields_null_implied_score(self, holdings_df):
        empty_esg = pd.DataFrame(
            columns=["ticker", "name", "currency", "exchange", "industry",
                     "environment_score", "social_score", "governance_score", "total_score", "total_level"]
        )
        docs = load_esg_cosmos.transform(holdings_df, empty_esg)
        assert all(d["holdings_implied_esg_score"] is None for d in docs)
        assert all(d["esg_coverage_pct"] == 0.0 for d in docs)
