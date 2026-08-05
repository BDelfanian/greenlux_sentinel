"""Tier 2 loader — ETF holdings + company ESG ratings -> reshaped JSON -> Cosmos DB.

Sources:
    https://www.kaggle.com/datasets/jackstev298/full-holdings-data-for-the-top-100-etfs
    https://www.kaggle.com/datasets/alistairking/public-company-esg-ratings-dataset

Joins the two by ticker/company name into one nested JSON document per ETF holding,
written to the Cosmos DB NoSQL/Core API container (NOT Gremlin — see CLAUDE.md decision #3).

TODO(Phase 1):
    - Confirm ticker overlap between the two datasets in notebooks/01_data_profiling
      (this determines how much of the Tier 2 join is actually usable)
    - Define the nested document shape (per-ETF -> holdings[] -> esg_scores)
"""

from __future__ import annotations

from pathlib import Path


def load(holdings_csv: Path, esg_csv: Path) -> int:
    """Reshape and load into Cosmos DB. Returns document count. Not yet implemented."""
    raise NotImplementedError("Phase 1 — see docs/ROADMAP.md")
