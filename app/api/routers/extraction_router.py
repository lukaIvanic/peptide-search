from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from ...config import settings
from ...db import get_session
from ...persistence.models import ExtractionRun, RunStatus
from ...persistence.repository import PaperRepository
from ...schemas import ExtractRequest, ExtractResponse, PaperMeta, UploadEnqueueResponse
from ...services.queue_coordinator import QueueCoordinator
from ...services.extraction_service import run_extraction
from ...services.upload_store import store_upload

router = APIRouter(tags=["extraction"])


@router.post("/api/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest, session: Session = Depends(get_session)) -> ExtractResponse:
    if not (req.text or req.pdf_url):
        raise HTTPException(status_code=400, detail="Provide either 'text' or 'pdf_url'.")

    try:
        extraction_id, paper_id, payload = await run_extraction(session, req)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ExtractResponse(extraction=payload, extraction_id=extraction_id, paper_id=paper_id)


@router.post("/api/extract-file", response_model=UploadEnqueueResponse)
async def extract_file(
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
    title: Optional[str] = Form(None),
    prompt_id: Optional[int] = Form(None),
    session: Session = Depends(get_session),
) -> UploadEnqueueResponse:
    upload_files = files or ([file] if file else [])
    if not upload_files:
        raise HTTPException(status_code=400, detail="No files provided")

    file_payloads: List[tuple[bytes, str]] = []
    total_size = 0
    for upload in upload_files:
        if not upload or not upload.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        if not upload.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")
        content = await upload.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Empty file")
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File too large (max 20MB)")
        total_size += len(content)
        if total_size > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Total upload too large (max 50MB)")
        file_payloads.append((content, upload.filename))

    upload_urls = [store_upload(content, filename) for content, filename in file_payloads]
    normalized_upload_urls: List[str] = []
    for raw_url in upload_urls:
        canonical_url = QueueCoordinator.canonicalize_source_url(raw_url)
        if canonical_url:
            normalized_upload_urls.append(canonical_url)
    if not normalized_upload_urls:
        raise HTTPException(status_code=400, detail="Unable to resolve upload source URLs")

    first_filename = file_payloads[0][1]
    if title:
        resolved_title = title
    elif len(file_payloads) == 1:
        resolved_title = first_filename.rsplit(".", 1)[0]
    else:
        base_title = first_filename.rsplit(".", 1)[0]
        resolved_title = f"{base_title} (+{len(file_payloads) - 1} more)"
    meta = PaperMeta(
        title=resolved_title,
        source="upload",
    )
    paper_repo = PaperRepository(session)
    paper_id = paper_repo.upsert(meta)
    if not paper_id:
        raise HTTPException(status_code=400, detail="Unable to create paper record for upload")

    use_provider = settings.LLM_PROVIDER
    run = ExtractionRun(
        paper_id=paper_id,
        status=RunStatus.QUEUED.value,
        model_provider=use_provider,
        pdf_url=normalized_upload_urls[0],
        prompt_id=prompt_id,
    )
    result = QueueCoordinator().enqueue_new_run(
        session,
        run=run,
        title=meta.title or "(Untitled)",
        pdf_urls=normalized_upload_urls,
    )
    if not result.enqueued:
        raise HTTPException(status_code=409, detail="Uploaded source is already queued")

    return UploadEnqueueResponse(
        run_id=result.run_id,
        paper_id=paper_id,
        status=result.run_status,
        message="Upload accepted and queued for processing",
    )
