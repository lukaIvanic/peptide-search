"""Extraction service - coordinates document input, LLM calls, and persistence."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Tuple, Union, AsyncGenerator

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
from ..persistence.repository import PaperRepository, ExtractionRepository

logger = logging.getLogger(__name__)

# Maximum characters of text to send to LLM
MAX_TEXT_LENGTH = 18000


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
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run.id


def get_provider() -> Union[OpenAIProvider, DeepSeekProvider, MockProvider]:
    """Get the configured LLM provider."""
    if settings.LLM_PROVIDER == "openai":
        return OpenAIProvider()
    if settings.LLM_PROVIDER == "deepseek":
        return DeepSeekProvider()
    return MockProvider()


def _should_force_text_extraction(url: Optional[str]) -> bool:
    if not url:
        return False
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
        
        # If provider supports direct PDF URL processing, use it
        if capabilities.supports_pdf_url and looks_like_pdf and not _should_force_text_extraction(req.pdf_url):
            return DocumentInput.from_url(req.pdf_url, meta_hint), None
        
        # Otherwise, extract text first
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
) -> Tuple[int, Optional[int], ExtractionPayload]:
    """
    Run extraction from a request.
    
    Returns (extraction_id, paper_id, payload).
    """
    provider = get_provider()
    system_prompt = build_system_prompt()
    
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
    except RuntimeError as e:
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
        # If direct PDF processing failed, try text extraction fallback
        if document.input_type == InputType.URL and (
            "empty response" in error_msg.lower()
            or "couldn't be processed" in error_msg.lower()
            or "timeout while downloading" in error_msg.lower()
            or "error while downloading" in error_msg.lower()
        ):
            logger.warning(f"Direct PDF processing failed, trying text extraction: {error_msg}")
            try:
                text = await fetch_and_extract_text(req.pdf_url)
                if text and text.strip():
                    document = DocumentInput.from_text(text[:MAX_TEXT_LENGTH], document.metadata_hint)
                    source_text = text
                    user_prompt = build_user_prompt(document.metadata_hint, document.text or "")
                    prompts_json = json.dumps({
                        "system_prompt": system_prompt,
                        "user_prompt": user_prompt,
                    })
                    raw_json_text = await provider.generate(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=settings.TEMPERATURE,
                        max_tokens=settings.MAX_TOKENS,
                    )
                else:
                    raise RuntimeError(f"PDF processing failed and text extraction yielded no content. Original error: {error_msg}")
            except Exception as fallback_err:
                raise RuntimeError(f"PDF processing failed: {error_msg}. Fallback also failed: {fallback_err}")
        else:
            paper_repo = PaperRepository(session)
            paper_id = paper_repo.upsert(meta)
            _persist_failed_run(
                session=session,
                paper_id=paper_id,
                provider_name=provider.name(),
                model_name=provider.model_name(),
                prompts_json=prompts_json,
                raw_json_text=json.dumps({"error": error_msg}),
                failure_reason=f"Provider error: {error_msg}",
                pdf_url=req.pdf_url or req.url,
            )
            raise

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
        status=RunStatus.STORED.value,
    )
    
    # NOTE: We intentionally do not write to the legacy `extraction` table anymore.
    # Old data may still exist there; API endpoints will fall back when needed.
    return run_id, paper_id, payload


async def run_extraction_from_file(
    session: Session,
    file_content: bytes,
    filename: str,
    title: Optional[str] = None,
) -> Tuple[int, Optional[int], ExtractionPayload]:
    """
    Run extraction on an uploaded PDF file.
    
    Returns (extraction_id, paper_id, payload).
    """
    provider = get_provider()
    capabilities = provider.capabilities()
    
    # Check provider supports file uploads
    if not capabilities.supports_pdf_file:
        # Fall back to text extraction
        from ..integrations.document import pdf_bytes_to_text
        text = pdf_bytes_to_text(file_content)
        if not text or not text.strip():
            raise RuntimeError(
                f"The current LLM provider ({provider.name()}) does not support file uploads, "
                "and text extraction from the PDF failed. Please try a different provider."
            )
        # Create a request with extracted text
        req = ExtractRequest(
            text=text,
            title=title or filename.rsplit(".", 1)[0],
            source="upload",
        )
        return await run_extraction(session, req)
    
    # Provider supports file uploads
    system_prompt = build_system_prompt()
    
    meta = PaperMeta(
        title=title or filename.rsplit(".", 1)[0],
        source="upload",
    )
    meta_hint = _build_metadata_hint(meta)
    
    document = DocumentInput.from_file(file_content, filename, meta_hint)
    user_prompt = build_user_prompt(meta_hint, "[PDF document attached - analyze the full document]")
    
    prompts_json = json.dumps({
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    })
    
    try:
        raw_json_text = await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            document=document,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )
    except Exception as exc:
        paper_repo = PaperRepository(session)
        paper_id = paper_repo.upsert(meta)
        _persist_failed_run(
            session=session,
            paper_id=paper_id,
            provider_name=provider.name(),
            model_name=provider.model_name(),
            prompts_json=prompts_json,
            raw_json_text=json.dumps({"error": str(exc)}),
            failure_reason=f"Provider error: {exc}",
            pdf_url=None,
        )
        raise
    
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
    )
    
    return run_id, paper_id, payload


async def run_queued_extraction(
    run_id: int,
    paper_id: int,
    pdf_url: str,
    provider: str = "openai",
) -> Dict[str, Any]:
    """
    Run extraction for a queued item.
    
    This is called by the queue worker. It updates the existing run record
    with the extraction results.
    
    Args:
        run_id: The ID of the ExtractionRun record (already created)
        paper_id: The ID of the Paper record
        pdf_url: URL to the PDF
        provider: Provider name (openai, mock)
        
    Returns:
        Dict with extraction result info
        
    Raises:
        Exception: If extraction fails
    """
    # Get provider instance
    if provider == "openai":
        llm_provider = OpenAIProvider()
    elif provider == "deepseek":
        llm_provider = DeepSeekProvider()
    else:
        llm_provider = MockProvider()
    
    # Build prompts
    system_prompt = build_system_prompt()
    
    # Build document input - use PDF URL directly for OpenAI
    capabilities = llm_provider.capabilities()
    
    if capabilities.supports_pdf_url and not _should_force_text_extraction(pdf_url):
        document = DocumentInput.from_url(pdf_url, "")
        user_prompt = build_user_prompt("", "[PDF document attached - analyze the full document]")
    else:
        # Fall back to text extraction
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
    })

    # Call LLM with fallback for URL download errors
    raw_json_text = None
    try:
        raw_json_text = await llm_provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            document=document if document.input_type != InputType.TEXT else None,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )
    except Exception as exc:
        error_msg = str(exc)
        if capabilities.supports_pdf_url and (
            "timeout while downloading" in error_msg.lower()
            or "error while downloading" in error_msg.lower()
            or "couldn't be processed" in error_msg.lower()
            or "empty response" in error_msg.lower()
        ):
            logger.warning(f"Direct PDF processing failed, trying text extraction: {error_msg}")
            text = await fetch_and_extract_text(pdf_url)
            if not text or not text.strip():
                raise RuntimeError(
                    f"PDF processing failed and text extraction yielded no content. Original error: {error_msg}"
                )
            document = DocumentInput.from_text(text[:MAX_TEXT_LENGTH], "")
            user_prompt = build_user_prompt("", text[:MAX_TEXT_LENGTH])
            prompts_json = json.dumps({
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            })
            raw_json_text = await llm_provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=settings.TEMPERATURE,
                max_tokens=settings.MAX_TOKENS,
            )
        else:
            with session_scope() as session:
                run = session.get(ExtractionRun, run_id)
                if run:
                    run.raw_json = json.dumps({"error": error_msg})
                    run.prompts_json = prompts_json
                    run.model_provider = llm_provider.name()
                    run.model_name = llm_provider.model_name()
                    run.status = RunStatus.FAILED.value
                    run.failure_reason = f"Provider error: {error_msg}"
                    session.add(run)
                    session.commit()
            raise
    
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
                run.status = RunStatus.FAILED.value
                run.failure_reason = f"Parse/validation error: {exc}"
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
    if resolved_provider == "openai":
        provider = OpenAIProvider()
    elif resolved_provider == "deepseek":
        provider = DeepSeekProvider()
    else:
        provider = MockProvider()

    system_prompt = build_system_prompt()

    # Build follow-up prompt using prior JSON + instruction + PDF URL (context only)
    user_prompt = build_followup_prompt(
        prior_json=parent_run.raw_json,
        instruction=instruction,
        pdf_url=parent_run.pdf_url or (paper.url if paper else None),
    )

    prompts_json = json.dumps({
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    })

    try:
        raw_json_text = await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )
    except Exception as exc:
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
        )
        raise RuntimeError(f"Failed to run followup: {exc}") from exc

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
        status=RunStatus.STORED.value,
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
    if resolved_provider == "openai":
        provider = OpenAIProvider()
    elif resolved_provider == "deepseek":
        provider = DeepSeekProvider()
    else:
        provider = MockProvider()

    system_prompt = build_system_prompt()
    user_prompt = build_followup_prompt(
        prior_json=parent_run.raw_json,
        instruction=instruction,
        pdf_url=parent_run.pdf_url or (paper.url if paper else None),
    )

    prompts_json = json.dumps({
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
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
        )
        yield {"event": "error", "data": {"message": str(exc)}}
        return

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
        status=RunStatus.STORED.value,
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
        status=RunStatus.STORED.value,
    )

    return run_id, parent_run.paper_id, payload
