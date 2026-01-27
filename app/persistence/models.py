"""Database models for the peptide extractor.

This module defines SQLModel tables for papers, extraction runs, and entities.
The schema is normalized to avoid duplicating raw_json per entity.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import SQLModel, Field


class RunStatus(str, Enum):
    """Status of an extraction run."""
    QUEUED = "queued"
    FETCHING = "fetching"
    PROVIDER = "provider"
    VALIDATING = "validating"
    STORED = "stored"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Paper(SQLModel, table=True):
    """A scientific paper from which peptides/molecules are extracted."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    doi: Optional[str] = Field(default=None, index=True)
    url: Optional[str] = Field(default=None)
    source: Optional[str] = Field(default=None, index=True)  # pmc, europepmc, arxiv, semanticscholar, upload, manual
    year: Optional[int] = Field(default=None, index=True)
    authors_json: Optional[str] = Field(default=None)  # JSON-encoded list of authors
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class ExtractionRun(SQLModel, table=True):
    """
    A single extraction run against a paper.
    
    Stores run-level metadata: the full raw JSON payload, model info,
    prompt version, and timing. Each run produces zero or more entities.
    """
    __tablename__ = "extraction_run"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    paper_id: Optional[int] = Field(default=None, foreign_key="paper.id", index=True)
    parent_run_id: Optional[int] = Field(default=None, foreign_key="extraction_run.id", index=True)
    baseline_case_id: Optional[str] = Field(default=None, index=True)
    baseline_dataset: Optional[str] = Field(default=None, index=True)
    
    # Run status for queue tracking
    status: str = Field(default=RunStatus.QUEUED.value, index=True)
    failure_reason: Optional[str] = Field(default=None)  # Error message if failed
    
    # Prompts sent to LLM (for traceability and follow-up)
    prompts_json: Optional[str] = Field(default=None)  # JSON: {system_prompt, user_prompt, messages}
    prompt_id: Optional[int] = Field(default=None, foreign_key="base_prompt.id", index=True)
    prompt_version_id: Optional[int] = Field(default=None, foreign_key="prompt_version.id", index=True)
    
    # Raw model output for traceability
    raw_json: Optional[str] = Field(default=None)  # Full JSON payload
    comment: Optional[str] = Field(default=None)   # Model's explanation
    
    # Model info
    model_provider: Optional[str] = Field(default=None)
    model_name: Optional[str] = Field(default=None)
    
    # Provenance
    source_text_hash: Optional[str] = Field(default=None, index=True)  # SHA256 of input text
    prompt_version: Optional[str] = Field(default=None)  # Version tag for prompt
    pdf_url: Optional[str] = Field(default=None)  # Original PDF URL for reference
    
    # Timing
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class BaselineCaseRun(SQLModel, table=True):
    """Links baseline cases to shared extraction runs."""
    __tablename__ = "baseline_case_run"

    id: Optional[int] = Field(default=None, primary_key=True)
    baseline_case_id: str = Field(index=True)
    run_id: int = Field(foreign_key="extraction_run.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class ExtractionEntity(SQLModel, table=True):
    """
    A single extracted entity (peptide or molecule) from an extraction run.
    
    No longer stores raw_json - that's at the run level.
    """
    __tablename__ = "extraction_entity"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: Optional[int] = Field(default=None, foreign_key="extraction_run.id", index=True)
    entity_index: Optional[int] = Field(default=None, index=True)
    
    # Entity type
    entity_type: Optional[str] = Field(default=None, index=True)  # peptide | molecule
    
    # Peptide-specific fields
    peptide_sequence_one_letter: Optional[str] = Field(default=None, index=True)
    peptide_sequence_three_letter: Optional[str] = Field(default=None)
    n_terminal_mod: Optional[str] = Field(default=None, index=True)
    c_terminal_mod: Optional[str] = Field(default=None, index=True)
    is_hydrogel: Optional[bool] = Field(default=None, index=True)
    
    # Molecule-specific fields
    chemical_formula: Optional[str] = Field(default=None, index=True)
    smiles: Optional[str] = Field(default=None)
    inchi: Optional[str] = Field(default=None)
    
    # Shared fields
    labels: Optional[str] = Field(default=None)  # JSON list
    morphology: Optional[str] = Field(default=None)  # JSON list
    
    # Conditions
    ph: Optional[float] = Field(default=None, index=True)
    concentration: Optional[float] = Field(default=None)
    concentration_units: Optional[str] = Field(default=None)
    temperature_c: Optional[float] = Field(default=None)
    
    # Thresholds
    cac: Optional[float] = Field(default=None)
    cgc: Optional[float] = Field(default=None)
    mgc: Optional[float] = Field(default=None)
    
    # Validation
    validation_methods: Optional[str] = Field(default=None)  # JSON list
    process_protocol: Optional[str] = Field(default=None)
    reported_characteristics: Optional[str] = Field(default=None)  # JSON list


class QualityRuleConfig(SQLModel, table=True):
    """Stores JSON config for quality/flag rules."""
    __tablename__ = "quality_rule_config"

    id: Optional[int] = Field(default=None, primary_key=True)
    rules_json: str = Field(default="{}")
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class BasePrompt(SQLModel, table=True):
    """Base prompt registry for system prompts."""
    __tablename__ = "base_prompt"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = Field(default=None)
    is_active: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class PromptVersion(SQLModel, table=True):
    """Versioned content for a base prompt."""
    __tablename__ = "prompt_version"

    id: Optional[int] = Field(default=None, primary_key=True)
    prompt_id: int = Field(foreign_key="base_prompt.id", index=True)
    version_index: int = Field(default=1)
    content: str
    notes: Optional[str] = Field(default=None)
    created_by: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


# Keep the old Extraction model for backward compatibility during migration
class Extraction(SQLModel, table=True):
    """Legacy extraction model - kept for migration compatibility."""
    id: Optional[int] = Field(default=None, primary_key=True)
    paper_id: Optional[int] = Field(default=None, index=True, foreign_key="paper.id")

    entity_type: Optional[str] = Field(default=None, index=True)
    peptide_sequence_one_letter: Optional[str] = Field(default=None, index=True)
    peptide_sequence_three_letter: Optional[str] = Field(default=None)
    n_terminal_mod: Optional[str] = Field(default=None, index=True)
    c_terminal_mod: Optional[str] = Field(default=None, index=True)
    chemical_formula: Optional[str] = Field(default=None, index=True)
    smiles: Optional[str] = Field(default=None)
    inchi: Optional[str] = Field(default=None)
    labels: Optional[str] = Field(default=None)
    morphology: Optional[str] = Field(default=None)

    ph: Optional[float] = Field(default=None, index=True)
    concentration: Optional[float] = Field(default=None)
    concentration_units: Optional[str] = Field(default=None)
    temperature_c: Optional[float] = Field(default=None)
    is_hydrogel: Optional[bool] = Field(default=None, index=True)
    cac: Optional[float] = Field(default=None)
    cgc: Optional[float] = Field(default=None)
    mgc: Optional[float] = Field(default=None)

    validation_methods: Optional[str] = Field(default=None)
    process_protocol: Optional[str] = Field(default=None)
    reported_characteristics: Optional[str] = Field(default=None)

    raw_json: Optional[str] = Field(default=None)
    model_name: Optional[str] = Field(default=None)
    model_provider: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
