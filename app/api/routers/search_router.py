from __future__ import annotations

import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlmodel import Session, select

from ...db import get_session
from ...integrations.llm import ProviderSelectionError, resolve_provider_selection
from ...persistence.models import ExtractionRun, Paper, RunStatus
from ...schemas import EnqueueRequest, EnqueueResponse, EnqueuedRun, SearchItem, SearchResponse
from ...services.queue_coordinator import QueueCoordinator
from ...services.queue_service import get_queue
from ...services.search_service import search_all_free_sources

router = APIRouter(tags=["search"])


@router.get("/api/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=2),
    rows: int = 10,
    session: Session = Depends(get_session),
) -> SearchResponse:
    results = await search_all_free_sources(q, per_source=rows)

    dois = [r.doi for r in results if r.doi]
    urls = [r.url for r in results if r.url]
    pdf_urls = [r.pdf_url for r in results if r.pdf_url]
    all_urls = list(set(urls + pdf_urls))

    existing_papers: dict[str, Paper] = {}
    if dois or all_urls:
        conditions = []
        if dois:
            conditions.append(Paper.doi.in_(dois))
        if all_urls:
            conditions.append(Paper.url.in_(all_urls))

        stmt = select(Paper).where(or_(*conditions))
        for paper in session.exec(stmt).all():
            if paper.doi:
                existing_papers[paper.doi.lower()] = paper
            if paper.url:
                existing_papers[paper.url.lower()] = paper

    processed_paper_ids: set[int] = set()
    if existing_papers:
        paper_ids = [p.id for p in existing_papers.values() if p.id]
        if paper_ids:
            stmt = (
                select(ExtractionRun.paper_id)
                .where(ExtractionRun.paper_id.in_(paper_ids))
                .where(ExtractionRun.status == RunStatus.STORED.value)
                .distinct()
            )
            processed_paper_ids = set(session.exec(stmt).all())

    enriched_results: List[SearchItem] = []
    for r in results:
        paper = None
        if r.doi and r.doi.lower() in existing_papers:
            paper = existing_papers[r.doi.lower()]
        elif r.url and r.url.lower() in existing_papers:
            paper = existing_papers[r.url.lower()]

        seen = paper is not None
        processed = paper.id in processed_paper_ids if paper and paper.id else False

        enriched_results.append(
            SearchItem(
                title=r.title,
                doi=r.doi,
                url=r.url,
                pdf_url=r.pdf_url,
                source=r.source,
                year=r.year,
                authors=r.authors,
                seen=seen,
                processed=processed,
            )
        )

    return SearchResponse(results=enriched_results)


@router.post("/api/enqueue", response_model=EnqueueResponse)
async def enqueue_papers(
    req: EnqueueRequest,
    session: Session = Depends(get_session),
) -> EnqueueResponse:
    """Enqueue papers for batch extraction."""
    try:
        selection = resolve_provider_selection(provider=req.provider, model=req.model)
    except ProviderSelectionError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_request",
                "message": str(exc),
                "details": exc.details,
            },
        ) from exc

    queue = get_queue()
    coordinator = QueueCoordinator()
    runs: List[EnqueuedRun] = []
    enqueued = 0
    skipped = 0

    for item in req.papers:
        paper = None
        if item.doi:
            stmt = select(Paper).where(Paper.doi == item.doi)
            paper = session.exec(stmt).first()
        if not paper and item.url:
            stmt = select(Paper).where(Paper.url == item.url)
            paper = session.exec(stmt).first()

        if paper and not item.force:
            stmt = (
                select(ExtractionRun)
                .where(ExtractionRun.paper_id == paper.id)
                .where(ExtractionRun.status == RunStatus.STORED.value)
                .limit(1)
            )
            existing_run = session.exec(stmt).first()
            if existing_run:
                runs.append(
                    EnqueuedRun(
                        run_id=existing_run.id,
                        paper_id=paper.id,
                        title=item.title,
                        status=existing_run.status,
                        skipped=True,
                        skip_reason="Already processed",
                    )
                )
                skipped += 1
                continue

        if await queue.is_url_pending(item.pdf_url):
            stmt = (
                select(ExtractionRun)
                .where(ExtractionRun.pdf_url == item.pdf_url)
                .order_by(ExtractionRun.created_at.desc())
                .limit(1)
            )
            existing_run = session.exec(stmt).first()
            if existing_run:
                runs.append(
                    EnqueuedRun(
                        run_id=existing_run.id,
                        paper_id=existing_run.paper_id or (paper.id if paper else 0),
                        title=item.title,
                        status=existing_run.status,
                        skipped=True,
                        skip_reason="Already queued",
                    )
                )
                skipped += 1
                continue

        if not paper:
            paper = Paper(
                title=item.title,
                doi=item.doi,
                url=item.url or item.pdf_url,
                source=item.source,
                year=item.year,
                authors_json=json.dumps(item.authors) if item.authors else None,
            )
            session.add(paper)
            session.commit()
            session.refresh(paper)

        run = ExtractionRun(
            paper_id=paper.id,
            status=RunStatus.QUEUED.value,
            model_provider=selection.provider_id,
            model_name=selection.model_id,
            pdf_url=item.pdf_url,
            prompt_id=req.prompt_id,
        )
        result = coordinator.enqueue_new_run(
            session,
            run=run,
            title=item.title,
            pdf_urls=None,
        )
        if not result.enqueued:
            conflict_run = session.get(ExtractionRun, result.conflict_run_id) if result.conflict_run_id else None
            runs.append(
                EnqueuedRun(
                    run_id=result.conflict_run_id or 0,
                    paper_id=(conflict_run.paper_id if conflict_run and conflict_run.paper_id else paper.id),
                    title=item.title,
                    status=result.conflict_run_status or RunStatus.QUEUED.value,
                    skipped=True,
                    skip_reason="Already queued",
                )
            )
            skipped += 1
            continue

        runs.append(
            EnqueuedRun(
                run_id=result.run_id,
                paper_id=paper.id,
                title=item.title,
                status=result.run_status,
                skipped=False,
            )
        )
        enqueued += 1

    return EnqueueResponse(
        runs=runs,
        total=len(req.papers),
        enqueued=enqueued,
        skipped=skipped,
    )
