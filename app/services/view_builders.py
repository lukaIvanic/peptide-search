from __future__ import annotations

import json
from typing import List, Optional

from ..persistence.models import ExtractionRun, Paper
from ..schemas import PromptInfo


def parse_json_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def build_prompt_info(prompt, versions) -> PromptInfo:
    version_entries = []
    for version in versions:
        version_entries.append(
            {
                "id": version.id,
                "prompt_id": version.prompt_id,
                "version_index": version.version_index,
                "content": version.content,
                "notes": version.notes,
                "created_by": version.created_by,
                "created_at": version.created_at.isoformat() + "Z" if version.created_at else None,
            }
        )
    latest_version = version_entries[0] if version_entries else None
    return PromptInfo(
        id=prompt.id,
        name=prompt.name,
        description=prompt.description,
        is_active=prompt.is_active,
        created_at=prompt.created_at.isoformat() + "Z" if prompt.created_at else None,
        updated_at=prompt.updated_at.isoformat() + "Z" if prompt.updated_at else None,
        latest_version=latest_version,
        versions=version_entries,
    )


def build_run_payload(run: ExtractionRun, paper: Optional[Paper]) -> dict:
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
            "baseline_case_id": run.baseline_case_id,
            "baseline_dataset": run.baseline_dataset,
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
