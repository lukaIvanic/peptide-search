"""Search service - multi-source paper search with deduplication and observability."""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

from ..schemas import SearchItem

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


@dataclass
class SearchStats:
    """Statistics for a search operation."""
    total_results: int = 0
    deduplicated_results: int = 0
    sources_queried: int = 0
    sources_succeeded: int = 0
    sources_failed: int = 0
    errors: List[str] = field(default_factory=list)


def _norm_year(year_like) -> int | None:
    try:
        y = int(year_like)
        return y if 1800 <= y <= (_dt.datetime.utcnow().year + 1) else None
    except Exception:
        return None


def _normalize_doi(doi: Optional[str]) -> Optional[str]:
    """Normalize a DOI for deduplication."""
    if not doi:
        return None
    doi = doi.strip().lower()
    # Remove common prefixes
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "arxiv:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi


def _normalize_url(url: Optional[str]) -> Optional[str]:
    """Normalize a URL for deduplication."""
    if not url:
        return None
    url = url.strip().lower()
    # Remove trailing slashes and common tracking params
    url = url.rstrip("/")
    # Remove common query params
    if "?" in url:
        base, _ = url.split("?", 1)
        return base
    return url


def _dedupe_results(results: List[SearchItem]) -> List[SearchItem]:
    """Remove duplicate results based on DOI and URL."""
    seen_dois: set = set()
    seen_urls: set = set()
    deduped: List[SearchItem] = []
    
    for item in results:
        # Check DOI
        norm_doi = _normalize_doi(item.doi)
        if norm_doi and norm_doi in seen_dois:
            continue
        
        # Check URL
        norm_url = _normalize_url(item.url)
        if norm_url and norm_url in seen_urls:
            continue
        
        # Add to seen sets
        if norm_doi:
            seen_dois.add(norm_doi)
        if norm_url:
            seen_urls.add(norm_url)
        
        deduped.append(item)
    
    return deduped


# ---------------------------------------------------------------------------
# PubMed Central (PMC) - Free full-text articles
# ---------------------------------------------------------------------------
async def _resolve_pmc_pdf_url(client: httpx.AsyncClient, pmc_id: str) -> Optional[str]:
    """Use PMC OA service to retrieve a direct PDF link if available."""
    oa_url = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
    try:
        resp = await client.get(oa_url, params={"id": pmc_id})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        for record in root.findall("./records/record"):
            for link in record.findall("./links/link"):
                if link.attrib.get("format") == "pdf":
                    href = link.attrib.get("href")
                    if href:
                        return href
    except Exception as e:
        logger.debug(f"PMC PDF resolution failed for {pmc_id}: {e}")
        return None
    return None


async def search_pmc(query: str, retmax: int = 10) -> List[SearchItem]:
    """Search PubMed Central for open-access full-text articles."""
    esearch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    esummary = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    async with httpx.AsyncClient(timeout=30, headers=_BROWSER_HEADERS) as client:
        # Search PMC database (not pubmed)
        r1 = await client.get(
            esearch,
            params={"db": "pmc", "retmode": "json", "retmax": retmax, "term": query},
        )
        r1.raise_for_status()
        j1 = r1.json()
        ids = j1.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []

        # Get summaries
        r2 = await client.get(
            esummary,
            params={"db": "pmc", "retmode": "json", "id": ",".join(ids)},
        )
        r2.raise_for_status()
        j2 = r2.json()

        result: List[SearchItem] = []
        docs: Dict[str, dict] = j2.get("result", {})

        for pmcid in ids:
            s = docs.get(pmcid)
            if not s:
                continue

            title = s.get("title") or "(Untitled)"
            title = re.sub(r"<[^>]+>", "", title)

            authors = []
            for a in s.get("authors", []):
                name = a.get("name")
                if name:
                    authors.append(name)

            pubdate = s.get("pubdate", "") or s.get("epubdate", "")
            year = None
            if pubdate:
                match = re.search(r"(\d{4})", pubdate)
                if match:
                    year = _norm_year(int(match.group(1)))

            doi = None
            article_ids = s.get("articleids", [])
            for aid in article_ids:
                if aid.get("idtype") == "doi":
                    doi = aid.get("value")
                    break

            pmc_id = f"PMC{pmcid}" if not str(pmcid).startswith("PMC") else pmcid
            pdf_url = await _resolve_pmc_pdf_url(client, pmc_id)
            if not pdf_url:
                pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/pdf/{pmc_id}.pdf"
            html_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/"

            result.append(
                SearchItem(
                    title=title,
                    doi=doi,
                    url=html_url,
                    pdf_url=pdf_url,
                    source="pmc",
                    year=year,
                    authors=authors,
                )
            )
        return result


