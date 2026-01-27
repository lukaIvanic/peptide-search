from __future__ import annotations

from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, field_validator


class SearchItem(BaseModel):
	"""A search result item with optional processing status."""
	title: str
	doi: Optional[str] = None
	url: Optional[str] = None
	pdf_url: Optional[str] = None  # Direct link to free PDF
	source: Optional[str] = None
	year: Optional[int] = None
	authors: List[str] = Field(default_factory=list)
	# Processing status flags (populated by search endpoint)
	seen: bool = False  # Paper exists in database
	processed: bool = False  # Paper has at least one successful extraction


class SearchResponse(BaseModel):
	results: List[SearchItem]


# --- Enqueue models ---

class EnqueueItem(BaseModel):
	"""A paper to enqueue for extraction."""
	title: str
	doi: Optional[str] = None
	url: Optional[str] = None
	pdf_url: str  # Required for extraction
	source: Optional[str] = None
	year: Optional[int] = None
	authors: List[str] = Field(default_factory=list)
	force: bool = False  # Force re-extract even if already processed


class EnqueueRequest(BaseModel):
	"""Request to enqueue papers for extraction."""
	papers: List[EnqueueItem]
	provider: str = "openai"  # openai | mock
	prompt_id: Optional[int] = None


class EnqueuedRun(BaseModel):
	"""Info about an enqueued run."""
	run_id: int
	paper_id: int
	title: str
	status: str
	skipped: bool = False  # True if skipped due to already processed
	skip_reason: Optional[str] = None


class EnqueueResponse(BaseModel):
	"""Response from enqueue endpoint."""
	runs: List[EnqueuedRun]
	total: int
	enqueued: int
	skipped: int


# --- Baseline models ---

class BaselineDatasetInfo(BaseModel):
	id: str
	label: Optional[str] = None
	description: Optional[str] = None
	count: int = 0


class BaselineRunSummary(BaseModel):
	run_id: int
	paper_id: Optional[int] = None
	status: str
	failure_reason: Optional[str] = None
	created_at: Optional[str] = None
	model_provider: Optional[str] = None
	model_name: Optional[str] = None


class BaselineCase(BaseModel):
	id: str
	dataset: str
	sequence: Optional[str] = None
	n_terminal: Optional[str] = None
	c_terminal: Optional[str] = None
	labels: List[str] = Field(default_factory=list)
	doi: Optional[str] = None
	pubmed_id: Optional[str] = None
	paper_url: Optional[str] = None
	pdf_url: Optional[str] = None
	metadata: Dict[str, Any] = Field(default_factory=dict)


class BaselineCaseSummary(BaselineCase):
	latest_run: Optional[BaselineRunSummary] = None


class BaselineCasesResponse(BaseModel):
	cases: List[BaselineCaseSummary]
	datasets: List[BaselineDatasetInfo]
	total_cases: int


class BaselineEnqueuedRun(BaseModel):
	baseline_case_id: str
	run_id: Optional[int] = None
	status: Optional[str] = None
	skipped: bool = False
	skip_reason: Optional[str] = None


class BaselineEnqueueRequest(BaseModel):
	provider: str = "openai"
	prompt_id: Optional[int] = None
	force: bool = False
	dataset: Optional[str] = None


class BaselineEnqueueResponse(BaseModel):
	runs: List[BaselineEnqueuedRun]
	total: int
	enqueued: int
	skipped: int


class ResolvedSourceResponse(BaseModel):
	found: bool
	title: Optional[str] = None
	doi: Optional[str] = None
	url: Optional[str] = None
	pdf_url: Optional[str] = None
	source: Optional[str] = None
	year: Optional[int] = None
	authors: List[str] = Field(default_factory=list)


class BaselineRetryRequest(BaseModel):
	source_url: Optional[str] = None
	provider: Optional[str] = None
	prompt_id: Optional[int] = None


class RunRetryWithSourceRequest(BaseModel):
	source_url: Optional[str] = None
	provider: Optional[str] = None
	prompt_id: Optional[int] = None


class BaselineShadowSeedRequest(BaseModel):
	dataset: Optional[str] = None
	limit: Optional[int] = None
	force: bool = False


class BaselineShadowSeedResponse(BaseModel):
	total: int
	seeded: int
	skipped: int


# --- Paper with status models ---

