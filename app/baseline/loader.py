from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional


BASELINE_DIR = Path(__file__).resolve().parent / "data"


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
