"""Extraction service - coordinates document input, LLM calls, and persistence."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple, Union, AsyncGenerator, List

from sqlmodel import Session

from ..config import settings
from ..db import session_scope
from ..prompts import build_system_prompt, build_user_prompt, build_followup_prompt
from ..schemas import ExtractRequest, ExtractionPayload, PaperMeta
from ..persistence.models import Paper, ExtractionRun, ExtractionEntity, RunStatus

from ..integrations.llm import (
    DocumentInput,
    InputType,
    OpenAIProvider,
    DeepSeekProvider,
    MockProvider,
)
from ..integrations.document import DocumentExtractor, fetch_and_extract_text
from ..persistence.repository import PaperRepository, ExtractionRepository, PromptRepository
from .upload_store import is_upload_url, pop_upload

logger = logging.getLogger(__name__)

# Maximum characters of text to send to LLM
MAX_TEXT_LENGTH = 18000


def _resolve_system_prompt(
    session: Session,
    prompt_id: Optional[int] = None,
    prompt_version_id: Optional[int] = None,
) -> Tuple[str, Optional[int], Optional[int], Optional[str], Optional[int]]:
    repo = PromptRepository(session)
    prompt, version = repo.resolve_prompt(
        build_system_prompt(),
        prompt_id=prompt_id,
        prompt_version_id=prompt_version_id,
    )
    system_prompt = build_system_prompt(version.content)
    return (
        system_prompt,
        prompt.id if prompt else None,
        version.id if version else None,
        prompt.name if prompt else None,
        version.version_index if version else None,
    )


def _extract_usage(
    provider: Union[OpenAIProvider, DeepSeekProvider, MockProvider],
) -> Dict[str, Optional[int]]:
    usage = provider.get_last_usage()
    if not usage:
        return {
            "input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "total_tokens": None,
        }
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": usage.get("reasoning_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def _apply_usage_to_run(run: ExtractionRun, usage: Optional[Dict[str, Optional[int]]]) -> None:
    if not usage:
        return
    if usage.get("input_tokens") is not None:
        run.input_tokens = usage.get("input_tokens")
    if usage.get("output_tokens") is not None:
        run.output_tokens = usage.get("output_tokens")
    if usage.get("reasoning_tokens") is not None:
        run.reasoning_tokens = usage.get("reasoning_tokens")
    if usage.get("total_tokens") is not None:
        run.total_tokens = usage.get("total_tokens")


def _persist_failed_run(
    session: Session,
    paper_id: Optional[int],
    provider_name: str,
    model_name: Optional[str],
    prompts_json: Optional[str],
    raw_json_text: str,
    failure_reason: str,
    pdf_url: Optional[str] = None,
    parent_run_id: Optional[int] = None,
    prompt_id: Optional[int] = None,
    prompt_version_id: Optional[int] = None,
    baseline_case_id: Optional[str] = None,
    baseline_dataset: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    reasoning_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
) -> int:
    run = ExtractionRun(
        paper_id=paper_id,
        raw_json=raw_json_text,
        comment=None,
        model_provider=provider_name,
        model_name=model_name,
        source_text_hash=None,
        prompt_version=ExtractionRepository.PROMPT_VERSION,
        prompts_json=prompts_json,
        pdf_url=pdf_url,
        parent_run_id=parent_run_id,
        status=RunStatus.FAILED.value,
        failure_reason=failure_reason,
        prompt_id=prompt_id,
        prompt_version_id=prompt_version_id,
        baseline_case_id=baseline_case_id,
        baseline_dataset=baseline_dataset,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run.id


def _build_provider(name: str) -> Union[OpenAIProvider, DeepSeekProvider, MockProvider]:
    key = name.lower().strip()
    if key in {"openai", "openai-full"}:
        return OpenAIProvider(provider_name="openai", model=settings.OPENAI_MODEL)
    if key == "openai-mini":
        return OpenAIProvider(provider_name="openai-mini", model=settings.OPENAI_MODEL_MINI)
    if key == "openai-nano":
        return OpenAIProvider(provider_name="openai-nano", model=settings.OPENAI_MODEL_NANO)
    if key == "deepseek":
        return DeepSeekProvider()
    if key == "mock":
        return MockProvider()
    raise RuntimeError(
        f"Unknown LLM provider '{name}'. Expected one of: "
        "openai, openai-full, openai-mini, openai-nano, deepseek, mock."
    )


def get_provider() -> Union[OpenAIProvider, DeepSeekProvider, MockProvider]:
    """Get the configured LLM provider."""
    if not settings.LLM_PROVIDER:
        raise RuntimeError(
            "LLM_PROVIDER is not set. Set it to one of: "
            "openai, openai-full, openai-mini, openai-nano, deepseek, mock."
        )
    return _build_provider(settings.LLM_PROVIDER)


def get_provider_by_name(name: Optional[str]) -> Union[OpenAIProvider, DeepSeekProvider, MockProvider]:
    """Get an LLM provider by explicit name, or use the configured provider."""
    if name is None:
        return get_provider()
    if not str(name).strip():
        raise RuntimeError("Provider name cannot be empty.")
    return _build_provider(str(name))


def _should_force_text_extraction(url: Optional[str]) -> bool:
    if not url:
        return False
    if not DocumentExtractor.looks_like_pdf_url(url):
        return True
    lowered = url.lower()
    if "europepmc.org/backend/ptpmcrender.fcgi" in lowered:
        return True
    if "europepmc.org/articles" in lowered and "pdf" in lowered:
        return True
    return False


def _build_metadata_hint(meta: PaperMeta) -> str:
    """Build a metadata hint string for the prompt."""
    parts = []
    if meta.title:
        parts.append(f"Title: {meta.title}")
    if meta.doi:
        parts.append(f"DOI: {meta.doi}")
    if meta.url:
        parts.append(f"URL: {meta.url}")
    if meta.source:
        parts.append(f"Source: {meta.source}")
    if meta.year:
        parts.append(f"Year: {meta.year}")
    if meta.authors:
        parts.append(f"Authors: {', '.join(meta.authors)}")
    return "\n".join(parts)


async def _resolve_document_input(
    req: ExtractRequest,
    provider: Union[OpenAIProvider, DeepSeekProvider, MockProvider],
) -> Tuple[DocumentInput, Optional[str]]:
    """
    Resolve the request into a DocumentInput for the provider.
    
    Returns (document_input, source_text_for_hash).
    Source text is only populated when we extract text ourselves.
    """
    meta_hint = _build_metadata_hint(PaperMeta(
        title=req.title,
        doi=req.doi,
        url=req.url or req.pdf_url,
        source=req.source,
        year=req.year,
        authors=req.authors or [],
    ))
    
    capabilities = provider.capabilities()
    
    # Case 1: Direct text provided
    if req.text:
        return DocumentInput.from_text(req.text[:MAX_TEXT_LENGTH], meta_hint), req.text
    
    # Case 2: PDF URL provided
    if req.pdf_url:
        looks_like_pdf = DocumentExtractor.looks_like_pdf_url(req.pdf_url)
        
        # If URL points to a PDF, require direct PDF handling (no text parsing fallback).
        if looks_like_pdf:
            if not capabilities.supports_pdf_url:
                raise RuntimeError(
                    f"The current LLM provider ({provider.name()}) does not support direct PDF URLs. "
                    "No text extraction fallback is enabled."
                )
            if _should_force_text_extraction(req.pdf_url):
                raise RuntimeError(
                    "This PDF URL requires manual text extraction, which is disabled. "
                    "Please provide a direct PDF URL that the provider can process."
                )
            return DocumentInput.from_url(req.pdf_url, meta_hint), None

        # Non-PDF URLs can still be fetched and parsed as text.
        text = await fetch_and_extract_text(req.pdf_url)
        if not text or not text.strip():
            raise RuntimeError(
                "No textual content could be extracted from the provided source. "
                "Please ensure the URL is a readable PDF or HTML article."
            )
        return DocumentInput.from_text(text[:MAX_TEXT_LENGTH], meta_hint), text
    
    raise ValueError("Either 'text' or 'pdf_url' must be provided")


async def run_extraction(
    session: Session,
    req: ExtractRequest,
    provider_name: Optional[str] = None,
    baseline_case_id: Optional[str] = None,
    baseline_dataset: Optional[str] = None,
    parent_run_id: Optional[int] = None,
) -> Tuple[int, Optional[int], ExtractionPayload]:
    """
    Run extraction from a request.
    
    Returns (extraction_id, paper_id, payload).
    """
    provider = get_provider_by_name(provider_name)
    (
        system_prompt,
        resolved_prompt_id,
        resolved_prompt_version_id,
        resolved_prompt_name,
        resolved_prompt_version_index,
    ) = _resolve_system_prompt(session, prompt_id=req.prompt_id)
    
    # Build metadata
    meta = PaperMeta(
        title=req.title,
        doi=req.doi,
        url=req.url or req.pdf_url,
        source=req.source,
        year=req.year,
        authors=req.authors or [],
    )
    
    # Resolve document input
    try:
        document, source_text = await _resolve_document_input(req, provider)
    except Exception as exc:
        paper_repo = PaperRepository(session)
        paper_id = paper_repo.upsert(meta)
        prompts_json = json.dumps({
            "system_prompt": system_prompt,
            "user_prompt": None,
            "prompt_id": resolved_prompt_id,
            "prompt_version_id": resolved_prompt_version_id,
            "prompt_name": resolved_prompt_name,
            "prompt_version_index": resolved_prompt_version_index,
        })
        _persist_failed_run(
            session=session,
            paper_id=paper_id,
            provider_name=provider.name(),
            model_name=provider.model_name(),
            prompts_json=prompts_json,
            raw_json_text=json.dumps({"error": str(exc)}),
            failure_reason=str(exc),
            pdf_url=req.pdf_url or req.url,
            prompt_id=resolved_prompt_id,
            prompt_version_id=resolved_prompt_version_id,
            parent_run_id=parent_run_id,
            baseline_case_id=baseline_case_id,
            baseline_dataset=baseline_dataset,
        )
        raise
    
    # Build prompt based on input type
    if document.input_type == InputType.URL or document.input_type == InputType.FILE:
        user_prompt = build_user_prompt(
            document.metadata_hint,
            "[PDF document attached - analyze the full document]"
        )
    else:
        user_prompt = build_user_prompt(document.metadata_hint, document.text or "")
    
    prompts_json = json.dumps({
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "prompt_id": resolved_prompt_id,
        "prompt_version_id": resolved_prompt_version_id,
        "prompt_name": resolved_prompt_name,
        "prompt_version_index": resolved_prompt_version_index,
    })

    # Call LLM with fallback
    try:
        raw_json_text = await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            document=document if document.input_type != InputType.TEXT else None,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )
    except RuntimeError as e:
        error_msg = str(e)
        paper_repo = PaperRepository(session)
        paper_id = paper_repo.upsert(meta)
        usage = _extract_usage(provider)
        _persist_failed_run(
            session=session,
            paper_id=paper_id,
            provider_name=provider.name(),
            model_name=provider.model_name(),
            prompts_json=prompts_json,
            raw_json_text=json.dumps({"error": error_msg}),
            failure_reason=f"Provider error: {error_msg}",
            pdf_url=req.pdf_url or req.url,
            prompt_id=resolved_prompt_id,
            prompt_version_id=resolved_prompt_version_id,
            parent_run_id=parent_run_id,
            baseline_case_id=baseline_case_id,
            baseline_dataset=baseline_dataset,
            **usage,
        )
        raise

    usage = _extract_usage(provider)

    # Parse and validate
    paper_repo = PaperRepository(session)
    extraction_repo = ExtractionRepository(session)
    try:
        data = json.loads(raw_json_text)
        payload = ExtractionPayload.model_validate(data)
    except Exception as exc:
        paper_id = paper_repo.upsert(meta)
        _persist_failed_run(
            session=session,
            paper_id=paper_id,
            provider_name=provider.name(),
            model_name=provider.model_name(),
            prompts_json=prompts_json,
            raw_json_text=raw_json_text,
            failure_reason=f"Parse/validation error: {exc}",
            pdf_url=req.pdf_url or req.url,
            prompt_id=resolved_prompt_id,
            prompt_version_id=resolved_prompt_version_id,
            parent_run_id=parent_run_id,
            baseline_case_id=baseline_case_id,
            baseline_dataset=baseline_dataset,
            **usage,
        )
        raise RuntimeError(f"Failed to parse model output: {exc}") from exc
    
    # Fill missing metadata from request
    if not payload.paper.title and meta.title:
        payload.paper.title = meta.title
    if not payload.paper.doi and meta.doi:
        payload.paper.doi = meta.doi
    if not payload.paper.url and meta.url:
        payload.paper.url = meta.url
    if not payload.paper.source and meta.source:
        payload.paper.source = meta.source
    if not payload.paper.year and meta.year:
        payload.paper.year = meta.year
    if not payload.paper.authors and meta.authors:
        payload.paper.authors = meta.authors
    
    # Persist using repositories
    paper_id = paper_repo.upsert(payload.paper)
    
    run_id, _entity_ids = extraction_repo.save_extraction(
        payload=payload,
        paper_id=paper_id,
        provider_name=provider.name(),
        model_name=provider.model_name(),
        source_text=source_text,
        prompts_json=prompts_json,
        pdf_url=req.pdf_url or req.url,
        prompt_id=resolved_prompt_id,
        prompt_version_id=resolved_prompt_version_id,
        status=RunStatus.STORED.value,
        baseline_case_id=baseline_case_id,
        baseline_dataset=baseline_dataset,
        parent_run_id=parent_run_id,
        **usage,
    )
    
    # NOTE: We intentionally do not write to the legacy `extraction` table anymore.
    # Old data may still exist there; API endpoints will fall back when needed.
    return run_id, paper_id, payload


async def run_extraction_from_file(
    session: Session,
    file_content: bytes,
    filename: str,
    title: Optional[str] = None,
    prompt_id: Optional[int] = None,
    provider_name: Optional[str] = None,
    baseline_case_id: Optional[str] = None,
    baseline_dataset: Optional[str] = None,
    parent_run_id: Optional[int] = None,
) -> Tuple[int, Optional[int], ExtractionPayload]:
    """
    Run extraction on an uploaded PDF file.
    
    Returns (extraction_id, paper_id, payload).
    """
    return await run_extraction_from_files(
        session=session,
        files=[(file_content, filename)],
        title=title,
        prompt_id=prompt_id,
        provider_name=provider_name,
        baseline_case_id=baseline_case_id,
        baseline_dataset=baseline_dataset,
        parent_run_id=parent_run_id,
    )


async def run_extraction_from_files(
    session: Session,
    files: List[Tuple[bytes, str]],
    title: Optional[str] = None,
    prompt_id: Optional[int] = None,
    provider_name: Optional[str] = None,
    baseline_case_id: Optional[str] = None,
    baseline_dataset: Optional[str] = None,
    parent_run_id: Optional[int] = None,
) -> Tuple[int, Optional[int], ExtractionPayload]:
    """
    Run extraction on uploaded PDF files.
    
    Returns (extraction_id, paper_id, payload).
    """
    if not files:
        raise ValueError("No files provided")

    provider = get_provider_by_name(provider_name)
    capabilities = provider.capabilities()
    
    (
        system_prompt,
        resolved_prompt_id,
        resolved_prompt_version_id,
        resolved_prompt_name,
        resolved_prompt_version_index,
    ) = _resolve_system_prompt(session, prompt_id=prompt_id)

    first_filename = files[0][1]
    if title:
        resolved_title = title
    elif len(files) == 1:
        resolved_title = first_filename.rsplit(".", 1)[0]
    else:
        base_title = first_filename.rsplit(".", 1)[0]
        resolved_title = f"{base_title} (+{len(files) - 1} more)"

    meta = PaperMeta(
        title=resolved_title,
        source="upload",
    )
    meta_hint = _build_metadata_hint(meta)
    
    if len(files) > 1:
        user_prompt = build_user_prompt(meta_hint, "[PDF documents attached - analyze the full document set]")
    else:
        user_prompt = build_user_prompt(meta_hint, "[PDF document attached - analyze the full document]")
    
    prompts_json = json.dumps({
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "prompt_id": resolved_prompt_id,
        "prompt_version_id": resolved_prompt_version_id,
        "prompt_name": resolved_prompt_name,
        "prompt_version_index": resolved_prompt_version_index,
    })
    
    # Check provider supports file uploads
    if not capabilities.supports_pdf_file:
        error_msg = (
            f"The current LLM provider ({provider.name()}) does not support direct PDF file uploads. "
            "No text extraction fallback is enabled."
        )
        paper_repo = PaperRepository(session)
        paper_id = paper_repo.upsert(meta)
        _persist_failed_run(
            session=session,
            paper_id=paper_id,
            provider_name=provider.name(),
            model_name=provider.model_name(),
            prompts_json=prompts_json,
            raw_json_text=json.dumps({"error": error_msg}),
            failure_reason=error_msg,
            pdf_url=None,
            prompt_id=resolved_prompt_id,
            prompt_version_id=resolved_prompt_version_id,
            parent_run_id=parent_run_id,
            baseline_case_id=baseline_case_id,
            baseline_dataset=baseline_dataset,
        )
        raise RuntimeError(error_msg)

    if len(files) == 1:
        file_content, filename = files[0]
        document = DocumentInput.from_file(file_content, filename, meta_hint)
    else:
        document = DocumentInput.from_files(files, meta_hint)

    raw_json_text = None
    try:
        raw_json_text = await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            document=document,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )
    except Exception as exc:
        error_msg = str(exc)
        paper_repo = PaperRepository(session)
        paper_id = paper_repo.upsert(meta)
        usage = _extract_usage(provider)
        _persist_failed_run(
            session=session,
            paper_id=paper_id,
            provider_name=provider.name(),
            model_name=provider.model_name(),
            prompts_json=prompts_json,
            raw_json_text=json.dumps({"error": error_msg}),
            failure_reason=f"Provider error: {error_msg}",
            pdf_url=None,
            prompt_id=resolved_prompt_id,
            prompt_version_id=resolved_prompt_version_id,
            parent_run_id=parent_run_id,
            baseline_case_id=baseline_case_id,
            baseline_dataset=baseline_dataset,
            **usage,
        )
        raise

    usage = _extract_usage(provider)
    
    paper_repo = PaperRepository(session)
    extraction_repo = ExtractionRepository(session)
    # Parse and validate
    try:
        data = json.loads(raw_json_text)
        payload = ExtractionPayload.model_validate(data)
    except Exception as exc:
        paper_id = paper_repo.upsert(meta)
        _persist_failed_run(
            session=session,
            paper_id=paper_id,
            provider_name=provider.name(),
            model_name=provider.model_name(),
            prompts_json=prompts_json,
            raw_json_text=raw_json_text,
            failure_reason=f"Parse/validation error: {exc}",
            pdf_url=None,
            prompt_id=resolved_prompt_id,
            prompt_version_id=resolved_prompt_version_id,
            parent_run_id=parent_run_id,
            baseline_case_id=baseline_case_id,
            baseline_dataset=baseline_dataset,
            **usage,
        )
        raise RuntimeError(f"Failed to parse model output: {exc}") from exc
    
    # Fill missing metadata
    if not payload.paper.title and meta.title:
        payload.paper.title = meta.title
    if not payload.paper.source:
        payload.paper.source = "upload"
    
    # Persist
    paper_id = paper_repo.upsert(payload.paper)
    
    run_id, _entity_ids = extraction_repo.save_extraction(
        payload=payload,
        paper_id=paper_id,
        provider_name=provider.name(),
        model_name=provider.model_name(),
        source_text=None,
        prompts_json=prompts_json,
        status=RunStatus.STORED.value,
        prompt_id=resolved_prompt_id,
        prompt_version_id=resolved_prompt_version_id,
        baseline_case_id=baseline_case_id,
        baseline_dataset=baseline_dataset,
        parent_run_id=parent_run_id,
        **usage,
    )
    
    return run_id, paper_id, payload


async def run_queued_extraction(
    run_id: int,
    paper_id: int,
    pdf_url: str,
    pdf_urls: Optional[List[str]] = None,
    provider: str = "openai",
    prompt_id: Optional[int] = None,
    prompt_version_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run extraction for a queued item.
    
    This is called by the queue worker. It updates the existing run record
    with the extraction results.
    
    Args:
        run_id: The ID of the ExtractionRun record (already created)
        paper_id: The ID of the Paper record
        pdf_url: URL to the PDF
        pdf_urls: Optional list of PDF URLs for a single run
        provider: Provider name (openai, mock)
        
    Returns:
        Dict with extraction result info
        
    Raises:
        Exception: If extraction fails
    """
    # Get provider instance
    llm_provider = get_provider_by_name(provider)
    
    (
        system_prompt,
        resolved_prompt_id,
        resolved_prompt_version_id,
        resolved_prompt_name,
        resolved_prompt_version_index,
    ) = (None, None, None, None, None)

    with session_scope() as session:
        run = session.get(ExtractionRun, run_id)
        if run:
            prompt_id = prompt_id or run.prompt_id
            prompt_version_id = prompt_version_id or run.prompt_version_id
        (
            system_prompt,
            resolved_prompt_id,
            resolved_prompt_version_id,
            resolved_prompt_name,
            resolved_prompt_version_index,
        ) = _resolve_system_prompt(
            session,
            prompt_id=prompt_id,
            prompt_version_id=prompt_version_id,
        )
        if run:
            run.prompt_id = resolved_prompt_id
            run.prompt_version_id = resolved_prompt_version_id
            session.add(run)
    
    # Build document input - handle uploads and URLs
    capabilities = llm_provider.capabilities()
    pdf_url_list = [url for url in (pdf_urls or []) if url]
    if not pdf_url_list and pdf_url:
        pdf_url_list = [pdf_url]
    if not pdf_url_list:
        raise RuntimeError("No PDF URL provided for extraction")

    if len(pdf_url_list) > 1:
        if any(not is_upload_url(url) for url in pdf_url_list):
            raise RuntimeError("Multiple PDF files are only supported for uploaded files.")
        uploads: List[Tuple[bytes, str]] = []
        for upload_url in pdf_url_list:
            upload = pop_upload(upload_url)
            if not upload:
                raise RuntimeError("Uploaded file not found or expired. Please upload again.")
            uploads.append(upload)
        if not capabilities.supports_pdf_file:
            raise RuntimeError(
                f"The current LLM provider ({llm_provider.name()}) does not support direct PDF file uploads. "
                "No text extraction fallback is enabled."
            )
        document = DocumentInput.from_files(uploads, "")
        user_prompt = build_user_prompt("", "[PDF documents attached - analyze the full document set]")
    else:
        pdf_url = pdf_url_list[0]
        is_upload = is_upload_url(pdf_url)
        file_content = None
        filename = None
        
        looks_like_pdf = DocumentExtractor.looks_like_pdf_url(pdf_url)

        if is_upload:
            upload = pop_upload(pdf_url)
            if not upload:
                raise RuntimeError("Uploaded file not found or expired. Please upload again.")
            file_content, filename = upload
            if not capabilities.supports_pdf_file:
                raise RuntimeError(
                    f"The current LLM provider ({llm_provider.name()}) does not support direct PDF file uploads. "
                    "No text extraction fallback is enabled."
                )
            document = DocumentInput.from_file(file_content, filename, "")
            user_prompt = build_user_prompt("", "[PDF document attached - analyze the full document]")
        elif looks_like_pdf:
            if not capabilities.supports_pdf_url:
                raise RuntimeError(
                    f"The current LLM provider ({llm_provider.name()}) does not support direct PDF URLs. "
                    "No text extraction fallback is enabled."
                )
            if _should_force_text_extraction(pdf_url):
                raise RuntimeError(
                    "This PDF URL requires manual text extraction, which is disabled. "
                    "Please provide a direct PDF URL that the provider can process."
                )
            document = DocumentInput.from_url(pdf_url, "")
            user_prompt = build_user_prompt("", "[PDF document attached - analyze the full document]")
        else:
            # Non-PDF URLs can be fetched and parsed as text.
            text = await fetch_and_extract_text(pdf_url)
            if not text or not text.strip():
                raise RuntimeError(
                    "No textual content could be extracted from the provided source. "
                    "Please ensure the URL is a readable PDF or HTML article."
                )
            document = DocumentInput.from_text(text[:MAX_TEXT_LENGTH], "")
            user_prompt = build_user_prompt("", text[:MAX_TEXT_LENGTH])
    
    # Store prompts for traceability (final version used)
    prompts_json = json.dumps({
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "prompt_id": resolved_prompt_id,
        "prompt_version_id": resolved_prompt_version_id,
        "prompt_name": resolved_prompt_name,
        "prompt_version_index": resolved_prompt_version_index,
    })

    # Call LLM without text-extraction fallbacks for PDFs
    raw_json_text = None
    extraction_start_time = time.monotonic()
    try:
        raw_json_text = await llm_provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            document=document if document.input_type != InputType.TEXT else None,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )
    except Exception as exc:
        extraction_time_ms = int((time.monotonic() - extraction_start_time) * 1000)
        error_msg = str(exc)
        usage = _extract_usage(llm_provider)
        with session_scope() as session:
            run = session.get(ExtractionRun, run_id)
            if run:
                run.raw_json = json.dumps({"error": error_msg})
                run.prompts_json = prompts_json
                run.model_provider = llm_provider.name()
                run.model_name = llm_provider.model_name()
                run.prompt_id = resolved_prompt_id
                run.prompt_version_id = resolved_prompt_version_id
                run.status = RunStatus.FAILED.value
                run.failure_reason = f"Provider error: {error_msg}"
                run.extraction_time_ms = extraction_time_ms
                _apply_usage_to_run(run, usage)
                session.add(run)
                session.commit()
        raise

    extraction_time_ms = int((time.monotonic() - extraction_start_time) * 1000)

    usage = _extract_usage(llm_provider)
    
    # Parse and validate
    try:
        data = json.loads(raw_json_text)
        payload = ExtractionPayload.model_validate(data)
    except Exception as exc:
        with session_scope() as session:
            run = session.get(ExtractionRun, run_id)
            if run:
                run.raw_json = raw_json_text
                run.comment = None
                run.model_provider = llm_provider.name()
                run.model_name = llm_provider.model_name()
                run.prompts_json = prompts_json
                run.prompt_version = ExtractionRepository.PROMPT_VERSION
                run.prompt_id = resolved_prompt_id
                run.prompt_version_id = resolved_prompt_version_id
                run.status = RunStatus.FAILED.value
                run.failure_reason = f"Parse/validation error: {exc}"
                _apply_usage_to_run(run, usage)
                session.add(run)
                session.commit()
        raise RuntimeError(f"Failed to parse model output: {exc}") from exc
    
    # Update the run record with results
    with session_scope() as session:
        run = session.get(ExtractionRun, run_id)
        if not run:
            raise RuntimeError(f"Run {run_id} not found")
        
        # Update run with results
        run.raw_json = payload.model_dump_json()
        run.comment = payload.comment
        run.model_provider = llm_provider.name()
        run.model_name = llm_provider.model_name()
        run.prompts_json = prompts_json
        run.prompt_version = ExtractionRepository.PROMPT_VERSION
        run.prompt_id = resolved_prompt_id
        run.prompt_version_id = resolved_prompt_version_id
        run.extraction_time_ms = extraction_time_ms
        _apply_usage_to_run(run, usage)
        
        session.add(run)
        
        # Create entities
        extraction_repo = ExtractionRepository(session)
        for entity_index, entity_data in enumerate(payload.entities):
            entity = extraction_repo._entity_to_row(entity_data, run_id, entity_index)
            session.add(entity)
        
        # Note: session_scope will commit
    
    logger.info(f"Run {run_id} completed: {len(payload.entities)} entities extracted")
    
    return {
        "run_id": run_id,
        "paper_id": paper_id,
        "entity_count": len(payload.entities),
        "comment": payload.comment,
    }


