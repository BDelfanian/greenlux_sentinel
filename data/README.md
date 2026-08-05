# data/

Raw and processed data files are **not committed** (see `.gitignore`) — Kaggle's terms of use and
plain repo hygiene both argue against checking in third-party CSVs.

## To populate `data/raw/`

Download each dataset and place it at the exact filename below — `etl/` reads these paths
directly. The Kaggle downloads don't arrive with these names (e.g. the ESG ratings dataset
downloads as a bare `data.csv`), so rename after extracting:

| File | Source |
|---|---|
| `data/raw/morningstar_european_mutual_funds.csv` | [European Funds dataset from Morningstar](https://www.kaggle.com/datasets/stefanoleone992/european-funds-dataset-from-morningstar) — "Mutual Funds" file |
| `data/raw/morningstar_european_etfs.csv` | Same dataset — "ETFs" file |
| `data/raw/top100_etf_holdings.csv` | [Full Holdings Data for the Top 100 ETFs](https://www.kaggle.com/datasets/jackstev298/full-holdings-data-for-the-top-100-etfs) |
| `data/raw/public_company_esg_ratings.csv` | [Public Company ESG Ratings Dataset](https://www.kaggle.com/datasets/alistairking/public-company-esg-ratings-dataset) — downloads as `data.csv`, rename it |

GLEIF data is not downloaded — it's fetched live via the GLEIF MCP server at runtime.

`data/processed/` holds intermediate reshaped files (e.g. the ETF-holdings/ESG join before it's
loaded to Cosmos DB) — also gitignored, regenerate via `src/greenlux_sentinel/etl/`.

See [docs/DATA.md](../docs/DATA.md) for the full dataset rationale and the two-tier data design.
