from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse


BASELINE_DIR = Path(__file__).resolve().parent / "data"
LOCAL_PDFS_PATH = BASELINE_DIR / "local_pdfs.json"
_LOCAL_PDFS_CACHE: Optional[Dict[str, Dict]] = None
_LOCAL_PDFS_MTIME: Optional[float] = None


def normalize_doi(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered.startswith("doi:"):
        text = text[4:].strip()
        lowered = text.lower()

    if lowered.startswith("http://") or lowered.startswith("https://"):
        parsed = urlparse(text)
        if "doi.org" in parsed.netloc:
            text = parsed.path.lstrip("/")
            lowered = text.lower()

    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/"):
        if lowered.startswith(prefix):
            text = text[len(prefix):].strip()
            lowered = text.lower()
            break

    return text.lower() if text else None


def load_local_pdf_mapping() -> Dict[str, Dict]:
    global _LOCAL_PDFS_CACHE, _LOCAL_PDFS_MTIME
    if not LOCAL_PDFS_PATH.exists():
        _LOCAL_PDFS_CACHE = {}
        _LOCAL_PDFS_MTIME = None
        return {}

    try:
        mtime = LOCAL_PDFS_PATH.stat().st_mtime
    except OSError:
        mtime = None

    if _LOCAL_PDFS_CACHE is not None and mtime is not None and _LOCAL_PDFS_MTIME == mtime:
        return _LOCAL_PDFS_CACHE

    raw_mapping = json.loads(LOCAL_PDFS_PATH.read_text(encoding="utf-8"))
    normalized: Dict[str, Dict] = {}
    for doi, entry in raw_mapping.items():
        normalized_doi = normalize_doi(doi)
        if not normalized_doi:
            continue
        if normalized_doi not in normalized:
            normalized[normalized_doi] = entry

    _LOCAL_PDFS_CACHE = normalized
    _LOCAL_PDFS_MTIME = mtime
    return normalized


def _resolve_single_pdf_path(raw_path: str) -> Optional[Path]:
    """Resolve a single PDF path from local_pdfs.json to an actual file path."""
    raw_path = str(raw_path).strip()
    if not raw_path:
        return None

    repo_root = BASELINE_DIR.parents[2]
    candidates: List[Path] = []

    def add_candidate(candidate: Path) -> None:
        if candidate not in candidates:
            candidates.append(candidate)

    path = Path(raw_path)
    if not path.is_absolute():
        add_candidate(repo_root / path)
    else:
        add_candidate(path)

    if "\\" in raw_path:
        normalized = raw_path.replace("\\", "/")
        path = Path(normalized)
        if not path.is_absolute():
            add_candidate(repo_root / path)
        else:
            add_candidate(path)

    if "/" in raw_path:
        normalized = raw_path.replace("/", "\\")
        path = Path(normalized)
        if not path.is_absolute():
            add_candidate(repo_root / path)
        else:
            add_candidate(path)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_local_pdf_path(doi: Optional[str]) -> Optional[Path]:
    """Resolve the main PDF path for a DOI."""
    normalized_doi = normalize_doi(doi)
    if not normalized_doi:
        return None
    mapping = load_local_pdf_mapping()
    entry = mapping.get(normalized_doi)
    if not entry:
        base_doi = re.sub(r"/v\d+$", "", normalized_doi)
        if base_doi != normalized_doi:
            entry = mapping.get(base_doi)
    if not entry:
        return None
    main_files = entry.get("main") or []
    if not main_files:
        return None
    return _resolve_single_pdf_path(main_files[0])


def resolve_all_local_pdf_paths(doi: Optional[str]) -> List[Path]:
    """Resolve all local PDF paths (main + supplementary) for a DOI.

    Returns a list of resolved paths, with main PDFs first, then supplementary.
    Only includes paths that actually exist on disk.
    """
    normalized_doi = normalize_doi(doi)
    if not normalized_doi:
        return []
    mapping = load_local_pdf_mapping()
    entry = mapping.get(normalized_doi)
    if not entry:
        base_doi = re.sub(r"/v\d+$", "", normalized_doi)
        if base_doi != normalized_doi:
            entry = mapping.get(base_doi)
    if not entry:
        return []

    resolved_paths: List[Path] = []

    # Add main PDFs first
    main_files = entry.get("main") or []
    for raw_path in main_files:
        resolved = _resolve_single_pdf_path(raw_path)
        if resolved and resolved not in resolved_paths:
            resolved_paths.append(resolved)

    # Add supplementary PDFs
    supplementary_files = entry.get("supplementary") or []
    for raw_path in supplementary_files:
        resolved = _resolve_single_pdf_path(raw_path)
        if resolved and resolved not in resolved_paths:
            resolved_paths.append(resolved)

    return resolved_paths


@lru_cache(maxsize=1)
def load_index() -> Dict:
    index_path = BASELINE_DIR / "index.json"
    if not index_path.exists():
        return {"schema_version": "v1", "datasets": [], "total_cases": 0}
    return json.loads(index_path.read_text(encoding="utf-8"))


def list_dataset_ids() -> List[str]:
    index = load_index()
    return [entry.get("id") for entry in index.get("datasets", []) if entry.get("id")]


@lru_cache(maxsize=32)
def load_dataset(dataset_id: str) -> List[Dict]:
    dataset_path = BASELINE_DIR / f"{dataset_id}.json"
    if not dataset_path.exists():
        return []
    return json.loads(dataset_path.read_text(encoding="utf-8"))


def list_cases(dataset: Optional[str] = None) -> List[Dict]:
    if dataset:
        return load_dataset(dataset)
    cases: List[Dict] = []
    for dataset_id in list_dataset_ids():
        cases.extend(load_dataset(dataset_id))
    return cases


def get_case(case_id: str) -> Optional[Dict]:
    for dataset_id in list_dataset_ids():
        for case in load_dataset(dataset_id):
            if case.get("id") == case_id:
                return case
    return None
