# data/

Raw and processed data files are **not committed** (see `.gitignore`) — Kaggle's terms of use and
plain repo hygiene both argue against checking in third-party CSVs.

## To populate `data/raw/`

1. Download and extract into `data/raw/`:
   - [European Funds dataset from Morningstar](https://www.kaggle.com/datasets/stefanoleone992/european-funds-dataset-from-morningstar)
   - [Full Holdings Data for the Top 100 ETFs](https://www.kaggle.com/datasets/jackstev298/full-holdings-data-for-the-top-100-etfs)
   - [Public Company ESG Ratings Dataset](https://www.kaggle.com/datasets/alistairking/public-company-esg-ratings-dataset)
2. GLEIF data is not downloaded — it's fetched live via the GLEIF MCP server at runtime.

`data/processed/` holds intermediate reshaped files (e.g. the ETF-holdings/ESG join before it's
loaded to Cosmos DB) — also gitignored, regenerate via `src/greenlux_sentinel/etl/`.

See [docs/DATA.md](../docs/DATA.md) for the full dataset rationale and the two-tier data design.