# ---------------------------------------------------------------------------
# arXiv - Free preprints
# ---------------------------------------------------------------------------
async def search_arxiv(query: str, max_results: int = 10) -> List[SearchItem]:
    """Search arXiv for preprints (all freely accessible)."""
    url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    async with httpx.AsyncClient(timeout=30, headers=_BROWSER_HEADERS) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        xml_data = resp.text

    root = ET.fromstring(xml_data)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    result: List[SearchItem] = []
    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else "(Untitled)"

        authors = []
        for author in entry.findall("atom:author", ns):
            name_el = author.find("atom:name", ns)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        published_el = entry.find("atom:published", ns)
        year = None
        if published_el is not None and published_el.text:
            match = re.search(r"(\d{4})", published_el.text)
            if match:
                year = _norm_year(int(match.group(1)))

        html_url = None
        pdf_url = None
        for link in entry.findall("atom:link", ns):
            href = link.get("href", "")
            link_type = link.get("type", "")
            link_title = link.get("title", "")

            if link_title == "pdf" or "pdf" in link_type:
                pdf_url = href
            elif link.get("rel") == "alternate":
                html_url = href

        id_el = entry.find("atom:id", ns)
        arxiv_id = None
        if id_el is not None and id_el.text:
            match = re.search(r"arxiv.org/abs/(.+)", id_el.text)
            if match:
                arxiv_id = match.group(1)
                if not pdf_url:
                    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                if not html_url:
                    html_url = f"https://arxiv.org/abs/{arxiv_id}"

        if html_url:
            result.append(
                SearchItem(
                    title=title,
                    doi=f"arXiv:{arxiv_id}" if arxiv_id else None,
                    url=html_url,
                    pdf_url=pdf_url,
                    source="arxiv",
                    year=year,
                    authors=authors,
                )
            )

    return result


# ---------------------------------------------------------------------------
# Europe PMC - Another free full-text source
# ---------------------------------------------------------------------------
async def search_europe_pmc(query: str, page_size: int = 10) -> List[SearchItem]:
    """Search Europe PMC for open-access articles."""
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    params = {
        "query": query,
        "format": "json",
        "pageSize": page_size,
        "resultType": "core",
    }

    async with httpx.AsyncClient(timeout=30, headers=_BROWSER_HEADERS) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    result: List[SearchItem] = []
    for item in data.get("resultList", {}).get("result", []):
        title = item.get("title", "(Untitled)")
        title = re.sub(r"<[^>]+>", "", title)

        authors = []
        author_list = item.get("authorList", {}).get("author", [])
        for a in author_list:
            full_name = a.get("fullName")
            if full_name:
                authors.append(full_name)

        year = _norm_year(item.get("pubYear"))
        doi = item.get("doi")

        pmcid = item.get("pmcid")
        pmid = item.get("pmid")

        html_url = None
        pdf_url = None

        if pmcid:
            html_url = f"https://europepmc.org/article/PMC/{pmcid}"
            pdf_url = f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf"
        elif pmid:
            html_url = f"https://europepmc.org/article/MED/{pmid}"

        is_open_access = item.get("isOpenAccess") == "Y"

        if html_url and is_open_access:
            result.append(
                SearchItem(
                    title=title,
                    doi=doi,
                    url=html_url,
                    pdf_url=pdf_url,
                    source="europepmc",
                    year=year,
                    authors=authors,
                )
            )

    return result


# ---------------------------------------------------------------------------
# Semantic Scholar - Often links to open PDFs
# ---------------------------------------------------------------------------
async def search_semantic_scholar(query: str, limit: int = 10) -> List[SearchItem]:
    """Search Semantic Scholar (often has open access PDFs)."""
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": limit,
        "fields": "title,authors,year,externalIds,openAccessPdf,url",
    }

    async with httpx.AsyncClient(timeout=30, headers=_BROWSER_HEADERS) as client:
        resp = await client.get(url, params=params)
        if resp.status_code == 429:
            logger.warning("Semantic Scholar rate limited (429)")
            raise RuntimeError("Semantic Scholar rate limited")
        resp.raise_for_status()
        data = resp.json()

    result: List[SearchItem] = []
    for item in data.get("data", []):
        title = item.get("title", "(Untitled)")

        authors = []
        for a in item.get("authors", []):
            name = a.get("name")
            if name:
                authors.append(name)

        year = _norm_year(item.get("year"))

        ext_ids = item.get("externalIds", {}) or {}
        doi = ext_ids.get("DOI")

        oa_pdf = item.get("openAccessPdf", {}) or {}
        pdf_url = oa_pdf.get("url")

        html_url = item.get("url")

        # Only include if we have an open access PDF
        if pdf_url and html_url:
            result.append(
                SearchItem(
                    title=title,
                    doi=doi,
                    url=html_url,
                    pdf_url=pdf_url,
                    source="semanticscholar",
                    year=year,
                    authors=authors,
                )
            )

    return result


