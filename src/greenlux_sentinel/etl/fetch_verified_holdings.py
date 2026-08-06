"""Fetches real, issuer-published holdings for a small set of UCITS ETFs that are *both* in the
Tier 1 Morningstar universe (real claimed sustainability rating) *and* have real security-level
holdings (Tier 2) — see docs/DATA.md#tier-2-verified-holdings for why this exists.

Background: the original Tier 2 source (Kaggle "Full Holdings Data for the Top 100 ETFs") turned
out to be a set of plain US-listed index/bond trackers with zero overlap with the Tier 1 Morningstar
**European** funds table and no sustainability claim of their own — so no fund in that dataset could
ever get a real claimed-vs-holdings-implied comparison. This module instead pulls real, current
holdings directly from BlackRock/iShares' public per-fund CSV export for five UCITS ETFs that *are*
in Tier 1, span a real Morningstar-rating range (3-5 globes), and are large-cap US/global equity
funds — chosen because their holdings have strong ticker overlap with the (US-centric)
public_company_esg_ratings.csv dataset (52-84% by weight, vs. ~14% for the original Top 100 set).

No API key or auth required — these are the same CSV exports available to any visitor via the
"Download Holdings" link on each fund's public product page. Re-running this script re-fetches the
current day's holdings (funds drift slowly, but this is not a point-in-time archive).
"""

from __future__ import annotations

from pathlib import Path

import httpx

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

# (output filename, ISIN, iShares ticker, holdings CSV URL). ISIN is the join key back to
# Tier 1's funds.isin. CSSPX has no ESG claim of its own (plain S&P 500 tracker) — kept as a
# no-claim control, not part of the greenwashing comparison itself.
VERIFIED_ETFS: list[tuple[str, str, str, str]] = [
    (
        "verified_SUAS_ishares_msci_usa_sri.csv",
        "IE00BYVJRR92",
        "SUAS",
        (
            "https://www.ishares.com/ch/individual/en/products/283565/"
            "ishares-sustainable-msci-usa-sri-ucits-etf/1495092304805.ajax"
            "?fileType=csv&fileName=SUAS_holdings&dataType=fund"
        ),
    ),
    (
        "verified_SASU_ishares_msci_usa_esg_screened.csv",
        "IE00BFNM3G45",
        "SASU",
        (
            "https://www.ishares.com/ch/individual/en/products/305356/"
            "fund/1495092304805.ajax"
            "?fileType=csv&fileName=SASU_holdings&dataType=fund"
        ),
    ),
    (
        "verified_SUSW_ishares_msci_world_sri.csv",
        "IE00BDZZTM54",
        "SUSW",
        (
            "https://www.ishares.com/ch/individual/en/products/290846/"
            "fund/1495092304805.ajax"
            "?fileType=csv&fileName=SUSW_holdings&dataType=fund"
        ),
    ),
    (
        "verified_MVEA_ishares_edge_msci_usa_minvol_esg.csv",
        "IE00BKVL7331",
        "MVEA",
        (
            "https://www.ishares.com/ch/individual/en/products/313214/"
            "fund/1495092304805.ajax"
            "?fileType=csv&fileName=MVEA_holdings&dataType=fund"
        ),
    ),
    (
        "verified_CSSPX_ishares_core_sp500_control.csv",
        "IE00B5BMR087",
        "CSSPX",
        (
            "https://www.ishares.com/ch/individual/en/products/253743/"
            "ishares-sp-500-b-ucits-etf-acc-fund/1495092304805.ajax"
            "?fileType=csv&fileName=CSSPX_holdings&dataType=fund"
        ),
    ),
]


def fetch_all(dest_dir: Path) -> list[Path]:
    """Download each verified ETF's current holdings CSV into dest_dir. Returns the paths written."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with httpx.Client(headers={"User-Agent": _USER_AGENT}, follow_redirects=True, timeout=30.0) as client:
        for filename, _isin, _ticker, url in VERIFIED_ETFS:
            response = client.get(url)
            response.raise_for_status()
            out_path = dest_dir / filename
            out_path.write_bytes(response.content)
            written.append(out_path)
    return written


if __name__ == "__main__":
    paths = fetch_all(Path(__file__).resolve().parents[3] / "data" / "raw" / "verified_holdings")
    for p in paths:
        print(f"wrote {p}")
