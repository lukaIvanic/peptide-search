from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import Session, select, func, or_

from .config import settings
from .db import init_db, get_session, session_scope
from .persistence.models import Paper, Extraction, ExtractionRun, ExtractionEntity, RunStatus
from .schemas import (
	SearchResponse,
	SearchItem,
	ExtractRequest,
	ExtractResponse,
	FollowupRequest,
	EditRunRequest,
	EntitiesResponse,
	EntityListItem,
	EntityDetail,
	EntityKpis,
	EntityAggregateItem,
	QualityRulesRequest,
	QualityRulesResponse,
	PaperRow,
	PapersResponse,
	EnqueueRequest,
	EnqueueResponse,
	EnqueuedRun,
	EnqueueItem,
	PaperWithStatus,
	PapersWithStatusResponse,
	FailureSummaryResponse,
	FailedRunsResponse,
	BulkRetryRequest,
	BulkRetryResponse,
)
from .services.search_service import search_all_free_sources
from .services.extraction_service import run_extraction, run_extraction_from_file, run_followup, run_followup_stream, run_edit
from .services.quality_service import (
	get_quality_rules,
	update_quality_rules,
	compute_entity_quality,
	extract_entity_payload,
)
from .services.queue_service import (
	get_queue,
	get_broadcaster,
	start_queue,
	stop_queue,
	QueueItem,
)

logger = logging.getLogger(__name__)


FAILURE_BUCKET_LABELS = {
	"pdf_download": "PDF download (provider)",
	"pdf_processing": "PDF processing failed",
	"text_extraction": "Text extraction empty",
	"fetch_error": "Fetch error",
	"unsupported_doc": "Unsupported document",
	"legacy_bug": "Legacy extraction bug",
	"validation": "Parse/validation",
	"provider": "Provider error",
	"followup": "Follow-up error",
	"missing_raw_json": "Missing parent raw JSON",
	"not_found": "Missing record",
	"queue": "Queue/worker error",
	"other": "Other",
	"unknown": "Unknown",
}


def _bucket_failure_reason(reason: Optional[str]) -> str:
	if not reason:
		return "unknown"
	lower = reason.lower()
	if "unknown failure" in lower:
		return "unknown"
	if "extractionrepository._entity_to_row" in lower or "entity_index" in lower:
		return "legacy_bug"
	if "timeout while downloading" in lower or "error while downloading" in lower:
		return "pdf_download"
	if "empty response" in lower or "couldn't be processed" in lower:
		return "pdf_download"
	if "failed to fetch the provided url" in lower:
		return "fetch_error"
	if "does not look like a pdf or html document" in lower:
		return "unsupported_doc"
	if "pdf processing failed" in lower:
		return "pdf_processing"
	if "no textual content could be extracted" in lower or "text extraction" in lower:
		return "text_extraction"
	if "parse/validation error" in lower or "failed to parse model output" in lower:
		return "validation"
	if "provider error" in lower:
		return "provider"
	if "failed to run followup" in lower or "followup" in lower:
		return "followup"
	if "prior run has no raw_json" in lower:
		return "missing_raw_json"
	if "not found" in lower:
		return "not_found"
	if "queue" in lower or "worker" in lower:
		return "queue"
	return "other"


def _normalize_failure_reason(reason: Optional[str]) -> str:
	if not reason:
		return "Unknown failure"
	lower = reason.lower()
	if "unknown failure" in lower:
		return "Unknown failure"
	if "extractionrepository._entity_to_row" in lower or "entity_index" in lower:
		return "Legacy entity index bug"
	if "parse/validation error" in lower or "failed to parse model output" in lower:
		return "Parse/validation error"
	if "provider error" in lower:
		return "Provider error"
	if "failed to fetch the provided url" in lower:
		return "Fetch error"
	if "does not look like a pdf or html document" in lower:
		return "Unsupported document"
	if "timeout while downloading" in lower or "error while downloading" in lower:
		return "PDF download error"
	if "empty response" in lower or "couldn't be processed" in lower:
		return "PDF processing error"
	if "pdf processing failed" in lower:
		return "PDF processing failed"
	if "no textual content could be extracted" in lower or "text extraction" in lower:
		return "Text extraction empty"
	if "prior run has no raw_json" in lower:
		return "Parent run missing raw JSON"
	if "not found" in lower:
		return "Record not found"
	return reason[:120]