async def run_followup(
    session: Session,
    parent_run_id: int,
    instruction: str,
    provider_name: Optional[str] = None,
) -> Tuple[int, Optional[int], ExtractionPayload]:
    """
    Run a follow-up extraction using prior run context.

    Returns (run_id, paper_id, payload).
    """
    parent_run = session.get(ExtractionRun, parent_run_id)
    if not parent_run:
        raise ValueError(f"Run {parent_run_id} not found")
    if not parent_run.raw_json:
        raise ValueError("Prior run has no raw_json to continue from")

    paper = session.get(Paper, parent_run.paper_id) if parent_run.paper_id else None
    try:
        parent_payload = json.loads(parent_run.raw_json)
    except Exception:
        parent_payload = {}

    # Provider selection: request override > prior run provider > default
    resolved_provider = provider_name or parent_run.model_provider or settings.LLM_PROVIDER
    provider = get_provider_by_name(resolved_provider)

    (
        system_prompt,
        resolved_prompt_id,
        resolved_prompt_version_id,
        resolved_prompt_name,
        resolved_prompt_version_index,
    ) = _resolve_system_prompt(
        session,
        prompt_id=parent_run.prompt_id,
        prompt_version_id=parent_run.prompt_version_id,
    )

    # Build follow-up prompt using prior JSON + instruction + PDF URL (context only)
    user_prompt = build_followup_prompt(
        prior_json=parent_run.raw_json,
        instruction=instruction,
        pdf_url=parent_run.pdf_url or (paper.url if paper else None),
    )

    prompts_json = json.dumps({
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "prompt_id": resolved_prompt_id,
        "prompt_version_id": resolved_prompt_version_id,
        "prompt_name": resolved_prompt_name,
        "prompt_version_index": resolved_prompt_version_index,
    })

    try:
        raw_json_text = await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )
    except Exception as exc:
        usage = _extract_usage(provider)
        _persist_failed_run(
            session=session,
            paper_id=parent_run.paper_id,
            provider_name=provider.name(),
            model_name=provider.model_name(),
            prompts_json=prompts_json,
            raw_json_text=json.dumps({"error": str(exc)}),
            failure_reason=f"Provider error: {exc}",
            pdf_url=parent_run.pdf_url,
            parent_run_id=parent_run_id,
            prompt_id=resolved_prompt_id,
            prompt_version_id=resolved_prompt_version_id,
            **usage,
        )
        raise RuntimeError(f"Failed to run followup: {exc}") from exc

    usage = _extract_usage(provider)

    try:
        data = json.loads(raw_json_text)
        payload = ExtractionPayload.model_validate(data)
    except Exception as exc:
        _persist_failed_run(
            session=session,
            paper_id=parent_run.paper_id,
            provider_name=provider.name(),
            model_name=provider.model_name(),
            prompts_json=prompts_json,
            raw_json_text=raw_json_text,
            failure_reason=f"Parse/validation error: {exc}",
            pdf_url=parent_run.pdf_url,
            parent_run_id=parent_run_id,
            prompt_id=resolved_prompt_id,
            prompt_version_id=resolved_prompt_version_id,
            **usage,
        )
        raise RuntimeError(f"Failed to parse model output: {exc}") from exc

    # Force paper metadata from the parent run/paper to keep continuity
    parent_paper = parent_payload.get("paper") if isinstance(parent_payload, dict) else None
    if isinstance(parent_paper, dict):
        payload.paper.title = parent_paper.get("title") or payload.paper.title
        payload.paper.doi = parent_paper.get("doi") or payload.paper.doi
        payload.paper.url = parent_paper.get("url") or payload.paper.url
        payload.paper.source = parent_paper.get("source") or payload.paper.source
        payload.paper.year = parent_paper.get("year") or payload.paper.year
        parent_authors = parent_paper.get("authors")
        if isinstance(parent_authors, list):
            payload.paper.authors = parent_authors
    elif paper:
        payload.paper.title = paper.title
        payload.paper.doi = paper.doi
        payload.paper.url = paper.url
        payload.paper.source = paper.source
        payload.paper.year = paper.year
        if paper.authors_json:
            try:
                payload.paper.authors = json.loads(paper.authors_json)
            except Exception:
                pass

    extraction_repo = ExtractionRepository(session)
    run_id, _entity_ids = extraction_repo.save_extraction(
        payload=payload,
        paper_id=parent_run.paper_id,
        provider_name=provider.name(),
        model_name=provider.model_name(),
        prompts_json=prompts_json,
        pdf_url=parent_run.pdf_url,
        parent_run_id=parent_run_id,
        prompt_id=resolved_prompt_id,
        prompt_version_id=resolved_prompt_version_id,
        status=RunStatus.STORED.value,
        **usage,
    )

    return run_id, parent_run.paper_id, payload


