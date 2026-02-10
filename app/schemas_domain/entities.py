from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ExtractionEntityPeptide(BaseModel):
    sequence_one_letter: Optional[str] = None
    sequence_three_letter: Optional[str] = None
    n_terminal_mod: Optional[str] = None
    c_terminal_mod: Optional[str] = None
    is_hydrogel: Optional[bool] = None


class ExtractionEntityMolecule(BaseModel):
    chemical_formula: Optional[str] = None
    smiles: Optional[str] = None
    inchi: Optional[str] = None


class EvidenceItem(BaseModel):
    quote: str
    section: Optional[str] = None
    page: Optional[int] = None


class ExtractionConditions(BaseModel):
    ph: Optional[float] = None
    concentration: Optional[float] = None
    concentration_units: Optional[str] = None
    temperature_c: Optional[float] = None


class ExtractionThresholds(BaseModel):
    cac: Optional[float] = None
    cgc: Optional[float] = None
    mgc: Optional[float] = None


class ExtractionEntity(BaseModel):
    type: Literal["peptide", "molecule"]
    peptide: Optional[ExtractionEntityPeptide] = None
    molecule: Optional[ExtractionEntityMolecule] = None
    labels: List[str] = Field(default_factory=list)
    morphology: List[str] = Field(default_factory=list)
    conditions: Optional[ExtractionConditions] = None
    thresholds: Optional[ExtractionThresholds] = None
    validation_methods: List[str] = Field(default_factory=list)
    process_protocol: Optional[str] = None
    reported_characteristics: List[str] = Field(default_factory=list)
    evidence: Optional[Dict[str, List[EvidenceItem]]] = None

    @field_validator(
        "labels",
        "morphology",
        "validation_methods",
        "reported_characteristics",
        mode="before",
    )
    @classmethod
    def _coerce_none_lists(cls, value):
        return [] if value is None else value

    @field_validator("thresholds", mode="before")
    @classmethod
    def _coerce_thresholds(cls, value):
        if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
            return value[0]
        return value

    @field_validator("evidence", mode="before")
    @classmethod
    def _coerce_evidence(cls, value):
        if value is None:
            return None
        if isinstance(value, list):
            return {"general": value} if value else None
        if isinstance(value, dict) and "quote" in value:
            return {"general": [value]}
        return value


class PaperMeta(BaseModel):
    title: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)


class ExtractionPayload(BaseModel):
    paper: PaperMeta
    entities: List[ExtractionEntity]
    comment: Optional[str] = None


class ExtractRequest(BaseModel):
    text: Optional[str] = None
    pdf_url: Optional[str] = None
    title: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)
    prompt_id: Optional[int] = None


class FollowupRequest(BaseModel):
    instruction: str
    provider: Optional[str] = None
    model: Optional[str] = None


class EditRunRequest(BaseModel):
    payload: ExtractionPayload
    reason: Optional[str] = None


class ExtractResponse(BaseModel):
    extraction: ExtractionPayload
    extraction_id: int
    paper_id: Optional[int] = None


class EntityListItem(BaseModel):
    id: int
    run_id: Optional[int] = None
    paper_id: Optional[int] = None
    entity_index: Optional[int] = None
    entity_type: Optional[str] = None
    peptide_sequence_one_letter: Optional[str] = None
    peptide_sequence_three_letter: Optional[str] = None
    chemical_formula: Optional[str] = None
    smiles: Optional[str] = None
    inchi: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    morphology: List[str] = Field(default_factory=list)
    validation_methods: List[str] = Field(default_factory=list)
    reported_characteristics: List[str] = Field(default_factory=list)
    ph: Optional[float] = None
    concentration: Optional[float] = None
    concentration_units: Optional[str] = None
    temperature_c: Optional[float] = None
    cac: Optional[float] = None
    cgc: Optional[float] = None
    mgc: Optional[float] = None
    evidence_coverage: int = 0
    flags: List[str] = Field(default_factory=list)
    missing_evidence_fields: List[str] = Field(default_factory=list)
    paper_title: Optional[str] = None
    paper_doi: Optional[str] = None
    paper_year: Optional[int] = None
    paper_source: Optional[str] = None
    run_created_at: Optional[str] = None
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None


class EntityAggregateItem(BaseModel):
    group_by: str
    group_value: str
    entity_count: int
    run_count: int
    paper_count: int


class EntitiesResponse(BaseModel):
    items: List[EntityListItem]
    aggregates: Optional[List[EntityAggregateItem]] = None


class EntityDetail(BaseModel):
    item: EntityListItem
    entity: Dict[str, Any]
    evidence: Optional[Dict[str, List[EvidenceItem]]] = None
    missing_evidence_fields: List[str] = Field(default_factory=list)
    run: Dict[str, Any]
    paper: Dict[str, Any]
    prompts: Optional[Dict[str, Any]] = None


class KpiBucket(BaseModel):
    value: str
    count: int


class EntityKpis(BaseModel):
    total_entities: int
    missing_evidence_count: int
    invalid_count: int
    missing_evidence_pct: float
    invalid_pct: float
    top_morphology: List[KpiBucket] = Field(default_factory=list)
    top_validation_methods: List[KpiBucket] = Field(default_factory=list)
    top_missing_fields: List[KpiBucket] = Field(default_factory=list)


class PaperExtractionsItem(BaseModel):
    id: int
    run_id: Optional[int] = None
    storage: str
    entity_type: Optional[str] = None
    sequence_one_letter: Optional[str] = None
    sequence_three_letter: Optional[str] = None
    n_terminal_mod: Optional[str] = None
    c_terminal_mod: Optional[str] = None
    chemical_formula: Optional[str] = None
    smiles: Optional[str] = None
    inchi: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    morphology: List[str] = Field(default_factory=list)
    ph: Optional[float] = None
    concentration: Optional[float] = None
    concentration_units: Optional[str] = None
    temperature_c: Optional[float] = None
    is_hydrogel: Optional[bool] = None
    cac: Optional[float] = None
    cgc: Optional[float] = None
    mgc: Optional[float] = None
    validation_methods: List[str] = Field(default_factory=list)
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    created_at: Optional[str] = None


class PaperExtractionsPaper(BaseModel):
    id: int
    title: str
    doi: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)


class PaperExtractionsResponse(BaseModel):
    paper: PaperExtractionsPaper
    extractions: List[PaperExtractionsItem]
