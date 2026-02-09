from __future__ import annotations

from typing import List, Optional

from ..persistence.models import ExtractionRun, Paper
from ..schemas import PromptInfo
from .serializers import iso_z, parse_json_list as parse_json_list_value, parse_json_object


def parse_json_list(value: Optional[str]) -> List[str]:
    return [str(item) for item in parse_json_list_value(value)]


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
                "created_at": iso_z(version.created_at),
            }
        )
    latest_version = version_entries[0] if version_entries else None
    return PromptInfo(
        id=prompt.id,
        name=prompt.name,
        description=prompt.description,
        is_active=prompt.is_active,
        created_at=iso_z(prompt.created_at),
        updated_at=iso_z(prompt.updated_at),
        latest_version=latest_version,
        versions=version_entries,
    )


def build_run_payload(run: ExtractionRun, paper: Optional[Paper]) -> dict:
    authors = []
    if paper and paper.authors_json:
        parsed_authors = parse_json_list_value(paper.authors_json)
        authors = [str(item) for item in parsed_authors]

    prompts = parse_json_object(run.prompts_json) if run.prompts_json else None
    raw_json = parse_json_object(run.raw_json) if run.raw_json else None

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
            "created_at": iso_z(run.created_at),
        },
    }
