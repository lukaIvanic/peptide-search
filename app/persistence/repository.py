"""Repository pattern for database operations."""
from __future__ import annotations

import hashlib
import json
from typing import List, Optional, Tuple

from sqlmodel import Session, select

from .models import (
    Paper,
    ExtractionRun,
    ExtractionEntity,
    BasePrompt,
    PromptVersion,
    BaselineCaseRun,
)
from ..schemas import ExtractionPayload, PaperMeta
from ..time_utils import utc_now


class PaperRepository:
    """Repository for Paper CRUD operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def find_by_doi(self, doi: str) -> Optional[Paper]:
        """Find a paper by DOI."""
        stmt = select(Paper).where(Paper.doi == doi)
        return self.session.exec(stmt).first()
    
    def find_by_title(self, title: str) -> Optional[Paper]:
        """Find a paper by title."""
        stmt = select(Paper).where(Paper.title == title)
        return self.session.exec(stmt).first()
    
    def find_by_url(self, url: str) -> Optional[Paper]:
        """Find a paper by URL."""
        stmt = select(Paper).where(Paper.url == url)
        return self.session.exec(stmt).first()
    
    def upsert(self, meta: PaperMeta) -> Optional[int]:
        """
        Upsert a paper from metadata.
        
        Returns the paper ID, or None if no identifiable info provided.
        """
        if not (meta.title or meta.doi or meta.url):
            return None
        
        # Try to find existing by DOI first
        if meta.doi:
            paper = self.find_by_doi(meta.doi)
            if paper:
                return self._update_paper(paper, meta)
        
        # Then by title
        if meta.title:
            paper = self.find_by_title(meta.title)
            if paper:
                return paper.id
        
        # Create new
        return self._create_paper(meta)
    
    def _update_paper(self, paper: Paper, meta: PaperMeta) -> int:
        """Update missing fields on an existing paper."""
        changed = False
        if meta.title and not paper.title:
            paper.title = meta.title
            changed = True
        if meta.url and not paper.url:
            paper.url = meta.url
            changed = True
        if meta.source and not paper.source:
            paper.source = meta.source
            changed = True
        if meta.year and not paper.year:
            paper.year = meta.year
            changed = True
        if meta.authors and not paper.authors_json:
            paper.authors_json = json.dumps(meta.authors, ensure_ascii=False)
            changed = True
        
        if changed:
            self.session.add(paper)
            self.session.commit()
            self.session.refresh(paper)
        
        return paper.id
    
    def _create_paper(self, meta: PaperMeta) -> int:
        """Create a new paper."""
        paper = Paper(
            title=meta.title or "(Untitled)",
            doi=meta.doi,
            url=meta.url,
            source=meta.source,
            year=meta.year,
            authors_json=json.dumps(meta.authors or [], ensure_ascii=False) if meta.authors else None,
        )
        self.session.add(paper)
        self.session.commit()
        self.session.refresh(paper)
        return paper.id


class ExtractionRepository:
    """Repository for ExtractionRun and ExtractionEntity operations."""
    
    PROMPT_VERSION = "v1.0"  # Increment when prompts change significantly
    
    def __init__(self, session: Session):
        self.session = session
    
    @staticmethod
    def compute_text_hash(text: str) -> str:
        """Compute SHA256 hash of input text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    
    def save_extraction(
        self,
        payload: ExtractionPayload,
        paper_id: Optional[int],
        provider_name: str,
        model_name: Optional[str],
        source_text: Optional[str] = None,
        prompts_json: Optional[str] = None,
        pdf_url: Optional[str] = None,
        parent_run_id: Optional[int] = None,
        prompt_id: Optional[int] = None,
        prompt_version_id: Optional[int] = None,
        status: Optional[str] = None,
        baseline_case_id: Optional[str] = None,
        baseline_dataset: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        reasoning_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
    ) -> Tuple[int, List[int]]:
        """
        Save an extraction run and its entities.
        
        Returns (run_id, list of entity_ids).
        """
        # Compute text hash if source text provided
        text_hash = self.compute_text_hash(source_text) if source_text else None

        # Create the run and flush to obtain run_id without committing yet
        run = ExtractionRun(
            paper_id=paper_id,
            raw_json=payload.model_dump_json(),
            comment=payload.comment,
            model_provider=provider_name,
            model_name=model_name,
            source_text_hash=text_hash,
            prompt_version=self.PROMPT_VERSION,
            prompts_json=prompts_json,
            pdf_url=pdf_url,
            parent_run_id=parent_run_id,
            prompt_id=prompt_id,
            prompt_version_id=prompt_version_id,
            baseline_case_id=baseline_case_id,
            baseline_dataset=baseline_dataset,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
        )
        if status:
            run.status = status
        self.session.add(run)
        self.session.flush()  # assigns run.id

        entities: List[ExtractionEntity] = []
        for entity_index, entity_data in enumerate(payload.entities):
            entities.append(self._entity_to_row(entity_data, run.id, entity_index))

        if entities:
            self.session.add_all(entities)

        # Commit once for the whole run (atomic)
        self.session.commit()

        entity_ids = [e.id for e in entities if e.id is not None]
        return run.id, entity_ids

    def _entity_to_row(self, entity, run_id: int, entity_index: int) -> ExtractionEntity:
        """Convert a Pydantic entity to a database entity."""
        peptide = entity.peptide if entity and entity.type == "peptide" else None
        molecule = entity.molecule if entity and entity.type == "molecule" else None
        conditions = entity.conditions if entity else None
        thresholds = entity.thresholds if entity else None

        return ExtractionEntity(
            run_id=run_id,
            entity_index=entity_index,
            entity_type=entity.type if entity else None,
            peptide_sequence_one_letter=peptide.sequence_one_letter if peptide else None,
            peptide_sequence_three_letter=peptide.sequence_three_letter if peptide else None,
            n_terminal_mod=peptide.n_terminal_mod if peptide else None,
            c_terminal_mod=peptide.c_terminal_mod if peptide else None,
            is_hydrogel=peptide.is_hydrogel if peptide else None,
            chemical_formula=molecule.chemical_formula if molecule else None,
            smiles=molecule.smiles if molecule else None,
            inchi=molecule.inchi if molecule else None,
            labels=json.dumps(entity.labels, ensure_ascii=False) if entity and entity.labels else None,
            morphology=json.dumps(entity.morphology, ensure_ascii=False) if entity and entity.morphology else None,
            ph=conditions.ph if conditions else None,
            concentration=conditions.concentration if conditions else None,
            concentration_units=conditions.concentration_units if conditions else None,
            temperature_c=conditions.temperature_c if conditions else None,
            cac=thresholds.cac if thresholds else None,
            cgc=thresholds.cgc if thresholds else None,
            mgc=thresholds.mgc if thresholds else None,
            validation_methods=json.dumps(entity.validation_methods, ensure_ascii=False) if entity and entity.validation_methods else None,
            process_protocol=entity.process_protocol if entity else None,
            reported_characteristics=json.dumps(entity.reported_characteristics, ensure_ascii=False) if entity and entity.reported_characteristics else None,
        )


