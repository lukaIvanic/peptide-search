from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ...db import get_session
from ...persistence.models import ExtractionEntity, ExtractionRun, Paper
from ...persistence.repository import PromptRepository
from ...schemas import (
    EntitiesResponse,
    EntityListItem,
    EntityDetail,
    EntityKpis,
    EntityAggregateItem,
    QualityRulesRequest,
    QualityRulesResponse,
    PromptListResponse,
    PromptCreateRequest,
    PromptVersionCreateRequest,
    PromptInfo,
)
from ...services.quality_service import (
    get_quality_rules,
    update_quality_rules,
    compute_entity_quality,
    extract_entity_payload,
)
from ...services.view_builders import parse_json_list, build_prompt_info
from ...time_utils import utc_now
from ...services.serializers import iso_z

router = APIRouter(tags=["metadata"])


@router.get("/api/quality-rules", response_model=QualityRulesResponse)
async def get_quality_rules_endpoint(session: Session = Depends(get_session)) -> QualityRulesResponse:
    rules = get_quality_rules(session)
    return QualityRulesResponse(rules=rules)


@router.post("/api/quality-rules", response_model=QualityRulesResponse)
async def update_quality_rules_endpoint(
    req: QualityRulesRequest,
    session: Session = Depends(get_session),
) -> QualityRulesResponse:
    rules = update_quality_rules(session, req.rules)
    return QualityRulesResponse(rules=rules)


@router.get("/api/prompts", response_model=PromptListResponse)
async def list_prompts(session: Session = Depends(get_session)) -> PromptListResponse:
    repo = PromptRepository(session)
    prompts = repo.list_prompts()
    active = repo.get_active_prompt()
    payload = []
    for prompt in prompts:
        versions = repo.list_versions(prompt.id)
        payload.append(build_prompt_info(prompt, versions))
    return PromptListResponse(
        prompts=payload,
        active_prompt_id=active.id if active else None,
    )


@router.post("/api/prompts", response_model=PromptInfo)
async def create_prompt_endpoint(
    req: PromptCreateRequest,
    session: Session = Depends(get_session),
) -> PromptInfo:
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Prompt name is required.")
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Prompt content is required.")
    repo = PromptRepository(session)
    prompt, _version = repo.create_prompt(
        name=req.name.strip(),
        description=req.description,
        content=req.content.strip(),
        notes=req.notes,
        created_by=req.created_by,
        activate=req.activate,
    )
    versions = repo.list_versions(prompt.id)
    return build_prompt_info(prompt, versions)


