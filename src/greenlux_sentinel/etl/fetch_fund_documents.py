"""Fetches real, issuer-published disclosure documents for the same five issuer-verified UCITS
ETFs as fetch_verified_holdings.py, plus a small, hand-curated set of general SFDR/CSSF regulatory
PDFs — the document corpus for the Phase 8 evidence agent (docs/DATA.md#document-corpus).

Every URL below was checked live during Phase 8a (real HTTP GET, real `application/pdf` response)
before being hardcoded here, the same due-diligence style as fetch_verified_holdings.py's own
CSV URLs. Two things worth knowing before touching this list:

  1. The per-fund PRIIPS KID (the EU successor to the old UCITS KIID, required since 2023) already
     contains the SFDR sustainability summary for these Article 8 products -- there is no separate
     downloadable "SFDR pre-contractual annex" PDF per fund on iShares' site. Classify the KID PDF
     as doc_type="kiid"; don't invent a fourth doc_type for a document that doesn't exist.
  2. The prospectus is per *umbrella company*, not per fund -- iShares IV plc covers SUAS/SASU
     (confirmed by cross-referencing Fidelity's factsheet URLs, which embed the umbrella name) and,
     by inference from sharing the same 2018-2019 SRI/ESG-factor launch wave, SUSW/MVEA too (not
     independently confirmed per-ISIN -- flagged here rather than silently assumed). CSSPX is
     iShares VII plc (confirmed the same way). So five funds map to only two prospectus PDFs.
"""

from __future__ import annotations

from pathlib import Path

import httpx

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

# EUR-Lex serves its PDF export as a 202-with-empty-body unless Accept/Accept-Language headers
# look like a real browser request -- confirmed live during Phase 8a.
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/pdf,text/html,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# (output filename, doc_type, fund_id-scoping ISIN or None for general docs, source URL).
# doc_type in {"kiid", "prospectus", "regulation", "cssf_guidance"} -- see db/schema.sql's
# document_citations.doc_type check constraint.
FUND_DOCUMENTS: list[tuple[str, str, str | None, str]] = [
    (
        "kiid_SUAS_ie00byvjrr92.pdf",
        "kiid",
        "IE00BYVJRR92",
        (
            "https://www.blackrock.com/ch/individual/en/literature/kiid/"
            "eu_priips-ishares-msci-usa-sri-ucits-etf-usd-acc-ch-ie00byvjrr92-en.pdf"
        ),
    ),
    (
        "kiid_SASU_ie00bfnm3g45.pdf",
        "kiid",
        "IE00BFNM3G45",
        (
            "https://www.blackrock.com/ch/individual/en/literature/kiid/"
            "eu_priips-ishares-msci-usa-screened-ucits-etf-usd-acc-ch-ie00bfnm3g45-en.pdf"
        ),
    ),
    (
        "kiid_SUSW_ie00bdzztm54.pdf",
        "kiid",
        "IE00BDZZTM54",
        (
            "https://www.blackrock.com/ch/individual/en/literature/kiid/"
            "eu_priips-ishares-msci-world-sri-ucits-etf-usd-dist-ch-ie00bdzztm54-en.pdf"
        ),
    ),
    (
        "kiid_MVEA_ie00bkvl7331.pdf",
        "kiid",
        "IE00BKVL7331",
        (
            "https://www.blackrock.com/ch/individual/en/literature/kiid/"
            "eu_priips-ishares-edge-msci-usa-minimum-volatility-advanced-ucits-etf-usd-acc-ch-"
            "ie00bkvl7331-en.pdf"
        ),
    ),
    (
        "kiid_CSSPX_ie00b5bmr087.pdf",
        "kiid",
        "IE00B5BMR087",
        (
            "https://www.blackrock.com/ch/individual/en/literature/kiid/"
            "eu_priips-ishares-core-sp-500-ucits-etf-usd-acc-ch-ie00b5bmr087-en.pdf"
        ),
    ),
    (
        # Covers SUAS (IE00BYVJRR92) and SASU (IE00BFNM3G45) confirmed; SUSW/MVEA by inference
        # -- see module docstring point 2. fund_id column left None: this one PDF is shared.
        "prospectus_ishares_iv_plc.pdf",
        "prospectus",
        None,
        "https://www.blackrock.com/lu/individual/literature/prospectus/ishares-iv-plc-prospectus-en.pdf",
    ),
    (
        # Covers CSSPX (IE00B5BMR087).
        "prospectus_ishares_vii_plc.pdf",
        "prospectus",
        None,
        "https://www.blackrock.com/lu/individual/literature/prospectus/ishares-vii-plc-prospectus-en.pdf",
    ),
    (
        "sfdr_regulation_2019_2088.pdf",
        "regulation",
        None,
        "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32019R2088",
    ),
    (
        "sfdr_rts_2022_1288.pdf",
        "regulation",
        None,
        "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32022R1288",
    ),
    (
        "cssf_faq_sfdr.pdf",
        "cssf_guidance",
        None,
        "https://www.cssf.lu/wp-content/uploads/FAQ-SFDR.pdf",
    ),
    (
        # CSSF Circular 26/905 -- the underlying document behind "The CSSF's 2026 supervisory
        # priorities in the area of sustainable finance" (docs/DATA.md#why-this-topic already
        # cites this priority conceptually; this is the actual PDF).
        "cssf_circular_26_905_sustainable_finance_priorities.pdf",
        "cssf_guidance",
        None,
        "https://www.cssf.lu/wp-content/uploads/cssf26_905_eng.pdf",
    ),
]


def fetch_all(dest_dir: Path) -> list[Path]:
    """Download every document in FUND_DOCUMENTS into dest_dir. Returns the paths written."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=30.0) as client:
        for filename, _doc_type, _isin, url in FUND_DOCUMENTS:
            response = client.get(url)
            response.raise_for_status()
            out_path = dest_dir / filename
            out_path.write_bytes(response.content)
            written.append(out_path)
    return written


if __name__ == "__main__":
    paths = fetch_all(Path(__file__).resolve().parents[3] / "data" / "raw" / "document_corpus")
    for p in paths:
        print(f"wrote {p}")