# ---------------------------------------------------------------------------
# Combined search across all free sources
# ---------------------------------------------------------------------------

# Priority order for sources (lower = higher priority, shown first)
SOURCE_PRIORITY = {
    "europepmc": 0,   # Best: direct PDF URLs that work reliably
    "arxiv": 1,       # Good: direct PDF URLs
    "semanticscholar": 2,  # Good: has openAccessPdf field
    "pmc": 3,         # Sometimes has issues with PDF URLs
}


async def search_all_free_sources(
    query: str,
    per_source: int = 5,
) -> List[SearchItem]:
    """
    Search all free-access sources and combine results.
    
    Returns deduplicated results sorted by source reliability.
    Logs errors instead of silently dropping them.
    """
    stats = SearchStats()
    
    # Define search tasks
    search_tasks = [
        ("pmc", search_pmc(query, retmax=per_source)),
        ("arxiv", search_arxiv(query, max_results=per_source)),
        ("europepmc", search_europe_pmc(query, page_size=per_source)),
        ("semanticscholar", search_semantic_scholar(query, limit=per_source)),
    ]
    
    stats.sources_queried = len(search_tasks)
    
    # Run all searches in parallel
    results = await asyncio.gather(
        *[task for _, task in search_tasks],
        return_exceptions=True,
    )
    
    combined: List[SearchItem] = []
    for (source_name, _), result in zip(search_tasks, results):
        if isinstance(result, Exception):
            error_msg = f"{source_name}: {type(result).__name__}: {result}"
            stats.errors.append(error_msg)
            stats.sources_failed += 1
            logger.warning(f"Search source failed - {error_msg}")
        elif isinstance(result, list):
            combined.extend(result)
            stats.sources_succeeded += 1
            logger.debug(f"Search source {source_name} returned {len(result)} results")
    
    stats.total_results = len(combined)
    
    # Deduplicate
    combined = _dedupe_results(combined)
    stats.deduplicated_results = len(combined)
    
    # Sort by source priority
    combined.sort(key=lambda item: SOURCE_PRIORITY.get(item.source, 99))
    
    # Log summary
    logger.info(
        f"Search completed: {stats.deduplicated_results}/{stats.total_results} results "
        f"({stats.sources_succeeded}/{stats.sources_queried} sources succeeded)"
    )
    if stats.errors:
        logger.warning(f"Search errors: {stats.errors}")
    
    return combined


async def search_all_free_sources_with_stats(
    query: str,
    per_source: int = 5,
) -> tuple[List[SearchItem], SearchStats]:
    """
    Search all sources and return both results and statistics.
    
    Useful for exposing search health to the API.
    """
    stats = SearchStats()
    
    search_tasks = [
        ("pmc", search_pmc(query, retmax=per_source)),
        ("arxiv", search_arxiv(query, max_results=per_source)),
        ("europepmc", search_europe_pmc(query, page_size=per_source)),
        ("semanticscholar", search_semantic_scholar(query, limit=per_source)),
    ]
    
    stats.sources_queried = len(search_tasks)
    
    results = await asyncio.gather(
        *[task for _, task in search_tasks],
        return_exceptions=True,
    )
    
    combined: List[SearchItem] = []
    for (source_name, _), result in zip(search_tasks, results):
        if isinstance(result, Exception):
            error_msg = f"{source_name}: {type(result).__name__}: {result}"
            stats.errors.append(error_msg)
            stats.sources_failed += 1
        elif isinstance(result, list):
            combined.extend(result)
            stats.sources_succeeded += 1
    
    stats.total_results = len(combined)
    combined = _dedupe_results(combined)
    stats.deduplicated_results = len(combined)
    combined.sort(key=lambda item: SOURCE_PRIORITY.get(item.source, 99))
    
    return combined, stats