@router.post("/api/prompts/{prompt_id}/versions", response_model=PromptInfo)
async def create_prompt_version_endpoint(
    prompt_id: int,
    req: PromptVersionCreateRequest,
    session: Session = Depends(get_session),
) -> PromptInfo:
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Prompt content is required.")
    repo = PromptRepository(session)
    prompt = repo.get_prompt(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found.")
    repo.create_version(
        prompt_id=prompt_id,
        content=req.content.strip(),
        notes=req.notes,
        created_by=req.created_by,
    )
    versions = repo.list_versions(prompt_id)
    return build_prompt_info(prompt, versions)


@router.post("/api/prompts/{prompt_id}/activate", response_model=PromptInfo)
async def activate_prompt_endpoint(
    prompt_id: int,
    session: Session = Depends(get_session),
) -> PromptInfo:
    repo = PromptRepository(session)
    prompt = repo.set_active(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found.")
    versions = repo.list_versions(prompt_id)
    return build_prompt_info(prompt, versions)


@router.get("/api/entities", response_model=EntitiesResponse)
async def list_entities(
    group_by: Optional[str] = Query(default=None),
    show_missing_key: bool = Query(default=False),
    latest_only: bool = Query(default=False),
    recent_minutes: Optional[int] = Query(default=None, ge=1, le=1440),
    session: Session = Depends(get_session),
) -> EntitiesResponse:
    rules = get_quality_rules(session)
    stmt = (
        select(ExtractionEntity, ExtractionRun, Paper)
        .join(ExtractionRun, ExtractionEntity.run_id == ExtractionRun.id)
        .outerjoin(Paper, ExtractionRun.paper_id == Paper.id)
        .order_by(ExtractionEntity.id.desc())
    )
    if latest_only:
        latest_run = session.exec(
            select(ExtractionRun).order_by(ExtractionRun.created_at.desc()).limit(1)
        ).first()
        if latest_run:
            stmt = stmt.where(ExtractionRun.id == latest_run.id)
    if recent_minutes:
        cutoff = utc_now() - timedelta(minutes=recent_minutes)
        stmt = stmt.where(ExtractionRun.created_at >= cutoff)
    rows = session.exec(stmt).all()
    items: List[EntityListItem] = []
    run_payload_cache: dict[int, dict] = {}

    for entity, run, paper in rows:
        raw_payload = run_payload_cache.get(run.id)
        if raw_payload is None:
            if run.raw_json:
                try:
                    raw_payload = json.loads(run.raw_json)
                except Exception:
                    raw_payload = {}
            else:
                raw_payload = {}
            run_payload_cache[run.id] = raw_payload

        entity_payload = extract_entity_payload(raw_payload, entity.entity_index)
        quality = compute_entity_quality(entity, entity_payload, rules)

        items.append(
            EntityListItem(
                id=entity.id,
                run_id=entity.run_id,
                paper_id=paper.id if paper else None,
                entity_index=entity.entity_index,
                entity_type=entity.entity_type,
                peptide_sequence_one_letter=entity.peptide_sequence_one_letter,
                peptide_sequence_three_letter=entity.peptide_sequence_three_letter,
                chemical_formula=entity.chemical_formula,
                smiles=entity.smiles,
                inchi=entity.inchi,
                labels=parse_json_list(entity.labels),
                morphology=parse_json_list(entity.morphology),
                validation_methods=parse_json_list(entity.validation_methods),
                reported_characteristics=parse_json_list(entity.reported_characteristics),
                ph=entity.ph,
                concentration=entity.concentration,
                concentration_units=entity.concentration_units,
                temperature_c=entity.temperature_c,
                cac=entity.cac,
                cgc=entity.cgc,
                mgc=entity.mgc,
                evidence_coverage=quality["evidence_coverage"],
                flags=quality["flags"],
                missing_evidence_fields=quality["missing_evidence_fields"],
                paper_title=paper.title if paper else None,
                paper_doi=paper.doi if paper else None,
                paper_year=paper.year if paper else None,
                paper_source=paper.source if paper else None,
                run_created_at=iso_z(run.created_at),
                model_provider=run.model_provider,
                model_name=run.model_name,
                prompt_version=run.prompt_version,
            )
        )

    aggregates = None
    if group_by:
        allowed = {
            "peptide_sequence_one_letter": lambda item: item.peptide_sequence_one_letter,
            "peptide_sequence_three_letter": lambda item: item.peptide_sequence_three_letter,
            "smiles": lambda item: item.smiles,
            "inchi": lambda item: item.inchi,
            "chemical_formula": lambda item: item.chemical_formula,
        }
        if group_by not in allowed:
            raise HTTPException(status_code=400, detail="Invalid group_by field")

        grouped: dict[str, dict] = {}
        for item in items:
            group_value = allowed[group_by](item)
            if not group_value:
                if not show_missing_key:
                    continue
                group_value = "(missing)"
            bucket = grouped.setdefault(group_value, {"entity_count": 0, "run_ids": set(), "paper_ids": set()})
            bucket["entity_count"] += 1
            if item.run_id:
                bucket["run_ids"].add(item.run_id)
            if item.paper_id:
                bucket["paper_ids"].add(item.paper_id)

        aggregates = [
            EntityAggregateItem(
                group_by=group_by,
                group_value=value,
                entity_count=data["entity_count"],
                run_count=len(data["run_ids"]),
                paper_count=len(data["paper_ids"]),
            )
            for value, data in grouped.items()
        ]

    return EntitiesResponse(items=items, aggregates=aggregates)


@router.get("/api/entities/kpis", response_model=EntityKpis)
async def get_entity_kpis(
    latest_only: bool = Query(default=False),
    recent_minutes: Optional[int] = Query(default=None, ge=1, le=1440),
    session: Session = Depends(get_session),
) -> EntityKpis:
    rules = get_quality_rules(session)
    stmt = (
        select(ExtractionEntity, ExtractionRun)
        .join(ExtractionRun, ExtractionEntity.run_id == ExtractionRun.id)
    )
    if latest_only:
        latest_run = session.exec(
            select(ExtractionRun).order_by(ExtractionRun.created_at.desc()).limit(1)
        ).first()
        if latest_run:
            stmt = stmt.where(ExtractionRun.id == latest_run.id)
    if recent_minutes:
        cutoff = utc_now() - timedelta(minutes=recent_minutes)
        stmt = stmt.where(ExtractionRun.created_at >= cutoff)
    rows = session.exec(stmt).all()
    total_entities = 0
    missing_evidence_count = 0
    invalid_count = 0
    morphology_counts: dict[str, int] = {}
    validation_counts: dict[str, int] = {}
    missing_field_counts: dict[str, int] = {}
    run_payload_cache: dict[int, dict] = {}
    invalid_flags = {
        "invalid_ph",
        "invalid_temperature",
        "invalid_concentration",
        "invalid_sequence_chars",
        "evidence_missing_quote",
        "peptide_and_molecule_set",
    }

    for entity, run in rows:
        total_entities += 1
        raw_payload = run_payload_cache.get(run.id)
        if raw_payload is None:
            if run.raw_json:
                try:
                    raw_payload = json.loads(run.raw_json)
                except Exception:
                    raw_payload = {}
            else:
                raw_payload = {}
            run_payload_cache[run.id] = raw_payload

        entity_payload = extract_entity_payload(raw_payload, entity.entity_index)
        quality = compute_entity_quality(entity, entity_payload, rules)
        if quality["missing_evidence_fields"]:
            missing_evidence_count += 1
            for field in quality["missing_evidence_fields"]:
                missing_field_counts[field] = missing_field_counts.get(field, 0) + 1
        if any(flag in invalid_flags for flag in quality["flags"]):
            invalid_count += 1

        for value in parse_json_list(entity.morphology):
            morphology_counts[value] = morphology_counts.get(value, 0) + 1
        for value in parse_json_list(entity.validation_methods):
            validation_counts[value] = validation_counts.get(value, 0) + 1

    missing_pct = (missing_evidence_count / total_entities * 100) if total_entities else 0.0
    invalid_pct = (invalid_count / total_entities * 100) if total_entities else 0.0

    top_morphology = [
        {"value": value, "count": count}
        for value, count in sorted(morphology_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    ]
    top_validation_methods = [
        {"value": value, "count": count}
        for value, count in sorted(validation_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    ]
    top_missing_fields = [
        {"value": value, "count": count}
        for value, count in sorted(missing_field_counts.items(), key=lambda item: item[1], reverse=True)[:6]
    ]

    return EntityKpis(
        total_entities=total_entities,
        missing_evidence_count=missing_evidence_count,
        invalid_count=invalid_count,
        missing_evidence_pct=missing_pct,
        invalid_pct=invalid_pct,
        top_morphology=top_morphology,
        top_validation_methods=top_validation_methods,
        top_missing_fields=top_missing_fields,
    )


@router.get("/api/entities/{entity_id}", response_model=EntityDetail)
async def get_entity_detail(entity_id: int, session: Session = Depends(get_session)) -> EntityDetail:
    entity = session.get(ExtractionEntity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    run = session.get(ExtractionRun, entity.run_id) if entity.run_id else None
    paper = session.get(Paper, run.paper_id) if run and run.paper_id else None

    run_payload: dict = {}
    if run and run.raw_json:
        try:
            run_payload = json.loads(run.raw_json)
        except Exception:
            run_payload = {}

    entity_payload = extract_entity_payload(run_payload, entity.entity_index)
    rules = get_quality_rules(session)
    quality = compute_entity_quality(entity, entity_payload, rules)
    evidence = entity_payload.get("evidence") if isinstance(entity_payload, dict) else None

    prompts = None
    if run and run.prompts_json:
        try:
            prompts = json.loads(run.prompts_json)
        except Exception:
            prompts = {"raw": run.prompts_json}

    item = EntityListItem(
        id=entity.id,
        run_id=entity.run_id,
        paper_id=paper.id if paper else None,
        entity_index=entity.entity_index,
        entity_type=entity.entity_type,
        peptide_sequence_one_letter=entity.peptide_sequence_one_letter,
        peptide_sequence_three_letter=entity.peptide_sequence_three_letter,
        chemical_formula=entity.chemical_formula,
        smiles=entity.smiles,
        inchi=entity.inchi,
        labels=parse_json_list(entity.labels),
        morphology=parse_json_list(entity.morphology),
        validation_methods=parse_json_list(entity.validation_methods),
        reported_characteristics=parse_json_list(entity.reported_characteristics),
        ph=entity.ph,
        concentration=entity.concentration,
        concentration_units=entity.concentration_units,
        temperature_c=entity.temperature_c,
        cac=entity.cac,
        cgc=entity.cgc,
        mgc=entity.mgc,
        evidence_coverage=quality["evidence_coverage"],
        flags=quality["flags"],
        missing_evidence_fields=quality["missing_evidence_fields"],
        paper_title=paper.title if paper else None,
        paper_doi=paper.doi if paper else None,
        paper_year=paper.year if paper else None,
        paper_source=paper.source if paper else None,
        run_created_at=iso_z(run.created_at) if run else None,
        model_provider=run.model_provider if run else None,
        model_name=run.model_name if run else None,
        prompt_version=run.prompt_version if run else None,
    )

    run_payload_meta = {
        "id": run.id if run else None,
        "paper_id": run.paper_id if run else None,
        "parent_run_id": run.parent_run_id if run else None,
        "status": run.status if run else None,
        "failure_reason": run.failure_reason if run else None,
        "comment": run.comment if run else None,
        "model_provider": run.model_provider if run else None,
        "model_name": run.model_name if run else None,
        "prompt_version": run.prompt_version if run else None,
        "created_at": iso_z(run.created_at) if run else None,
    }
    paper_meta = {
        "id": paper.id if paper else None,
        "title": paper.title if paper else None,
        "doi": paper.doi if paper else None,
        "url": paper.url if paper else None,
        "source": paper.source if paper else None,
        "year": paper.year if paper else None,
    }

    return EntityDetail(
        item=item,
        entity=entity_payload,
        evidence=evidence,
        missing_evidence_fields=quality["missing_evidence_fields"],
        run=run_payload_meta,
        paper=paper_meta,
        prompts=prompts,
    )
