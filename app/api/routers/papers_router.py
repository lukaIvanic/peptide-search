from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from ...config import settings
from ...db import get_session
from ...integrations.llm import ProviderSelectionError, resolve_provider_selection
from ...persistence.models import ExtractionEntity, ExtractionRun, Paper, RunStatus
from ...persistence.repository import PromptRepository
from ...prompts import build_system_prompt
from ...schemas import (
    ForceReextractResponse,
    PaperExtractionsResponse,
    PaperWithStatus,
    PapersWithStatusResponse,
)
from ...services.queue_coordinator import QueueCoordinator
from ...services.queue_service import get_queue
from ...services.serializers import iso_z, parse_json_list

router = APIRouter(tags=["papers"])


@router.get("/api/papers", response_model=PapersWithStatusResponse)
async def list_papers(session: Session = Depends(get_session)) -> PapersWithStatusResponse:
    """List all papers with their latest run status."""
    latest_run_subq = (
        select(
            ExtractionRun.paper_id,
            func.max(ExtractionRun.id).label("latest_run_id"),
        )
        .group_by(ExtractionRun.paper_id)
        .subquery()
    )

    run_count_subq = (
        select(
            ExtractionRun.paper_id,
            func.count(ExtractionRun.id).label("run_count"),
        )
        .group_by(ExtractionRun.paper_id)
        .subquery()
    )

    stmt = (
        select(
            Paper,
            ExtractionRun,
            run_count_subq.c.run_count,
        )
        .outerjoin(latest_run_subq, Paper.id == latest_run_subq.c.paper_id)
        .outerjoin(ExtractionRun, ExtractionRun.id == latest_run_subq.c.latest_run_id)
        .outerjoin(run_count_subq, Paper.id == run_count_subq.c.paper_id)
        .order_by(Paper.created_at.desc())
    )

    rows = session.exec(stmt).all()
    items: list[PaperWithStatus] = []

    for paper, latest_run, run_count in rows:
        authors = [str(item) for item in parse_json_list(paper.authors_json)]

        pdf_url = latest_run.pdf_url if latest_run else None

        items.append(
            PaperWithStatus(
                id=paper.id,
                title=paper.title,
                doi=paper.doi,
                url=paper.url,
                pdf_url=pdf_url,
                source=paper.source,
                year=paper.year,
                authors=authors,
                latest_run_id=latest_run.id if latest_run else None,
                status=latest_run.status if latest_run else None,
                failure_reason=latest_run.failure_reason if latest_run else None,
                last_run_at=iso_z(latest_run.created_at) if latest_run else None,
                run_count=run_count or 0,
            )
        )

    queue = get_queue()
    stats = await queue.get_stats()

    return PapersWithStatusResponse(
        papers=items,
        queue_stats={
            "queued": stats.queued,
            "processing": stats.processing,
        },
    )


@router.get("/api/papers/{paper_id}/extractions", response_model=PaperExtractionsResponse)
async def get_paper_extractions(
    paper_id: int,
    session: Session = Depends(get_session),
) -> PaperExtractionsResponse:
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    authors = [str(item) for item in parse_json_list(paper.authors_json)]

    merged: list[tuple[object, dict]] = []

    new_stmt = (
        select(ExtractionEntity, ExtractionRun)
        .join(ExtractionRun, ExtractionEntity.run_id == ExtractionRun.id)
        .where(ExtractionRun.paper_id == paper_id)
    )
    for ent, run in session.exec(new_stmt).all():
        merged.append(
            (
                run.created_at,
                {
                    "id": ent.id,
                    "run_id": run.id,
                    "storage": "run",
                    "entity_type": ent.entity_type,
                    "sequence_one_letter": ent.peptide_sequence_one_letter,
                    "sequence_three_letter": ent.peptide_sequence_three_letter,
                    "n_terminal_mod": ent.n_terminal_mod,
                    "c_terminal_mod": ent.c_terminal_mod,
                    "chemical_formula": ent.chemical_formula,
                    "smiles": ent.smiles,
                    "inchi": ent.inchi,
                    "labels": parse_json_list(ent.labels),
                    "morphology": parse_json_list(ent.morphology),
                    "ph": ent.ph,
                    "concentration": ent.concentration,
                    "concentration_units": ent.concentration_units,
                    "temperature_c": ent.temperature_c,
                    "is_hydrogel": ent.is_hydrogel,
                    "cac": ent.cac,
                    "cgc": ent.cgc,
                    "mgc": ent.mgc,
                    "validation_methods": parse_json_list(ent.validation_methods),
                    "model_provider": run.model_provider,
                    "model_name": run.model_name,
                    "created_at": iso_z(run.created_at),
                },
            )
        )

    merged.sort(key=lambda t: t[0], reverse=True)
    extractions = [item for _, item in merged]

    return PaperExtractionsResponse(
        paper={
            "id": paper.id,
            "title": paper.title,
            "doi": paper.doi,
            "url": paper.url,
            "source": paper.source,
            "year": paper.year,
            "authors": authors,
        },
        extractions=extractions,
    )


@router.post("/api/papers/{paper_id}/force-reextract", response_model=ForceReextractResponse)
async def force_reextract(
    paper_id: int,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    session: Session = Depends(get_session),
) -> ForceReextractResponse:
    """Force re-extraction of a paper by creating a new run."""
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    latest_run_stmt = (
        select(ExtractionRun)
        .where(ExtractionRun.paper_id == paper_id)
        .order_by(ExtractionRun.created_at.desc())
        .limit(1)
    )
    latest_run = session.exec(latest_run_stmt).first()

    pdf_url = latest_run.pdf_url if latest_run else None
    if not pdf_url and paper.url:
        pdf_url = paper.url

    if not pdf_url:
        raise HTTPException(
            status_code=400,
            detail="No PDF URL available for this paper",
        )

    queue = get_queue()
    if await queue.is_url_pending(pdf_url):
        return ForceReextractResponse(
            id=latest_run.id if latest_run else None,
            paper_id=paper.id,
            status=RunStatus.QUEUED.value,
            message="Extraction already queued for this paper",
        )

    try:
        selection = resolve_provider_selection(
            provider=provider or (latest_run.model_provider if latest_run else settings.LLM_PROVIDER),
            model=model or (latest_run.model_name if latest_run else None),
        )
    except ProviderSelectionError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_request",
                "message": str(exc),
                "details": exc.details,
            },
        ) from exc

    prompt_id = latest_run.prompt_id if latest_run and latest_run.prompt_id else None
    if not prompt_id:
        prompt_repo = PromptRepository(session)
        active_prompt = prompt_repo.get_active_prompt()
        if not active_prompt:
            active_prompt, _ = prompt_repo.ensure_default_prompt(build_system_prompt())
        prompt_id = active_prompt.id if active_prompt else None

    new_run = ExtractionRun(
        paper_id=paper.id,
        status=RunStatus.QUEUED.value,
        model_provider=selection.provider_id,
        model_name=selection.model_id,
        pdf_url=pdf_url,
        prompt_id=prompt_id,
    )

    result = QueueCoordinator().enqueue_new_run(
        session,
        run=new_run,
        title=paper.title,
        pdf_urls=None,
    )
    if not result.enqueued:
        return ForceReextractResponse(
            id=result.conflict_run_id,
            paper_id=paper.id,
            status=result.conflict_run_status or RunStatus.QUEUED.value,
            message="Extraction already queued for this paper",
        )

    return ForceReextractResponse(
        id=result.run_id,
        paper_id=paper.id,
        status=result.run_status,
        message="New extraction run created and queued",
    )
