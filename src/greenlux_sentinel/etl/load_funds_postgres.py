"""Tier 1 loader — European Funds dataset from Morningstar (Kaggle CSV) -> Postgres.

Source: https://www.kaggle.com/datasets/stefanoleone992/european-funds-dataset-from-morningstar
See docs/DATA.md#datasets for the expected shape (~57.6k mutual funds + ~9.5k ETFs).

TODO(Phase 1):
    - Confirm real column names against the downloaded CSV in notebooks/01_data_profiling
    - Load into the schema defined in db/schema.sql
    - Do NOT add a literal "sfdr_article" column — see docs/DATA.md#ground-truth-methodology
"""

from __future__ import annotations

from pathlib import Path


def load(csv_path: Path) -> int:
    """Load the Morningstar funds CSV into Postgres. Returns row count. Not yet implemented."""
    raise NotImplementedError("Phase 1 — see docs/ROADMAP.md")
