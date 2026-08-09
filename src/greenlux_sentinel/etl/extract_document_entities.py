"""Extracts entity tags from the Phase 8a document corpus (fetch_fund_documents.py) — lightweight
LLM-based tagging, not a graph database or the Microsoft `graphrag` library. See
docs/PROGRESS_LOG.md's Phase 8a entry for why: an ~11-document, 5-fund corpus has no hidden
entity-relationship structure worth discovering via full graph construction + community
detection — the real structure (which fund, which doc type, which regulation) is already known
before ingestion runs. What a real GraphRAG-style system buys over plain chunk search is
*entity-aware* retrieval; this module gets that cheaply by tagging each chunk with the fund
names/ISINs/regulation-article references/SFDR terms it actually mentions, extracted once per
document (not per chunk, to keep the LLM call count small) via the same AzureChatOpenAI pattern
every other agent in this repo already uses (see dashboard_agent.py's build_dax()).

Pipeline: PDF -> extracted text (pypdf) -> paragraph-packed chunks (~1200 chars) -> one LLM call
per document tags every chunk from that document with the same entity list. Output is a plain
list[dict] — no parquet, no graph store. load_documents_search.py reads this shape directly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

_MAX_CHUNK_CHARS = 1200
# The two umbrella prospectuses in fetch_fund_documents.FUND_DOCUMENTS cover dozens of sub-funds
# beyond the 5 this project actually tracks (iShares IV/VII plc are full legal prospectuses,
# 2.85M+ characters observed for iShares IV plc alone -- confirmed while building this module).
# Capped here, not left unbounded, for the same reason GLEIF lookups are capped elsewhere
# (etl_agent._GLEIF_LOOKUP_LIMIT): this is a deliberately small, portfolio-scoped corpus, not "the
# whole legal document regardless of size." The front section of a UCITS umbrella prospectus
# (fund structure, general risk factors) is shared across every sub-fund; per-sub-fund
# supplements deep in the document for funds outside this project's scope aren't worth the
# embedding cost.
_MAX_DOCUMENT_CHARS = 60_000

_ENTITY_SYSTEM_PROMPT = """Read this excerpt from a fund/regulatory disclosure document. List the \
specific entities it mentions: fund names, ISINs/tickers, regulation or article references (e.g. \
"SFDR Article 8", "Regulation (EU) 2019/2088"), and named indices. Reply with ONLY a JSON array \
of short strings, nothing else -- no markdown, no explanation. If none, reply with [].

Excerpt (first 4000 characters):
{excerpt}
"""

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _default_llm() -> BaseChatModel:
    from langchain_openai import AzureChatOpenAI

    from greenlux_sentinel.config import get_settings

    settings = get_settings()
    return AzureChatOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=settings.azure_openai_deployment,
        api_version=settings.azure_openai_api_version,
    )


def extract_text(pdf_path: Path, max_chars: int | None = None) -> str:
    """Extract raw text from one PDF, page by page, via pypdf. If max_chars is given, stops
    reading further pages once it's reached instead of parsing the whole file and discarding the
    rest -- some real documents in this corpus run to thousands of pages (see
    _MAX_DOCUMENT_CHARS's docstring), and parsing pages nobody will read is pure waste."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    total = 0
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
        total += len(text)
        if max_chars is not None and total >= max_chars:
            break
    return "\n\n".join(pages)


def _split_oversized_block(block: str, max_chars: int) -> list[str]:
    """A single paragraph-ish block bigger than max_chars on its own (common with PDF text
    extraction, which doesn't reliably preserve paragraph breaks -- see build_document_records'
    docstring) gets greedily packed on sentence boundaries instead of returned whole."""
    sentences = re.split(r"(?<=[.!?])\s+", block)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > max_chars:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        parts.append(current)
    return parts


def chunk_text(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    """Pack text into ~max_chars chunks on paragraph boundaries, falling back to sentence
    boundaries for any block still oversized on its own (see _split_oversized_block)."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_oversized_block(paragraph, max_chars))
        elif current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def extract_entities(text: str, llm: BaseChatModel | None = None) -> list[str]:
    """One LLM call over (a truncated prefix of) a document's full text -> the entity tags it
    mentions. Falls back to an empty list on an unparseable reply rather than failing the whole
    ingestion run over one document's tagging."""
    llm = llm or _default_llm()
    response = llm.invoke([("system", _ENTITY_SYSTEM_PROMPT.format(excerpt=text[:4000]))])
    match = _JSON_ARRAY_RE.search(str(response.content).strip())
    if not match:
        return []
    try:
        entities = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [str(e) for e in entities if isinstance(e, str)]


def build_document_records(
    source_dir: Path,
    documents: list[tuple[str, str, str | None, str]],
    llm: BaseChatModel | None = None,
) -> list[dict[str, Any]]:
    """For each (filename, doc_type, isin, source_url) tuple (fetch_fund_documents.FUND_DOCUMENTS'
    shape), extract text, chunk it, and tag every chunk with that document's entity list. Returns
    a flat list of chunk records ready for load_documents_search.py:
    {"id": str, "content": str, "doc_id": str, "doc_type": str, "isin": str | None,
     "entity_names": list[str], "source_url": str, "chunk_index": int}."""
    llm = llm or _default_llm()
    records: list[dict[str, Any]] = []
    for filename, doc_type, isin, source_url in documents:
        doc_id = Path(filename).stem
        text = extract_text(source_dir / filename, max_chars=_MAX_DOCUMENT_CHARS)[:_MAX_DOCUMENT_CHARS]
        entities = extract_entities(text, llm=llm)
        for chunk_index, chunk in enumerate(chunk_text(text)):
            records.append(
                {
                    "id": f"{doc_id}_{chunk_index}",
                    "content": chunk,
                    "doc_id": doc_id,
                    "doc_type": doc_type,
                    "isin": isin,
                    "entity_names": entities,
                    "source_url": source_url,
                    "chunk_index": chunk_index,
                }
            )
    return records
