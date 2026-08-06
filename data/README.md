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

## `data/raw/verified_holdings/`

Not from Kaggle. Five real, issuer-published UCITS ETF holdings files, fetched by running:

```
python -m greenlux_sentinel.etl.fetch_verified_holdings
```

See [docs/DATA.md#tier-2-verified-holdings-phase-2-correction](../docs/DATA.md#tier-2-verified-holdings-phase-2-correction)
for why this exists — the original Top 100 ETF holdings dataset has no fund in Tier 1, so this
fills in a small, real, ISIN-linked subset instead. Re-run the script any time to refresh to the
current day's holdings.

`data/processed/` holds intermediate reshaped files (e.g. the ETF-holdings/ESG join before it's
loaded to Cosmos DB) — also gitignored, regenerate via `src/greenlux_sentinel/etl/`.

See [docs/DATA.md](../docs/DATA.md) for the full dataset rationale and the two-tier data design.