def create_app() -> FastAPI:
	app = FastAPI(title=settings.APP_NAME)
	cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
	if cors_origins:
		app.add_middleware(
			CORSMiddleware,
			allow_origins=cors_origins,
			allow_credentials=True,
			allow_methods=["*"],
			allow_headers=["*"],
		)

	def _parse_json_list(value: Optional[str]) -> List[str]:
		if not value:
			return []
		try:
			parsed = json.loads(value)
			return parsed if isinstance(parsed, list) else []
		except Exception:
			return []

	def _backfill_failed_runs() -> None:
		with session_scope() as session:
			stmt = select(ExtractionRun).where(ExtractionRun.status == RunStatus.FAILED.value)
			updated = 0
			for run in session.exec(stmt).all():
				changed = False
				if not run.failure_reason:
					run.failure_reason = "Unknown failure (missing reason)"
					changed = True
				if not run.raw_json:
					run.raw_json = json.dumps({"error": run.failure_reason or "Unknown failure"})
					changed = True
				if changed:
					session.add(run)
					updated += 1
			if updated:
				logger.info(f"Backfilled {updated} failed runs missing metadata")

	# Initialize DB and queue at startup
	@app.on_event("startup")
	async def _startup() -> None:
		init_db()
		_backfill_failed_runs()
		# Start the extraction queue
		await start_queue()
		# Set up extraction callback
		from .services.extraction_service import run_queued_extraction
		queue = get_queue()
		queue.set_extract_callback(run_queued_extraction)
		logger.info("Application started")
	
	@app.on_event("shutdown")
	async def _shutdown() -> None:
		await stop_queue()
		logger.info("Application shutdown")

	# Serve static frontend
	static_dir: Path = settings.STATIC_DIR
	if static_dir.exists():
		app.mount("/static", StaticFiles(directory=str(static_dir), html=False), name="static")

		@app.get("/", include_in_schema=False)
		async def index() -> FileResponse:
			return FileResponse(static_dir / "index.html")

		@app.get("/runs/{run_id}", include_in_schema=False)
		async def run_detail(run_id: int) -> FileResponse:
			return FileResponse(static_dir / "run.html")

		@app.get("/runs/{run_id}/edit", include_in_schema=False)
		async def run_edit_page(run_id: int) -> FileResponse:
			return FileResponse(static_dir / "run_editor.html")

		@app.get("/entities", include_in_schema=False)
		async def entities_page() -> FileResponse:
			return FileResponse(static_dir / "entities.html")

		@app.get("/help", include_in_schema=False)
		async def help_page() -> FileResponse:
			return FileResponse(static_dir / "help.html")

	@app.get("/api/health")
	async def health() -> dict:
		# Include model name for display
		model = None
		if settings.LLM_PROVIDER == "openai":
			model = settings.OPENAI_MODEL
		elif settings.LLM_PROVIDER == "deepseek":
			model = settings.DEEPSEEK_MODEL
		return {"status": "ok", "provider": settings.LLM_PROVIDER, "model": model}

	@app.get("/api/search", response_model=SearchResponse)
	async def search(
		q: str = Query(..., min_length=2),
		rows: int = 10,
		session: Session = Depends(get_session),
	) -> SearchResponse:
		# Search only free full-text sources (PMC, arXiv, Europe PMC, Semantic Scholar)
		results = await search_all_free_sources(q, per_source=rows)
		
		# Add seen/processed flags based on database
		# Get all DOIs and URLs from results
		dois = [r.doi for r in results if r.doi]
		urls = [r.url for r in results if r.url]
		pdf_urls = [r.pdf_url for r in results if r.pdf_url]
		all_urls = list(set(urls + pdf_urls))
		
		# Query papers that match any of these identifiers
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
		
		# Check which papers have successful extractions
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
		
		# Update results with flags
		enriched_results: List[SearchItem] = []
		for r in results:
			paper = None
			if r.doi and r.doi.lower() in existing_papers:
				paper = existing_papers[r.doi.lower()]
			elif r.url and r.url.lower() in existing_papers:
				paper = existing_papers[r.url.lower()]
			
			seen = paper is not None
			processed = paper.id in processed_paper_ids if paper and paper.id else False
			
			enriched_results.append(SearchItem(
				title=r.title,
				doi=r.doi,
				url=r.url,
				pdf_url=r.pdf_url,
				source=r.source,
				year=r.year,
				authors=r.authors,
				seen=seen,
				processed=processed,
			))
		
		return SearchResponse(results=enriched_results)

	@app.post("/api/enqueue", response_model=EnqueueResponse)
	async def enqueue_papers(
		req: EnqueueRequest,
		session: Session = Depends(get_session),
	) -> EnqueueResponse:
		"""Enqueue papers for batch extraction."""
		queue = get_queue()
		runs: List[EnqueuedRun] = []
		enqueued = 0
		skipped = 0
		
		for item in req.papers:
			# Check if paper already exists
			paper = None
			if item.doi:
				stmt = select(Paper).where(Paper.doi == item.doi)
				paper = session.exec(stmt).first()
			if not paper and item.url:
				stmt = select(Paper).where(Paper.url == item.url)
				paper = session.exec(stmt).first()
			
			# Check if already processed (unless force=True)
			if paper and not item.force:
				stmt = (
					select(ExtractionRun)
					.where(ExtractionRun.paper_id == paper.id)
					.where(ExtractionRun.status == RunStatus.STORED.value)
					.limit(1)
				)
				existing_run = session.exec(stmt).first()
				if existing_run:
					runs.append(EnqueuedRun(
						run_id=existing_run.id,
						paper_id=paper.id,
						title=item.title,
						status=existing_run.status,
						skipped=True,
						skip_reason="Already processed",
					))
					skipped += 1
					continue
			
			# Create or update paper
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
			
			# Create a new run in QUEUED status
			run = ExtractionRun(
				paper_id=paper.id,
				status=RunStatus.QUEUED.value,
				model_provider=req.provider,
				pdf_url=item.pdf_url,
			)
			session.add(run)
			session.commit()
			session.refresh(run)
			
			# Add to queue
			await queue.enqueue(QueueItem(
				run_id=run.id,
				paper_id=paper.id,
				pdf_url=item.pdf_url,
				title=item.title,
				provider=req.provider,
				force=item.force,
			))
			
			runs.append(EnqueuedRun(
				run_id=run.id,
				paper_id=paper.id,
				title=item.title,
				status=run.status,
				skipped=False,
			))
			enqueued += 1
		
		return EnqueueResponse(
			runs=runs,
			total=len(req.papers),
			enqueued=enqueued,
			skipped=skipped,
		)

	@app.get("/api/stream")
	async def stream_events():
		"""SSE endpoint for live status updates."""
		broadcaster = get_broadcaster()
		queue = await broadcaster.subscribe()
		
		async def event_generator():
			try:
				# Send initial connection message
				yield f"data: {json.dumps({'event': 'connected', 'timestamp': ''})}\n\n"
				
				while True:
					try:
						message = await asyncio.wait_for(queue.get(), timeout=30.0)
						yield f"data: {json.dumps(message)}\n\n"
					except asyncio.TimeoutError:
						# Send keepalive
						yield f": keepalive\n\n"
			except asyncio.CancelledError:
				pass
			finally:
				await broadcaster.unsubscribe(queue)
		
		return StreamingResponse(
			event_generator(),
			media_type="text/event-stream",
			headers={
				"Cache-Control": "no-cache",
				"Connection": "keep-alive",
				"X-Accel-Buffering": "no",
			},
		)


	@app.post("/api/extract", response_model=ExtractResponse)
	async def extract(req: ExtractRequest, session: Session = Depends(get_session)) -> ExtractResponse:
		if not (req.text or req.pdf_url):
			raise HTTPException(status_code=400, detail="Provide either 'text' or 'pdf_url'.")

		try:
			extraction_id, paper_id, payload = await run_extraction(session, req)
		except (ValueError, RuntimeError) as exc:
			raise HTTPException(status_code=400, detail=str(exc)) from exc

		return ExtractResponse(extraction=payload, extraction_id=extraction_id, paper_id=paper_id)

	@app.post("/api/extract-file", response_model=ExtractResponse)
	async def extract_file(
		file: UploadFile = File(...),
		title: Optional[str] = Form(None),
		session: Session = Depends(get_session),
	) -> ExtractResponse:
		# Validate file type
		if not file.filename:
			raise HTTPException(status_code=400, detail="No file provided")
		
		if not file.filename.lower().endswith(".pdf"):
			raise HTTPException(status_code=400, detail="Only PDF files are supported")
		
		# Read file content
		content = await file.read()
		if len(content) == 0:
			raise HTTPException(status_code=400, detail="Empty file")
		
		# Limit file size (20MB)
		if len(content) > 20 * 1024 * 1024:
			raise HTTPException(status_code=400, detail="File too large (max 20MB)")

		try:
			extraction_id, paper_id, payload = await run_extraction_from_file(
				session=session,
				file_content=content,
				filename=file.filename,
				title=title,
			)
		except (ValueError, RuntimeError) as exc:
			raise HTTPException(status_code=400, detail=str(exc)) from exc

		return ExtractResponse(extraction=payload, extraction_id=extraction_id, paper_id=paper_id)

	@app.get("/api/papers", response_model=PapersWithStatusResponse)
	async def list_papers(session: Session = Depends(get_session)) -> PapersWithStatusResponse:
		"""List all papers with their latest run status."""
		# Subquery to get the latest run for each paper
		latest_run_subq = (
			select(
				ExtractionRun.paper_id,
				func.max(ExtractionRun.id).label("latest_run_id"),
			)
			.group_by(ExtractionRun.paper_id)
			.subquery()
		)
		
		# Subquery to count runs per paper
		run_count_subq = (
			select(
				ExtractionRun.paper_id,
				func.count(ExtractionRun.id).label("run_count"),
			)
			.group_by(ExtractionRun.paper_id)
			.subquery()
		)
		
		# Main query: papers with latest run info
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
		items: List[PaperWithStatus] = []
		
		for paper, latest_run, run_count in rows:
			authors = []
			if paper.authors_json:
				try:
					authors = json.loads(paper.authors_json)
				except Exception:
					authors = []
			
			# Get PDF URL from latest run if available
			pdf_url = latest_run.pdf_url if latest_run else None
			
			items.append(PaperWithStatus(
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
			))
		
		# Get queue stats
		queue = get_queue()
		stats = await queue.get_stats()
		
		return PapersWithStatusResponse(
			papers=items,
			queue_stats={
				"queued": stats.queued,
				"processing": stats.processing,
			},
		)

	@app.get("/api/papers/{paper_id}/extractions")
	async def get_paper_extractions(paper_id: int, session: Session = Depends(get_session)) -> dict:
		paper = session.get(Paper, paper_id)
		if not paper:
			raise HTTPException(status_code=404, detail="Paper not found")
		
		# Get paper authors
		authors = []
		if paper.authors_json:
			try:
				authors = json.loads(paper.authors_json)
			except Exception:
				authors = []
		
		# Return combined view: normalized entities + legacy extraction rows.
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

	@app.get("/api/extractions")
	async def list_extractions(session: Session = Depends(get_session)) -> list[dict]:
		# IMPORTANT: we only list ONE "extraction" type here to avoid ID collisions.
		# - If there are any ExtractionRuns, list runs (new schema)
		# - Otherwise, list legacy Extraction rows (old schema)
		has_run = session.exec(select(ExtractionRun.id).limit(1)).first()
		if has_run:
			subq = (
				select(ExtractionEntity.run_id, func.count(ExtractionEntity.id).label("cnt"))
				.group_by(ExtractionEntity.run_id)
				.subquery()
			)
			stmt = (
				select(ExtractionRun, subq.c.cnt)
				.outerjoin(subq, ExtractionRun.id == subq.c.run_id)
				.order_by(ExtractionRun.created_at.desc())
				.limit(200)
			)
			rows = session.exec(stmt).all()
			result: list[dict] = []
			for run, cnt in rows:
				result.append(
					{
						"id": run.id,
						"paper_id": run.paper_id,
						"entity_count": int(cnt or 0),
						"comment": run.comment,
						"model_provider": run.model_provider,
						"model_name": run.model_name,
						"created_at": run.created_at.isoformat() + "Z",
					}
				)
			return result
		
		# Legacy fallback (pre-normalization DBs)
		stmt = select(Extraction).order_by(Extraction.created_at.desc()).limit(200)
		rows = session.exec(stmt).all()
		result: list[dict] = []
		for r in rows:
			result.append(
				{
					"id": r.id,
					"paper_id": r.paper_id,
					"entity_type": r.entity_type,
					"sequence": r.peptide_sequence_one_letter,
					"chemical_formula": r.chemical_formula,
					"labels": json.loads(r.labels) if r.labels else [],
					"morphology": json.loads(r.morphology) if r.morphology else [],
					"created_at": r.created_at.isoformat() + "Z",
				}
			)
		return result

	@app.get("/api/extractions/{extraction_id}")
	async def get_extraction(extraction_id: int, session: Session = Depends(get_session)) -> dict:
		has_run = session.exec(select(ExtractionRun.id).limit(1)).first()
		if has_run:
			run = session.get(ExtractionRun, extraction_id)
			if not run:
				raise HTTPException(status_code=404, detail="ExtractionRun not found")
			try:
				payload = json.loads(run.raw_json or "{}")
			except Exception:
				payload = {}
			return {
				"id": run.id,
				"paper_id": run.paper_id,
				"payload": payload,
				"model_provider": run.model_provider,
				"model_name": run.model_name,
				"created_at": run.created_at.isoformat() + "Z",
			}
		
		# Legacy fallback (pre-normalization DBs)
		row = session.get(Extraction, extraction_id)
		if not row:
			raise HTTPException(status_code=404, detail="Extraction not found")
		try:
			payload = json.loads(row.raw_json or "{}")
		except Exception:
			payload = {}
		return {
			"id": row.id,
			"paper_id": row.paper_id,
			"payload": payload,
			"model_provider": row.model_provider,
			"model_name": row.model_name,
			"created_at": row.created_at.isoformat() + "Z",
		}

	@app.get("/api/quality-rules", response_model=QualityRulesResponse)
	async def get_quality_rules_endpoint(session: Session = Depends(get_session)) -> QualityRulesResponse:
		rules = get_quality_rules(session)
		return QualityRulesResponse(rules=rules)

	@app.post("/api/quality-rules", response_model=QualityRulesResponse)
	async def update_quality_rules_endpoint(
		req: QualityRulesRequest,
		session: Session = Depends(get_session),
	) -> QualityRulesResponse:
		rules = update_quality_rules(session, req.rules)
		return QualityRulesResponse(rules=rules)

	@app.get("/api/entities", response_model=EntitiesResponse)
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
			cutoff = datetime.utcnow() - timedelta(minutes=recent_minutes)
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

			items.append(EntityListItem(
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
				labels=_parse_json_list(entity.labels),
				morphology=_parse_json_list(entity.morphology),
				validation_methods=_parse_json_list(entity.validation_methods),
				reported_characteristics=_parse_json_list(entity.reported_characteristics),
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
				run_created_at=run.created_at.isoformat() + "Z" if run.created_at else None,
				model_provider=run.model_provider,
				model_name=run.model_name,
				prompt_version=run.prompt_version,
			))

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

	@app.get("/api/entities/kpis", response_model=EntityKpis)
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
			cutoff = datetime.utcnow() - timedelta(minutes=recent_minutes)
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

			for value in _parse_json_list(entity.morphology):
				morphology_counts[value] = morphology_counts.get(value, 0) + 1
			for value in _parse_json_list(entity.validation_methods):
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

	@app.get("/api/entities/{entity_id}", response_model=EntityDetail)
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
			labels=_parse_json_list(entity.labels),
			morphology=_parse_json_list(entity.morphology),
			validation_methods=_parse_json_list(entity.validation_methods),
			reported_characteristics=_parse_json_list(entity.reported_characteristics),
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
			run_created_at=run.created_at.isoformat() + "Z" if run and run.created_at else None,
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
			"created_at": run.created_at.isoformat() + "Z" if run and run.created_at else None,
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


	@app.get("/api/runs")
	async def list_runs(
		paper_id: int = Query(...),
		session: Session = Depends(get_session),
	) -> dict:
		"""List all runs for a paper, including prompts and raw JSON."""
		paper = session.get(Paper, paper_id)
		if not paper:
			raise HTTPException(status_code=404, detail="Paper not found")
		
		# Get paper info
		authors = []
		if paper.authors_json:
			try:
				authors = json.loads(paper.authors_json)
			except Exception:
				authors = []
		
		# Get all runs for this paper, newest first
		stmt = (
			select(ExtractionRun)
			.where(ExtractionRun.paper_id == paper_id)
			.order_by(ExtractionRun.created_at.desc())
		)
		runs = session.exec(stmt).all()
		
		# Count entities per run
		entity_counts: dict[int, int] = {}
		if runs:
			run_ids = [r.id for r in runs if r.id]
			count_stmt = (
				select(ExtractionEntity.run_id, func.count(ExtractionEntity.id))
				.where(ExtractionEntity.run_id.in_(run_ids))
				.group_by(ExtractionEntity.run_id)
			)
			for run_id, cnt in session.exec(count_stmt).all():
				entity_counts[run_id] = cnt
		
		runs_data = []
		for run in runs:
			# Parse prompts_json if available
			prompts = None
			if run.prompts_json:
				try:
					prompts = json.loads(run.prompts_json)
				except Exception:
					prompts = {"raw": run.prompts_json}
			
			# Parse raw_json if available
			raw_json = None
			if run.raw_json:
				try:
					raw_json = json.loads(run.raw_json)
				except Exception:
					raw_json = {"raw": run.raw_json}
			
			runs_data.append({
				"id": run.id,
				"paper_id": run.paper_id,
			"parent_run_id": run.parent_run_id,
				"status": run.status,
				"failure_reason": run.failure_reason,
				"prompts": prompts,
				"raw_json": raw_json,
				"comment": run.comment,
				"model_provider": run.model_provider,
				"model_name": run.model_name,
				"pdf_url": run.pdf_url,
				"entity_count": entity_counts.get(run.id, 0),
				"created_at": run.created_at.isoformat() + "Z" if run.created_at else None,
			})
		
		# Get latest run status for the paper
		latest_status = runs[0].status if runs else None
		
		return {
			"paper": {
				"id": paper.id,
				"title": paper.title,
				"doi": paper.doi,
				"url": paper.url,
				"source": paper.source,
				"year": paper.year,
				"authors": authors,
				"status": latest_status,
			},
			"runs": runs_data,
		}

	@app.get("/api/runs/recent")
	async def list_recent_runs(
		status: Optional[str] = Query(default=None),
		limit: int = Query(default=10, ge=1, le=50),
		session: Session = Depends(get_session),
	) -> dict:
		stmt = select(ExtractionRun).order_by(ExtractionRun.created_at.desc()).limit(limit)
		if status:
			stmt = stmt.where(ExtractionRun.status == status)
		runs = session.exec(stmt).all()
		results = []
		for run in runs:
			paper = session.get(Paper, run.paper_id) if run.paper_id else None
			results.append({
				"id": run.id,
				"paper_id": run.paper_id,
				"status": run.status,
				"failure_reason": run.failure_reason,
				"model_provider": run.model_provider,
				"model_name": run.model_name,
				"created_at": run.created_at.isoformat() + "Z" if run.created_at else None,
				"paper": {
					"id": paper.id if paper else None,
					"title": paper.title if paper else None,
					"doi": paper.doi if paper else None,
					"url": paper.url if paper else None,
					"source": paper.source if paper else None,
					"year": paper.year if paper else None,
				},
			})
		return {"runs": results}

	@app.get("/api/runs/failure-summary", response_model=FailureSummaryResponse)
	async def get_failure_summary(
		days: int = Query(default=30, ge=1, le=365),
		max_runs: int = Query(default=1000, ge=50, le=10000),
		session: Session = Depends(get_session),
	) -> FailureSummaryResponse:
		cutoff = datetime.utcnow() - timedelta(days=days)
		stmt = (
			select(ExtractionRun, Paper)
			.join(Paper, ExtractionRun.paper_id == Paper.id, isouter=True)
			.where(ExtractionRun.status == RunStatus.FAILED.value)
			.where(ExtractionRun.created_at >= cutoff)
			.order_by(ExtractionRun.created_at.desc())
			.limit(max_runs)
		)
		rows = session.exec(stmt).all()
		bucket_counts: dict = {}
		provider_counts: dict = {}
		source_counts: dict = {}
		reason_counts: dict = {}

		def _bump(target: dict, key: str, label: Optional[str], run: ExtractionRun, paper: Optional[Paper]) -> None:
			entry = target.get(key)
			if not entry:
				entry = {
					"key": key,
					"label": label or key,
					"count": 0,
					"example_run_id": None,
					"example_paper_id": None,
					"example_title": None,
				}
				target[key] = entry
			entry["count"] += 1
			if entry["example_run_id"] is None:
				entry["example_run_id"] = run.id
				entry["example_paper_id"] = run.paper_id
				entry["example_title"] = paper.title if paper else None

		for run, paper in rows:
			bucket_key = _bucket_failure_reason(run.failure_reason)
			_bump(bucket_counts, bucket_key, FAILURE_BUCKET_LABELS.get(bucket_key, bucket_key), run, paper)
			provider_key = run.model_provider or "unknown"
			_bump(provider_counts, provider_key, provider_key, run, paper)
			source_key = paper.source if paper and paper.source else "unknown"
			_bump(source_counts, source_key, source_key, run, paper)
			reason_key = _normalize_failure_reason(run.failure_reason)
			_bump(reason_counts, reason_key, reason_key, run, paper)

		def _sorted(values: dict) -> list:
			return sorted(values.values(), key=lambda item: item["count"], reverse=True)

		window_start = cutoff.isoformat() + "Z"
		return FailureSummaryResponse(
			total_failed=len(rows),
			runs_analyzed=len(rows),
			window_days=days,
			window_start=window_start,
			buckets=_sorted(bucket_counts),
			providers=_sorted(provider_counts),
			sources=_sorted(source_counts),
			reasons=_sorted(reason_counts),
		)

	@app.get("/api/runs/failures", response_model=FailedRunsResponse)
	async def list_failed_runs(
		days: int = Query(default=30, ge=1, le=365),
		limit: int = Query(default=25, ge=1, le=200),
		max_runs: int = Query(default=1000, ge=50, le=10000),
		bucket: Optional[str] = Query(default=None),
		provider: Optional[str] = Query(default=None),
		source: Optional[str] = Query(default=None),
		reason: Optional[str] = Query(default=None),
		session: Session = Depends(get_session),
	) -> FailedRunsResponse:
		cutoff = datetime.utcnow() - timedelta(days=days)
		stmt = (
			select(ExtractionRun, Paper)
			.join(Paper, ExtractionRun.paper_id == Paper.id, isouter=True)
			.where(ExtractionRun.status == RunStatus.FAILED.value)
			.where(ExtractionRun.created_at >= cutoff)
			.order_by(ExtractionRun.created_at.desc())
			.limit(max_runs)
		)
		if provider:
			stmt = stmt.where(ExtractionRun.model_provider == provider)
		if source:
			stmt = stmt.where(Paper.source == source)
		rows = session.exec(stmt).all()
		items = []
		for run, paper in rows:
			bucket_key = _bucket_failure_reason(run.failure_reason)
			normalized_reason = _normalize_failure_reason(run.failure_reason)
			if bucket and bucket_key != bucket:
				continue
			if reason and normalized_reason != reason:
				continue
			items.append({
				"id": run.id,
				"paper_id": run.paper_id,
				"status": run.status,
				"failure_reason": run.failure_reason,
				"bucket": bucket_key,
				"normalized_reason": normalized_reason,
				"model_provider": run.model_provider,
				"model_name": run.model_name,
				"created_at": run.created_at.isoformat() + "Z" if run.created_at else None,
				"paper_title": paper.title if paper else None,
				"paper_doi": paper.doi if paper else None,
				"paper_url": paper.url if paper else None,
				"paper_source": paper.source if paper else None,
				"paper_year": paper.year if paper else None,
			})
			if len(items) >= limit:
				break

		window_start = cutoff.isoformat() + "Z"
		return FailedRunsResponse(
			items=items,
			total=len(items),
			window_days=days,
			window_start=window_start,
		)

	@app.post("/api/runs/failures/retry", response_model=BulkRetryResponse)
	async def retry_failed_runs(
		req: BulkRetryRequest,
		session: Session = Depends(get_session),
	) -> BulkRetryResponse:
		cutoff = datetime.utcnow() - timedelta(days=req.days)
		stmt = (
			select(ExtractionRun, Paper)
			.join(Paper, ExtractionRun.paper_id == Paper.id, isouter=True)
			.where(ExtractionRun.status == RunStatus.FAILED.value)
			.where(ExtractionRun.created_at >= cutoff)
			.order_by(ExtractionRun.created_at.desc())
			.limit(req.max_runs)
		)
		if req.provider:
			stmt = stmt.where(ExtractionRun.model_provider == req.provider)
		if req.source:
			stmt = stmt.where(Paper.source == req.source)
		rows = session.exec(stmt).all()

		requested = 0
		enqueued = 0
		skipped = 0
		skipped_missing_pdf = 0
		skipped_missing_paper = 0
		skipped_not_failed = 0
		to_enqueue: List[QueueItem] = []

		for run, paper in rows:
			bucket_key = _bucket_failure_reason(run.failure_reason)
			normalized_reason = _normalize_failure_reason(run.failure_reason)
			if req.bucket and bucket_key != req.bucket:
				continue
			if req.reason and normalized_reason != req.reason:
				continue
			if requested >= req.limit:
				break
			requested += 1

			if run.status != RunStatus.FAILED.value:
				skipped_not_failed += 1
				continue
			if not paper:
				skipped_missing_paper += 1
				skipped += 1
				continue
			if not run.pdf_url:
				skipped_missing_pdf += 1
				skipped += 1
				continue

			run.status = RunStatus.QUEUED.value
			run.failure_reason = None
			session.add(run)
			to_enqueue.append(QueueItem(
				run_id=run.id,
				paper_id=paper.id,
				pdf_url=run.pdf_url,
				title=paper.title or "(Untitled)",
				provider=run.model_provider or settings.LLM_PROVIDER,
				force=True,
			))

		if to_enqueue:
			session.commit()
			queue = get_queue()
			for item in to_enqueue:
				await queue.enqueue(item)
				enqueued += 1
		else:
			session.commit()

		if requested > (enqueued + skipped + skipped_not_failed):
			skipped += requested - (enqueued + skipped + skipped_not_failed)

		return BulkRetryResponse(
			requested=requested,
			enqueued=enqueued,
			skipped=skipped,
			skipped_missing_pdf=skipped_missing_pdf,
			skipped_missing_paper=skipped_missing_paper,
			skipped_not_failed=skipped_not_failed,
		)

	@app.get("/api/runs/{run_id}")
	async def get_run(run_id: int, session: Session = Depends(get_session)) -> dict:
		run = session.get(ExtractionRun, run_id)
		if not run:
			raise HTTPException(status_code=404, detail="Run not found")

		paper = session.get(Paper, run.paper_id) if run.paper_id else None
		authors = []
		if paper and paper.authors_json:
			try:
				authors = json.loads(paper.authors_json)
			except Exception:
				authors = []

		prompts = None
		if run.prompts_json:
			try:
				prompts = json.loads(run.prompts_json)
			except Exception:
				prompts = {"raw": run.prompts_json}

		raw_json = None
		if run.raw_json:
			try:
				raw_json = json.loads(run.raw_json)
			except Exception:
				raw_json = {"raw": run.raw_json}

		return {
			"paper": {
				"id": paper.id if paper else None,
				"title": paper.title if paper else None,
				"doi": paper.doi if paper else None,
				"url": paper.url if paper else None,
				"source": paper.source if paper else None,
				"year": paper.year if paper else None,
				"authors": authors,
			},
			"run": {
				"id": run.id,
				"paper_id": run.paper_id,
				"parent_run_id": run.parent_run_id,
				"status": run.status,
				"failure_reason": run.failure_reason,
				"prompts": prompts,
				"raw_json": raw_json,
				"comment": run.comment,
				"model_provider": run.model_provider,
				"model_name": run.model_name,
				"pdf_url": run.pdf_url,
				"created_at": run.created_at.isoformat() + "Z" if run.created_at else None,
			},
		}

	@app.post("/api/runs/{run_id}/followup", response_model=ExtractResponse)
	async def followup_run(
		run_id: int,
		req: FollowupRequest,
		session: Session = Depends(get_session),
	) -> ExtractResponse:
		try:
			new_run_id, paper_id, payload = await run_followup(
				session=session,
				parent_run_id=run_id,
				instruction=req.instruction,
				provider_name=req.provider,
			)
		except (ValueError, RuntimeError) as exc:
			raise HTTPException(status_code=400, detail=str(exc)) from exc

		return ExtractResponse(extraction=payload, extraction_id=new_run_id, paper_id=paper_id)

	@app.post("/api/runs/{run_id}/followup-stream")
	async def followup_run_stream(
		run_id: int,
		req: FollowupRequest,
		session: Session = Depends(get_session),
	) -> StreamingResponse:
		async def event_generator():
			async for event in run_followup_stream(
				session=session,
				parent_run_id=run_id,
				instruction=req.instruction,
				provider_name=req.provider,
			):
				payload = json.dumps(event.get("data", {}))
				yield f"event: {event.get('event', 'message')}\n"
				yield f"data: {payload}\n\n"

		return StreamingResponse(
			event_generator(),
			media_type="text/event-stream",
			headers={
				"Cache-Control": "no-cache",
				"Connection": "keep-alive",
				"X-Accel-Buffering": "no",
			},
		)

	@app.post("/api/runs/{run_id}/edit", response_model=ExtractResponse)
	async def edit_run(
		run_id: int,
		req: EditRunRequest,
		session: Session = Depends(get_session),
	) -> ExtractResponse:
		try:
			new_run_id, paper_id, payload = run_edit(
				session=session,
				parent_run_id=run_id,
				payload=req.payload,
				reason=req.reason,
			)
		except (ValueError, RuntimeError) as exc:
			raise HTTPException(status_code=400, detail=str(exc)) from exc

		return ExtractResponse(extraction=payload, extraction_id=new_run_id, paper_id=paper_id)

	@app.get("/api/runs/{run_id}/history")
	async def get_run_history(run_id: int, session: Session = Depends(get_session)) -> dict:
		run = session.get(ExtractionRun, run_id)
		if not run:
			raise HTTPException(status_code=404, detail="Run not found")
		stmt = (
			select(ExtractionRun)
			.where(ExtractionRun.paper_id == run.paper_id)
			.order_by(ExtractionRun.created_at.desc())
		)
		versions = []
		for item in session.exec(stmt).all():
			versions.append({
				"id": item.id,
				"parent_run_id": item.parent_run_id,
				"status": item.status,
				"model_provider": item.model_provider,
				"model_name": item.model_name,
				"created_at": item.created_at.isoformat() + "Z" if item.created_at else None,
			})
		return {"paper_id": run.paper_id, "versions": versions}

	@app.post("/api/runs/{run_id}/retry")
	async def retry_run(
		run_id: int,
		session: Session = Depends(get_session),
	) -> dict:
		"""Retry a failed extraction run."""
		run = session.get(ExtractionRun, run_id)
		if not run:
			raise HTTPException(status_code=404, detail="Run not found")
		
		if run.status != RunStatus.FAILED.value:
			raise HTTPException(
				status_code=400,
				detail=f"Can only retry failed runs. Current status: {run.status}"
			)
		
		# Get paper info for queue item
		paper = session.get(Paper, run.paper_id)
		if not paper:
			raise HTTPException(status_code=404, detail="Paper not found")
		
		# Reset status to queued
		run.status = RunStatus.QUEUED.value
		run.failure_reason = None
		session.add(run)
		session.commit()
		session.refresh(run)
		
		# Add to queue
		queue = get_queue()
		await queue.enqueue(QueueItem(
			run_id=run.id,
			paper_id=paper.id,
			pdf_url=run.pdf_url,
			title=paper.title,
			provider=run.model_provider or settings.LLM_PROVIDER,
			force=True,
		))
		
		return {
			"id": run.id,
			"status": run.status,
			"message": "Run re-queued for processing",
		}

	@app.post("/api/papers/{paper_id}/force-reextract")
	async def force_reextract(
		paper_id: int,
		provider: Optional[str] = None,
		session: Session = Depends(get_session),
	) -> dict:
		"""Force re-extraction of a paper by creating a new run."""
		paper = session.get(Paper, paper_id)
		if not paper:
			raise HTTPException(status_code=404, detail="Paper not found")
		
		# Get the latest run to copy pdf_url
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
				detail="No PDF URL available for this paper"
			)
		
		# Use specified provider or fallback to latest run's provider or default
		use_provider = provider or (latest_run.model_provider if latest_run else None) or settings.LLM_PROVIDER
		
		# Create a new run
		new_run = ExtractionRun(
			paper_id=paper.id,
			status=RunStatus.QUEUED.value,
			model_provider=use_provider,
			pdf_url=pdf_url,
		)
		session.add(new_run)
		session.commit()
		session.refresh(new_run)
		
		# Add to queue
		queue = get_queue()
		await queue.enqueue(QueueItem(
			run_id=new_run.id,
			paper_id=paper.id,
			pdf_url=pdf_url,
			title=paper.title,
			provider=use_provider,
			force=True,
		))
		
		return {
			"id": new_run.id,
			"paper_id": paper.id,
			"status": new_run.status,
			"message": "New extraction run created and queued",
		}

	return app


app = create_app()


