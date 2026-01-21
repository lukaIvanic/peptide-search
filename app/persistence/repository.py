"""Repository pattern for database operations."""
from __future__ import annotations

import hashlib
import json
from typing import List, Optional, Tuple

from sqlmodel import Session, select

from .models import Paper, ExtractionRun, ExtractionEntity, Extraction
from ..schemas import ExtractionPayload, PaperMeta


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
        status: Optional[str] = None,
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
    
    def find_run_by_text_hash(self, text_hash: str, paper_id: Optional[int] = None) -> Optional[ExtractionRun]:
        """Find an extraction run by source text hash (for deduplication)."""
        stmt = select(ExtractionRun).where(ExtractionRun.source_text_hash == text_hash)
        if paper_id:
            stmt = stmt.where(ExtractionRun.paper_id == paper_id)
        return self.session.exec(stmt).first()
    
    # Legacy support: save to old Extraction table
    def save_extraction_legacy(
        self,
        payload: ExtractionPayload,
        paper_id: Optional[int],
        provider_name: str,
        model_name: Optional[str],
    ) -> int:
        """Save extraction to legacy Extraction table for backward compatibility."""
        payload_json = payload.model_dump_json()
        first_id = None
        
        if not payload.entities:
            row = Extraction(
                raw_json=payload_json,
                model_name=model_name,
                model_provider=provider_name,
                paper_id=paper_id,
            )
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
            return row.id
        
        for entity in payload.entities:
            peptide = entity.peptide if entity.type == "peptide" else None
            molecule = entity.molecule if entity.type == "molecule" else None
            conditions = entity.conditions
            thresholds = entity.thresholds
            
            row = Extraction(
                paper_id=paper_id,
                entity_type=entity.type,
                peptide_sequence_one_letter=peptide.sequence_one_letter if peptide else None,
                peptide_sequence_three_letter=peptide.sequence_three_letter if peptide else None,
                n_terminal_mod=peptide.n_terminal_mod if peptide else None,
                c_terminal_mod=peptide.c_terminal_mod if peptide else None,
                is_hydrogel=peptide.is_hydrogel if peptide else None,
                chemical_formula=molecule.chemical_formula if molecule else None,
                smiles=molecule.smiles if molecule else None,
                inchi=molecule.inchi if molecule else None,
                labels=json.dumps(entity.labels, ensure_ascii=False) if entity.labels else None,
                morphology=json.dumps(entity.morphology, ensure_ascii=False) if entity.morphology else None,
                ph=conditions.ph if conditions else None,
                concentration=conditions.concentration if conditions else None,
                concentration_units=conditions.concentration_units if conditions else None,
                temperature_c=conditions.temperature_c if conditions else None,
                cac=thresholds.cac if thresholds else None,
                cgc=thresholds.cgc if thresholds else None,
                mgc=thresholds.mgc if thresholds else None,
                validation_methods=json.dumps(entity.validation_methods, ensure_ascii=False) if entity.validation_methods else None,
                process_protocol=entity.process_protocol,
                reported_characteristics=json.dumps(entity.reported_characteristics, ensure_ascii=False) if entity.reported_characteristics else None,
                raw_json=payload_json,
                model_name=model_name,
                model_provider=provider_name,
            )
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
            if first_id is None:
                first_id = row.id
        
        return first_id