class PromptRepository:
    """Repository for base prompts and versions."""

    def __init__(self, session: Session):
        self.session = session

    def list_prompts(self) -> List[BasePrompt]:
        stmt = select(BasePrompt).order_by(BasePrompt.created_at.desc())
        return list(self.session.exec(stmt).all())

    def get_prompt(self, prompt_id: int) -> Optional[BasePrompt]:
        return self.session.get(BasePrompt, prompt_id)

    def get_active_prompt(self) -> Optional[BasePrompt]:
        stmt = select(BasePrompt).where(BasePrompt.is_active == True)  # noqa: E712
        return self.session.exec(stmt).first()

    def list_versions(self, prompt_id: int) -> List[PromptVersion]:
        stmt = (
            select(PromptVersion)
            .where(PromptVersion.prompt_id == prompt_id)
            .order_by(PromptVersion.version_index.desc())
        )
        return list(self.session.exec(stmt).all())

    def get_latest_version(self, prompt_id: int) -> Optional[PromptVersion]:
        stmt = (
            select(PromptVersion)
            .where(PromptVersion.prompt_id == prompt_id)
            .order_by(PromptVersion.version_index.desc())
            .limit(1)
        )
        return self.session.exec(stmt).first()

    def create_prompt(
        self,
        name: str,
        description: Optional[str],
        content: str,
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
        activate: bool = False,
    ) -> Tuple[BasePrompt, PromptVersion]:
        if activate:
            self._clear_active()
        prompt = BasePrompt(
            name=name,
            description=description,
            is_active=activate,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.session.add(prompt)
        self.session.commit()
        self.session.refresh(prompt)

        version = PromptVersion(
            prompt_id=prompt.id,
            version_index=1,
            content=content,
            notes=notes,
            created_by=created_by,
        )
        self.session.add(version)
        self.session.commit()
        self.session.refresh(version)
        return prompt, version

    def create_version(
        self,
        prompt_id: int,
        content: str,
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> PromptVersion:
        latest = self.get_latest_version(prompt_id)
        next_index = (latest.version_index if latest else 0) + 1
        version = PromptVersion(
            prompt_id=prompt_id,
            version_index=next_index,
            content=content,
            notes=notes,
            created_by=created_by,
        )
        self.session.add(version)
        prompt = self.session.get(BasePrompt, prompt_id)
        if prompt:
            prompt.updated_at = utc_now()
            self.session.add(prompt)
        self.session.commit()
        self.session.refresh(version)
        return version

    def set_active(self, prompt_id: int) -> Optional[BasePrompt]:
        self._clear_active()
        prompt = self.session.get(BasePrompt, prompt_id)
        if not prompt:
            return None
        prompt.is_active = True
        prompt.updated_at = utc_now()
        self.session.add(prompt)
        self.session.commit()
        self.session.refresh(prompt)
        return prompt

    def ensure_default_prompt(self, default_content: str) -> Tuple[BasePrompt, PromptVersion]:
        prompt = self.session.exec(select(BasePrompt).order_by(BasePrompt.created_at.asc())).first()
        if not prompt:
            prompt, version = self.create_prompt(
                name="Default base prompt",
                description="Built-in base prompt.",
                content=default_content,
                notes="Initial default prompt",
                activate=True,
                created_by="system",
            )
            return prompt, version

        if not self.get_active_prompt():
            prompt.is_active = True
            prompt.updated_at = utc_now()
            self.session.add(prompt)
            self.session.commit()
            self.session.refresh(prompt)

        version = self.get_latest_version(prompt.id)
        if not version:
            version = self.create_version(
                prompt_id=prompt.id,
                content=default_content,
                notes="Backfilled default prompt",
                created_by="system",
            )
        return prompt, version

    def resolve_prompt(
        self,
        default_content: str,
        prompt_id: Optional[int] = None,
        prompt_version_id: Optional[int] = None,
    ) -> Tuple[BasePrompt, PromptVersion]:
        if prompt_version_id:
            version = self.session.get(PromptVersion, prompt_version_id)
            if version:
                prompt = self.session.get(BasePrompt, version.prompt_id)
                if prompt:
                    return prompt, version

        if prompt_id:
            prompt = self.session.get(BasePrompt, prompt_id)
            if prompt:
                version = self.get_latest_version(prompt.id)
                if version:
                    return prompt, version

        active = self.get_active_prompt()
        if active:
            version = self.get_latest_version(active.id)
            if version:
                return active, version

        return self.ensure_default_prompt(default_content)

    def _clear_active(self) -> None:
        stmt = select(BasePrompt).where(BasePrompt.is_active == True)  # noqa: E712
        for prompt in self.session.exec(stmt).all():
            prompt.is_active = False
            prompt.updated_at = utc_now()
            self.session.add(prompt)
        self.session.commit()
    
    def find_run_by_text_hash(self, text_hash: str, paper_id: Optional[int] = None) -> Optional[ExtractionRun]:
        """Find an extraction run by source text hash (for deduplication)."""
        stmt = select(ExtractionRun).where(ExtractionRun.source_text_hash == text_hash)
        if paper_id:
            stmt = stmt.where(ExtractionRun.paper_id == paper_id)
        return self.session.exec(stmt).first()


class BaselineCaseRunRepository:
    """Repository for baseline case/run linking."""

    def __init__(self, session: Session):
        self.session = session

    def list_case_ids_for_run(self, run_id: int) -> List[str]:
        stmt = select(BaselineCaseRun.baseline_case_id).where(BaselineCaseRun.run_id == run_id)
        return [row for row in self.session.exec(stmt).all()]

    def link_cases_to_run(self, case_ids: List[str], run_id: int) -> None:
        if not case_ids:
            return
        stmt = (
            select(BaselineCaseRun.baseline_case_id)
            .where(BaselineCaseRun.run_id == run_id)
            .where(BaselineCaseRun.baseline_case_id.in_(case_ids))
        )
        existing = set(self.session.exec(stmt).all())
        new_links = [
            BaselineCaseRun(baseline_case_id=case_id, run_id=run_id)
            for case_id in case_ids
            if case_id not in existing
        ]
        if not new_links:
            return
        self.session.add_all(new_links)
        self.session.commit()
