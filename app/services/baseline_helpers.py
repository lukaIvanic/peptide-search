from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from ..baseline.loader import (
    get_case,
    list_cases,
    load_index,
    normalize_doi,
    resolve_all_local_pdf_paths,
)
from ..integrations.document import DocumentExtractor
from ..persistence.models import BaselineCaseRun, ExtractionRun, RunStatus
from ..persistence.repository import BaselineCaseRunRepository
from ..schemas import (
    BaselineCase,
    BaselineDatasetInfo,
    BaselineRunSummary,
    SearchItem,
)
from ..services.failure_reason import normalize_failure_reason
from ..services.search_service import search_all_free_sources
from ..services.upload_store import store_upload
from .serializers import iso_z

logger = logging.getLogger(__name__)


def baseline_title(case: BaselineCase) -> str:
    sequence = case.sequence or "Unknown sequence"
    return f"Baseline {case.dataset}: {sequence}"


def baseline_dataset_infos(dataset_filter: Optional[str] = None) -> List[BaselineDatasetInfo]:
    index = load_index()
    datasets: List[BaselineDatasetInfo] = []
    for entry in index.get("datasets", []):
        if dataset_filter and entry.get("id") != dataset_filter:
            continue
        datasets.append(
            BaselineDatasetInfo(
                id=entry.get("id"),
                label=entry.get("label"),
                description=entry.get("description"),
                count=entry.get("count", 0),
            )
        )
    return datasets


def build_baseline_run_summary(run: ExtractionRun) -> BaselineRunSummary:
    normalized_failure = None
    if run.status == RunStatus.FAILED.value:
        normalized_failure = normalize_failure_reason(run.failure_reason)
    return BaselineRunSummary(
        run_id=run.id,
        paper_id=run.paper_id,
        status=run.status,
        failure_reason=normalized_failure,
        created_at=iso_z(run.created_at),
        model_provider=run.model_provider,
        model_name=run.model_name,
        batch_id=run.batch_id,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        extraction_time_ms=run.extraction_time_ms,
    )


def select_baseline_result(results: List[SearchItem], doi: Optional[str]) -> Optional[SearchItem]:
    if not results:
        return None
    if doi:
        needle = doi.strip().lower()
        for item in results:
            if item.doi and item.doi.strip().lower() == needle:
                return item
        return None
    return results[0]


def resolve_local_pdf_source(
    case: BaselineCase,
    local_upload_cache: Optional[Dict[str, Any]] = None,
) -> Optional[SearchItem]:
    """Resolve local PDFs for a baseline case, including supplementary PDFs.

    The cache stores `{doi: {"primary": url, "all": [url, ...]}}` to reuse uploads.
    """
    normalized = normalize_doi(case.doi)
    if not normalized:
        return None

    if local_upload_cache is not None and normalized in local_upload_cache:
        cached = local_upload_cache[normalized]
        if isinstance(cached, str):
            return SearchItem(
                title=baseline_title(case),
                doi=case.doi,
                url=case.paper_url,
                pdf_url=cached,
                source="local",
                year=None,
                authors=[],
            )
        return SearchItem(
            title=baseline_title(case),
            doi=case.doi,
            url=case.paper_url,
            pdf_url=cached.get("primary"),
            pdf_urls=cached.get("all"),
            source="local",
            year=None,
            authors=[],
        )

    all_paths = resolve_all_local_pdf_paths(case.doi)
    if not all_paths:
        return None

    all_upload_urls: List[str] = []
    for local_path in all_paths:
        try:
            content = local_path.read_bytes()
            upload_url = store_upload(content, local_path.name)
            all_upload_urls.append(upload_url)
        except Exception as exc:
            logger.warning("Failed to read local PDF %s for DOI %s: %s", local_path, case.doi, exc)

    if not all_upload_urls:
        return None

    primary_url = all_upload_urls[0]

    if local_upload_cache is not None:
        local_upload_cache[normalized] = {
            "primary": primary_url,
            "all": all_upload_urls,
        }

    return SearchItem(
        title=baseline_title(case),
        doi=case.doi,
        url=case.paper_url,
        pdf_url=primary_url,
        pdf_urls=all_upload_urls if len(all_upload_urls) > 1 else None,
        source="local",
        year=None,
        authors=[],
    )


async def resolve_baseline_source(
    case: BaselineCase,
    local_upload_cache: Optional[Dict[str, Any]] = None,
    local_only: bool = False,
) -> Optional[SearchItem]:
    local_source = resolve_local_pdf_source(case, local_upload_cache)
    if local_source:
        return local_source
    if local_only:
        return None

    if case.pdf_url and DocumentExtractor.looks_like_pdf_url(case.pdf_url):
        return SearchItem(
            title=baseline_title(case),
            doi=case.doi,
            url=case.paper_url or case.pdf_url,
            pdf_url=case.pdf_url,
            source="baseline",
            year=None,
            authors=[],
        )

    if case.paper_url:
        return SearchItem(
            title=baseline_title(case),
            doi=case.doi,
            url=case.paper_url,
            pdf_url=case.paper_url if DocumentExtractor.looks_like_pdf_url(case.paper_url) else None,
            source="baseline",
            year=None,
            authors=[],
        )

    query = case.doi or case.pubmed_id
    if not query:
        return None
    results = await search_all_free_sources(query, per_source=3)
    return select_baseline_result(results, case.doi)


