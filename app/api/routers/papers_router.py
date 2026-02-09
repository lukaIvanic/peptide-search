from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from ...config import settings
from ...db import get_session
from ...persistence.models import Extraction, ExtractionEntity, ExtractionRun, Paper, RunStatus
from ...persistence.repository import PromptRepository
from ...prompts import build_system_prompt
from ...schemas import PaperWithStatus, PapersWithStatusResponse
from ...services.queue_service import QueueItem, get_queue

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
        authors = []
        if paper.authors_json:
            try:
                authors = json.loads(paper.authors_json)
            except Exception:
                authors = []

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
                last_run_at=latest_run.created_at.isoformat() + "Z" if latest_run else None,
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


@router.get("/api/papers/{paper_id}/extractions")
async def get_paper_extractions(paper_id: int, session: Session = Depends(get_session)) -> dict:
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    authors = []
    if paper.authors_json:
        try:
            authors = json.loads(paper.authors_json)
        except Exception:
            authors = []

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
                    "labels": json.loads(ent.labels) if ent.labels else [],
                    "morphology": json.loads(ent.morphology) if ent.morphology else [],
                    "ph": ent.ph,
                    "concentration": ent.concentration,
                    "concentration_units": ent.concentration_units,
                    "temperature_c": ent.temperature_c,
                    "is_hydrogel": ent.is_hydrogel,
                    "cac": ent.cac,
                    "cgc": ent.cgc,
                    "mgc": ent.mgc,
                    "validation_methods": json.loads(ent.validation_methods) if ent.validation_methods else [],
                    "model_provider": run.model_provider,
                    "model_name": run.model_name,
                    "created_at": run.created_at.isoformat() + "Z",
                },
            )
        )

    old_stmt = select(Extraction).where(Extraction.paper_id == paper_id)
    for r in session.exec(old_stmt).all():
        merged.append(
            (
                r.created_at,
                {
                    "id": r.id,
                    "run_id": None,
                    "storage": "legacy",
                    "entity_type": r.entity_type,
                    "sequence_one_letter": r.peptide_sequence_one_letter,
                    "sequence_three_letter": r.peptide_sequence_three_letter,
                    "n_terminal_mod": r.n_terminal_mod,
                    "c_terminal_mod": r.c_terminal_mod,
                    "chemical_formula": r.chemical_formula,
                    "smiles": r.smiles,
                    "inchi": r.inchi,
                    "labels": json.loads(r.labels) if r.labels else [],
                    "morphology": json.loads(r.morphology) if r.morphology else [],
                    "ph": r.ph,
                    "concentration": r.concentration,
                    "concentration_units": r.concentration_units,
                    "temperature_c": r.temperature_c,
                    "is_hydrogel": r.is_hydrogel,
                    "cac": r.cac,
                    "cgc": r.cgc,
                    "mgc": r.mgc,
                    "validation_methods": json.loads(r.validation_methods) if r.validation_methods else [],
                    "model_provider": r.model_provider,
                    "model_name": r.model_name,
                    "created_at": r.created_at.isoformat() + "Z",
                },
            )
        )

    merged.sort(key=lambda t: t[0], reverse=True)
    extractions = [item for _, item in merged]

    return {
        "paper": {
            "id": paper.id,
            "title": paper.title,
            "doi": paper.doi,
            "url": paper.url,
            "source": paper.source,
            "year": paper.year,
            "authors": authors,
        },
        "extractions": extractions,
    }


@router.post("/api/papers/{paper_id}/force-reextract")
async def force_reextract(
    paper_id: int,
    provider: Optional[str] = None,
    session: Session = Depends(get_session),
) -> dict:
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
        return {
            "id": latest_run.id if latest_run else None,
            "paper_id": paper.id,
            "status": RunStatus.QUEUED.value,
            "message": "Extraction already queued for this paper",
        }

    use_provider = provider or (latest_run.model_provider if latest_run else None) or settings.LLM_PROVIDER

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
        model_provider=use_provider,
        pdf_url=pdf_url,
        prompt_id=prompt_id,
    )
    session.add(new_run)
    session.commit()
    session.refresh(new_run)

    await queue.enqueue(
        QueueItem(
            run_id=new_run.id,
            paper_id=paper.id,
            pdf_url=pdf_url,
            title=paper.title,
            provider=use_provider,
            force=True,
            prompt_id=prompt_id,
        )
    )

    return {
        "id": new_run.id,
        "paper_id": paper.id,
        "status": new_run.status,
        "message": "New extraction run created and queued",
    }