class PaperWithStatus(BaseModel):
	"""Paper with latest run status for the unified table."""
	id: int
	title: str
	doi: Optional[str] = None
	url: Optional[str] = None
	pdf_url: Optional[str] = None
	source: Optional[str] = None
	year: Optional[int] = None
	authors: List[str] = Field(default_factory=list)
	# Latest run info
	latest_run_id: Optional[int] = None
	status: Optional[str] = None  # queued, fetching, provider, validating, stored, failed
	failure_reason: Optional[str] = None
	last_run_at: Optional[str] = None
	run_count: int = 0


class PapersWithStatusResponse(BaseModel):
	"""Response for papers list with status."""
	papers: List[PaperWithStatus]
	# Queue stats
	queue_stats: Optional[dict] = None


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

	@field_validator("labels", "morphology", "validation_methods", "reported_characteristics", mode="before")
	@classmethod
	def _coerce_none_lists(cls, value):
		# LLMs sometimes emit null for list fields; treat it as empty list.
		return [] if value is None else value


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
	comment: Optional[str] = None  # Model's brief explanation of what was found/not found


class ExtractRequest(BaseModel):
	# Either provide text directly, or a URL to fetch (PDF/HTML)
	text: Optional[str] = None
	pdf_url: Optional[str] = None
	# Optional metadata to help the model
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


class QualityRulesRequest(BaseModel):
	rules: Dict[str, Any]


class QualityRulesResponse(BaseModel):
	rules: Dict[str, Any]


class PromptVersionInfo(BaseModel):
	id: int
	prompt_id: int
	version_index: int
	content: str
	notes: Optional[str] = None
	created_by: Optional[str] = None
	created_at: Optional[str] = None


class PromptInfo(BaseModel):
	id: int
	name: str
	description: Optional[str] = None
	is_active: bool
	created_at: Optional[str] = None
	updated_at: Optional[str] = None
	latest_version: Optional[PromptVersionInfo] = None
	versions: List[PromptVersionInfo] = Field(default_factory=list)


class PromptListResponse(BaseModel):
	prompts: List[PromptInfo]
	active_prompt_id: Optional[int] = None


class PromptCreateRequest(BaseModel):
	name: str
	description: Optional[str] = None
	content: str
	notes: Optional[str] = None
	activate: bool = False
	created_by: Optional[str] = None


class PromptVersionCreateRequest(BaseModel):
	content: str
	notes: Optional[str] = None
	created_by: Optional[str] = None


class PaperRow(BaseModel):
	id: int
	title: str
	doi: Optional[str] = None
	url: Optional[str] = None
	source: Optional[str] = None
	year: Optional[int] = None
	authors: List[str] = Field(default_factory=list)
	extraction_count: int = 0


class PapersResponse(BaseModel):
	papers: List[PaperRow]


class FailureBucketItem(BaseModel):
	key: str
	label: Optional[str] = None
	count: int
	example_run_id: Optional[int] = None
	example_paper_id: Optional[int] = None
	example_title: Optional[str] = None


class FailureSummaryResponse(BaseModel):
	total_failed: int
	runs_analyzed: int
	window_days: int
	window_start: Optional[str] = None
	buckets: List[FailureBucketItem]
	providers: List[FailureBucketItem]
	sources: List[FailureBucketItem]
	reasons: List[FailureBucketItem]


class FailedRunItem(BaseModel):
	id: int
	paper_id: Optional[int] = None
	status: str
	failure_reason: Optional[str] = None
	bucket: str
	normalized_reason: str
	model_provider: Optional[str] = None
	model_name: Optional[str] = None
	created_at: Optional[str] = None
	paper_title: Optional[str] = None
	paper_doi: Optional[str] = None
	paper_url: Optional[str] = None
	paper_source: Optional[str] = None
	paper_year: Optional[int] = None


class FailedRunsResponse(BaseModel):
	items: List[FailedRunItem]
	total: int
	window_days: int
	window_start: Optional[str] = None


class BulkRetryRequest(BaseModel):
	days: int = 30
	limit: int = 25
	max_runs: int = 1000
	bucket: Optional[str] = None
	provider: Optional[str] = None
	source: Optional[str] = None
	reason: Optional[str] = None


class BulkRetryResponse(BaseModel):
	requested: int
	enqueued: int
	skipped: int
	skipped_missing_pdf: int
	skipped_missing_paper: int
	skipped_not_failed: int

