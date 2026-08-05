# notebooks/

Phase 1 starts with `01_data_profiling.ipynb` (not yet created) — profiling the real downloaded
CSVs against the assumptions in [docs/DATA.md](../docs/DATA.md):

- Actual column names/types in the Morningstar funds CSV vs. `db/schema.sql`
- Null rates on `domicile_country` and `sustainability_rating`
- Ticker/name overlap between the ETF holdings dataset and the company ESG ratings dataset
  (this determines how much of the Tier 2 join is actually usable)

Findings here should update `docs/DATA.md` and `db/schema.sql` directly — treat the current
schema as a design intent, not a confirmed contract, until this notebook exists and has run.