async def run_followup_stream(
    session: Session,
    parent_run_id: int,
    instruction: str,
    provider_name: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream a follow-up extraction using prior run context.

    Yields dicts with shape: {"event": str, "data": dict}
    """
    yield {"event": "status", "data": {"message": "starting"}}

    parent_run = session.get(ExtractionRun, parent_run_id)
    if not parent_run:
        yield {"event": "error", "data": {"message": f"Run {parent_run_id} not found"}}
        return
    if not parent_run.raw_json:
        yield {"event": "error", "data": {"message": "Prior run has no raw_json to continue from"}}
        return

    paper = session.get(Paper, parent_run.paper_id) if parent_run.paper_id else None
    try:
        parent_payload = json.loads(parent_run.raw_json)
    except Exception:
        parent_payload = {}

    resolved_provider = provider_name or parent_run.model_provider or settings.LLM_PROVIDER
    provider = get_provider_by_name(resolved_provider)

    (
        system_prompt,
        resolved_prompt_id,
        resolved_prompt_version_id,
        resolved_prompt_name,
        resolved_prompt_version_index,
    ) = _resolve_system_prompt(
        session,
        prompt_id=parent_run.prompt_id,
        prompt_version_id=parent_run.prompt_version_id,
    )
    user_prompt = build_followup_prompt(
        prior_json=parent_run.raw_json,
        instruction=instruction,
        pdf_url=parent_run.pdf_url or (paper.url if paper else None),
    )

    prompts_json = json.dumps({
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "prompt_id": resolved_prompt_id,
        "prompt_version_id": resolved_prompt_version_id,
        "prompt_name": resolved_prompt_name,
        "prompt_version_index": resolved_prompt_version_index,
    })

    buffer = ""
    received_token = False
    try:
        if isinstance(provider, OpenAIProvider):
            yield {"event": "status", "data": {"message": "streaming"}}
            async for token in provider.generate_stream(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=settings.TEMPERATURE,
                max_tokens=settings.MAX_TOKENS,
            ):
                received_token = True
                buffer += token
                yield {"event": "token", "data": {"token": token}}
                await asyncio.sleep(0)
            if not received_token:
                buffer = await provider.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=settings.TEMPERATURE,
                    max_tokens=settings.MAX_TOKENS,
                )
                for i in range(0, len(buffer), 200):
                    yield {"event": "token", "data": {"token": buffer[i:i + 200]}}
                    await asyncio.sleep(0)
        else:
            yield {"event": "status", "data": {"message": "non_streaming"}}
            buffer = await provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=settings.TEMPERATURE,
                max_tokens=settings.MAX_TOKENS,
            )
            for i in range(0, len(buffer), 200):
                yield {"event": "token", "data": {"token": buffer[i:i + 200]}}
                await asyncio.sleep(0)
    except Exception as exc:
        usage = _extract_usage(provider)
        _persist_failed_run(
            session=session,
            paper_id=parent_run.paper_id,
            provider_name=provider.name(),
            model_name=provider.model_name(),
            prompts_json=prompts_json,
            raw_json_text=json.dumps({"error": str(exc)}),
            failure_reason=f"Provider error: {exc}",
            pdf_url=parent_run.pdf_url,
            parent_run_id=parent_run_id,
            prompt_id=resolved_prompt_id,
            prompt_version_id=resolved_prompt_version_id,
            **usage,
        )
        yield {"event": "error", "data": {"message": str(exc)}}
        return

    usage = _extract_usage(provider)

    try:
        data = json.loads(buffer)
        payload = ExtractionPayload.model_validate(data)
    except Exception as exc:
        _persist_failed_run(
            session=session,
            paper_id=parent_run.paper_id,
            provider_name=provider.name(),
            model_name=provider.model_name(),
            prompts_json=prompts_json,
            raw_json_text=buffer,
            failure_reason=f"Parse/validation error: {exc}",
            pdf_url=parent_run.pdf_url,
            parent_run_id=parent_run_id,
            prompt_id=resolved_prompt_id,
            prompt_version_id=resolved_prompt_version_id,
            **usage,
        )
        yield {"event": "error", "data": {"message": f"Invalid JSON: {exc}"}}
        return

    parent_paper = parent_payload.get("paper") if isinstance(parent_payload, dict) else None
    if isinstance(parent_paper, dict):
        payload.paper.title = parent_paper.get("title") or payload.paper.title
        payload.paper.doi = parent_paper.get("doi") or payload.paper.doi
        payload.paper.url = parent_paper.get("url") or payload.paper.url
        payload.paper.source = parent_paper.get("source") or payload.paper.source
        payload.paper.year = parent_paper.get("year") or payload.paper.year
        parent_authors = parent_paper.get("authors")
        if isinstance(parent_authors, list):
            payload.paper.authors = parent_authors
    elif paper:
        payload.paper.title = paper.title
        payload.paper.doi = paper.doi
        payload.paper.url = paper.url
        payload.paper.source = paper.source
        payload.paper.year = paper.year
        if paper.authors_json:
            try:
                payload.paper.authors = json.loads(paper.authors_json)
            except Exception:
                pass

    extraction_repo = ExtractionRepository(session)
    run_id, _entity_ids = extraction_repo.save_extraction(
        payload=payload,
        paper_id=parent_run.paper_id,
        provider_name=provider.name(),
        model_name=provider.model_name(),
        prompts_json=prompts_json,
        pdf_url=parent_run.pdf_url,
        parent_run_id=parent_run_id,
        prompt_id=resolved_prompt_id,
        prompt_version_id=resolved_prompt_version_id,
        status=RunStatus.STORED.value,
        **usage,
    )

    yield {
        "event": "done",
        "data": {
            "run_id": run_id,
            "paper_id": parent_run.paper_id,
            "payload": payload.model_dump(),
        },
    }


def run_edit(
    session: Session,
    parent_run_id: int,
    payload: ExtractionPayload,
    reason: Optional[str] = None,
) -> Tuple[int, Optional[int], ExtractionPayload]:
    """
    Save a manual edit as a new run version.
    """
    parent_run = session.get(ExtractionRun, parent_run_id)
    if not parent_run:
        raise ValueError(f"Run {parent_run_id} not found")

    paper = session.get(Paper, parent_run.paper_id) if parent_run.paper_id else None
    if paper:
        payload.paper.title = paper.title
        payload.paper.doi = paper.doi
        payload.paper.url = paper.url
        payload.paper.source = paper.source
        payload.paper.year = paper.year
        if paper.authors_json:
            try:
                payload.paper.authors = json.loads(paper.authors_json)
            except Exception:
                pass

    prompts_json = json.dumps({
        "edit_source": "manual",
        "edit_reason": reason,
    })

    extraction_repo = ExtractionRepository(session)
    run_id, _entity_ids = extraction_repo.save_extraction(
        payload=payload,
        paper_id=parent_run.paper_id,
        provider_name="manual",
        model_name="editor",
        prompts_json=prompts_json,
        pdf_url=parent_run.pdf_url,
        parent_run_id=parent_run_id,
        prompt_id=parent_run.prompt_id,
        prompt_version_id=parent_run.prompt_version_id,
        status=RunStatus.STORED.value,
    )

    return run_id, parent_run.paper_id, payload
