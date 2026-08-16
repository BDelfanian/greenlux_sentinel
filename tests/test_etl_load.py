"""Tests for the I/O side of the ETL loaders, using injected fakes (no real DB needed).

Complements test_etl_transforms.py, which only covers the pure transform() functions.
These tests check load() wires transform -> writes -> audit log -> commit correctly when
given a DB handle, via dependency injection (see the `conn`/`container` params on load()).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from greenlux_sentinel.etl import load_esg_cosmos, load_funds_postgres

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_funds_postgres_upserts_and_commits():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value

    count = load_funds_postgres.load(
        FIXTURES / "morningstar_mutual_funds_sample.csv", FIXTURES / "morningstar_etfs_sample.csv", conn=conn
    )

    assert count == 12  # 8 mutual funds + 4 ETFs
    assert cur.executemany.call_count == 1
    sql, records = cur.executemany.call_args.args
    assert "INSERT INTO funds" in sql
    assert len(records) == 12
    assert conn.commit.called
    assert not conn.close.called  # caller-owned connection, load() must not close it


def test_load_funds_postgres_converts_missing_numeric_to_none_not_nan():
    # Regression test for a real, live bug: `.where(pd.notnull(df), None)` on a mixed-dtype
    # DataFrame silently leaves float NaN in place for numeric columns (a float64 column can't
    # hold Python None, so pandas coerces the assignment back to NaN) -- Postgres' `numeric` type
    # then happily stores that NaN instead of NULL, which poisons any AVG()/SUM() over it (IEEE754
    # NaN propagates through arithmetic; NULL is simply excluded). Confirmed live: NL2SQL's
    # `AVG(sustainability_rating)` for LU funds returned the string "NaN", not a real number.
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value

    load_funds_postgres.load(
        FIXTURES / "morningstar_mutual_funds_sample.csv", FIXTURES / "morningstar_etfs_sample.csv", conn=conn
    )

    _, records = cur.executemany.call_args.args
    missing_rating_records = [r for r in records if r["fund_id"] in ("F003", "F006")]  # fixture rows with no rating
    assert len(missing_rating_records) == 2
    for record in missing_rating_records:
        assert record["sustainability_rating"] is None  # not float('nan')


def test_load_funds_postgres_writes_audit_log():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value

    load_funds_postgres.load(
        FIXTURES / "morningstar_mutual_funds_sample.csv", FIXTURES / "morningstar_etfs_sample.csv", conn=conn
    )

    audit_calls = [c for c in cur.execute.call_args_list if "audit_log" in c.args[0]]
    assert len(audit_calls) == 1


def test_load_esg_cosmos_upserts_one_doc_per_etf():
    container = MagicMock()

    count = load_esg_cosmos.load(
        FIXTURES / "etf_holdings_sample.csv", FIXTURES / "company_esg_ratings_sample.csv", container=container
    )

    assert count == 4
    assert container.upsert_item.call_count == 4
    upserted_ids = {c.args[0]["id"] for c in container.upsert_item.call_args_list}
    assert upserted_ids == {"GRNENERGY", "GLBESG50", "EUCLEAN", "WLDSUS"}