def normalize_case_doi(value: Optional[str]) -> Optional[str]:
    normalized = normalize_doi(value)
    if not normalized:
        return None
    return re.sub(r"/v\d+$", "", normalized)


def get_case_paper_key(case: BaselineCase) -> str:
    """Stable paper identity key used for UI grouping and batch totals."""
    normalized_doi = normalize_doi(case.doi)
    if normalized_doi:
        return f"doi:{normalized_doi}"
    if case.pubmed_id:
        return f"pubmed:{case.pubmed_id.strip()}"
    if case.paper_url:
        return f"url:{case.paper_url.strip()}"
    return f"case:{case.id}"


def get_source_key(case: BaselineCase, resolved_url: Optional[str]) -> Optional[str]:
    source_url = resolved_url or case.pdf_url or case.paper_url
    if source_url:
        return f"url:{source_url.strip()}"
    normalized = normalize_case_doi(case.doi)
    if normalized:
        return f"doi:{normalized}"
    if case.pubmed_id:
        return f"pubmed:{case.pubmed_id.strip()}"
    return None


def get_source_keys(case: BaselineCase, resolved_url: Optional[str]) -> List[str]:
    keys: List[str] = []
    source_url = resolved_url or case.pdf_url or case.paper_url
    if source_url:
        keys.append(f"url:{source_url.strip()}")
    normalized = normalize_case_doi(case.doi)
    if normalized:
        keys.append(f"doi:{normalized}")
    if case.pubmed_id:
        keys.append(f"pubmed:{case.pubmed_id.strip()}")
    return keys


def get_latest_baseline_run(session: Session, case_id: str) -> Optional[ExtractionRun]:
    stmt = (
        select(ExtractionRun)
        .join(BaselineCaseRun, BaselineCaseRun.run_id == ExtractionRun.id)
        .where(BaselineCaseRun.baseline_case_id == case_id)
        .order_by(ExtractionRun.created_at.desc())
        .limit(1)
    )
    run = session.exec(stmt).first()
    if run:
        return run
    stmt = (
        select(ExtractionRun)
        .where(ExtractionRun.baseline_case_id == case_id)
        .order_by(ExtractionRun.created_at.desc())
        .limit(1)
    )
    return session.exec(stmt).first()


def get_latest_baseline_runs(
    session: Session,
    case_ids: List[str],
) -> dict[str, BaselineRunSummary]:
    latest_by_case: dict[str, BaselineRunSummary] = {}
    if not case_ids:
        return latest_by_case

    stmt = (
        select(BaselineCaseRun.baseline_case_id, ExtractionRun)
        .join(ExtractionRun, BaselineCaseRun.run_id == ExtractionRun.id)
        .where(BaselineCaseRun.baseline_case_id.in_(case_ids))
        .order_by(ExtractionRun.created_at.desc())
    )
    for case_id, run in session.exec(stmt).all():
        if case_id not in latest_by_case:
            latest_by_case[case_id] = build_baseline_run_summary(run)

    missing = [case_id for case_id in case_ids if case_id not in latest_by_case]
    if missing:
        stmt = (
            select(ExtractionRun)
            .where(ExtractionRun.baseline_case_id.in_(missing))
            .order_by(ExtractionRun.created_at.desc())
        )
        for run in session.exec(stmt).all():
            case_id = run.baseline_case_id
            if case_id and case_id not in latest_by_case:
                latest_by_case[case_id] = build_baseline_run_summary(run)

    return latest_by_case


def link_cases_to_run(session: Session, case_ids: List[str], run_id: int) -> None:
    BaselineCaseRunRepository(session).link_cases_to_run(case_ids, run_id)


def get_latest_run_for_cases(session: Session, case_ids: List[str]) -> Optional[ExtractionRun]:
    if not case_ids:
        return None
    stmt = (
        select(ExtractionRun)
        .join(BaselineCaseRun, BaselineCaseRun.run_id == ExtractionRun.id)
        .where(BaselineCaseRun.baseline_case_id.in_(case_ids))
        .order_by(ExtractionRun.created_at.desc())
        .limit(1)
    )
    run = session.exec(stmt).first()
    if run:
        return run
    stmt = (
        select(ExtractionRun)
        .where(ExtractionRun.baseline_case_id.in_(case_ids))
        .order_by(ExtractionRun.created_at.desc())
        .limit(1)
    )
    return session.exec(stmt).first()


def load_shadow_entries(dataset: Optional[str] = None) -> List[dict]:
    shadow_path = Path(__file__).resolve().parent.parent / "baseline" / "data_shadow" / "shadow_extractions.json"
    if not shadow_path.exists():
        return []
    entries = json.loads(shadow_path.read_text(encoding="utf-8"))
    if dataset:
        entries = [entry for entry in entries if entry.get("dataset") == dataset]
    return entries


def get_case_ids_for_shared_source(case: BaselineCase) -> List[str]:
    source_keys = get_source_keys(case, None)
    if not source_keys:
        return [case.id]

    matched_ids = [case.id]
    for other_data in list_cases():
        other = BaselineCase(**other_data)
        other_keys = get_source_keys(other, None)
        if any(key in source_keys for key in other_keys):
            matched_ids.append(other.id)
    return sorted(set(matched_ids))


def get_case_by_id(case_id: str) -> Optional[BaselineCase]:
    case_data = get_case(case_id)
    if not case_data:
        return None
    return BaselineCase(**case_data)
