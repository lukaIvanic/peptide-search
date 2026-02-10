from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, delete
from sqlmodel import Session, select

from ..persistence.models import BaselineCase as BaselineCaseModel
from ..persistence.models import BaselineCaseRun, BaselineDataset, ExtractionRun, Paper
from ..services.serializers import iso_z
from ..time_utils import utc_now


class BaselineStoreError(Exception):
    pass


class BaselineConflictError(BaselineStoreError):
    pass


class BaselineNotFoundError(BaselineStoreError):
    pass


class BaselineValidationError(BaselineStoreError):
    pass


def _normalize_doi(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered.startswith("doi:"):
        text = text[4:].strip()
        lowered = text.lower()

    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
    ):
        if lowered.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text.lower() if text else None


def _normalize_url(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_json_text(value: Any, default: str) -> str:
    if value is None:
        return default
    return json.dumps(value, ensure_ascii=False)


def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


class BaselineStore:
    def __init__(self, session: Session):
        self.session = session

    def has_cases(self) -> bool:
        return self.session.exec(select(BaselineCaseModel.id).limit(1)).first() is not None

    def list_cases(self, dataset: Optional[str] = None) -> List[Dict[str, Any]]:
        stmt = select(BaselineCaseModel)
        if dataset:
            stmt = stmt.where(BaselineCaseModel.dataset_id == dataset)
        rows = self.session.exec(stmt.order_by(BaselineCaseModel.id.asc())).all()
        return [self._case_to_dict(row) for row in rows]

    def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        row = self.session.get(BaselineCaseModel, case_id)
        if not row:
            return None
        return self._case_to_dict(row)

    def list_datasets(self, dataset_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        stmt = select(BaselineDataset).order_by(BaselineDataset.id.asc())
        if dataset_filter:
            stmt = stmt.where(BaselineDataset.id == dataset_filter)
        rows = self.session.exec(stmt).all()

        counts = dict(
            self.session.exec(
                select(BaselineCaseModel.dataset_id, func.count(BaselineCaseModel.id))
                .group_by(BaselineCaseModel.dataset_id)
            ).all()
        )

        datasets = []
        for row in rows:
            datasets.append(
                {
                    "id": row.id,
                    "label": row.label,
                    "description": row.description,
                    "source_file": row.source_file,
                    "count": int(counts.get(row.id, 0)),
                    "original_count": row.original_count,
                }
            )

        if not datasets:
            stmt = select(BaselineCaseModel.dataset_id, func.count(BaselineCaseModel.id)).group_by(
                BaselineCaseModel.dataset_id
            )
            for dataset_id, count in self.session.exec(stmt).all():
                if dataset_filter and dataset_id != dataset_filter:
                    continue
                datasets.append(
                    {
                        "id": dataset_id,
                        "label": dataset_id,
                        "description": None,
                        "source_file": None,
                        "count": int(count),
                        "original_count": int(count),
                    }
                )
        return datasets

    def create_case(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        case_id = _normalize_str(payload.get("id"))
        dataset_id = _normalize_str(payload.get("dataset"))
        if not case_id:
            raise BaselineValidationError("Case id is required")
        if not dataset_id:
            raise BaselineValidationError("Dataset is required")
        if self.session.get(BaselineCaseModel, case_id):
            raise BaselineConflictError("Baseline case already exists")

        dataset = self.session.get(BaselineDataset, dataset_id)
        if not dataset:
            now = utc_now()
            dataset = BaselineDataset(
                id=dataset_id,
                label=dataset_id,
                description=None,
                source_file=None,
                original_count=0,
                created_at=now,
                updated_at=now,
            )
            self.session.add(dataset)

        row = BaselineCaseModel(
            id=case_id,
            dataset_id=dataset_id,
            sequence=_normalize_str(payload.get("sequence")),
            n_terminal=_normalize_str(payload.get("n_terminal")),
            c_terminal=_normalize_str(payload.get("c_terminal")),
            labels_json=self._validate_and_dump_labels(payload.get("labels")),
            doi=_normalize_doi(payload.get("doi")),
            pubmed_id=_normalize_str(payload.get("pubmed_id")),
            paper_url=_normalize_url(payload.get("paper_url")),
            pdf_url=_normalize_url(payload.get("pdf_url")),
            metadata_json=self._validate_and_dump_metadata(payload.get("metadata")),
            source_unverified=bool(payload.get("source_unverified", False)),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.session.add(row)
        dataset.updated_at = utc_now()
        self.session.add(dataset)
        self.session.commit()
        self.session.refresh(row)
        return self._case_to_dict(row)

    def update_case(
        self,
        case_id: str,
        payload: Dict[str, Any],
        expected_updated_at: Optional[str],
    ) -> Dict[str, Any]:
        row = self.session.get(BaselineCaseModel, case_id)
        if not row:
            raise BaselineNotFoundError("Baseline case not found")
        self._assert_expected_updated_at(row, expected_updated_at)

        if "dataset" in payload and payload.get("dataset"):
            dataset_id = _normalize_str(payload.get("dataset"))
            if not dataset_id:
                raise BaselineValidationError("Dataset cannot be empty")
            dataset = self.session.get(BaselineDataset, dataset_id)
            if not dataset:
                now = utc_now()
                dataset = BaselineDataset(
                    id=dataset_id,
                    label=dataset_id,
                    description=None,
                    source_file=None,
                    original_count=0,
                    created_at=now,
                    updated_at=now,
                )
                self.session.add(dataset)
            row.dataset_id = dataset_id

        if "sequence" in payload:
            row.sequence = _normalize_str(payload.get("sequence"))
        if "n_terminal" in payload:
            row.n_terminal = _normalize_str(payload.get("n_terminal"))
        if "c_terminal" in payload:
            row.c_terminal = _normalize_str(payload.get("c_terminal"))
        if "labels" in payload:
            row.labels_json = self._validate_and_dump_labels(payload.get("labels"))
        if "doi" in payload:
            row.doi = _normalize_doi(payload.get("doi"))
        if "pubmed_id" in payload:
            row.pubmed_id = _normalize_str(payload.get("pubmed_id"))
        if "paper_url" in payload:
            row.paper_url = _normalize_url(payload.get("paper_url"))
        if "pdf_url" in payload:
            row.pdf_url = _normalize_url(payload.get("pdf_url"))
        if "metadata" in payload:
            row.metadata_json = self._validate_and_dump_metadata(payload.get("metadata"))
        if "source_unverified" in payload:
            row.source_unverified = bool(payload.get("source_unverified"))

        row.updated_at = utc_now()
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self._case_to_dict(row)

    def delete_case(self, case_id: str, expected_updated_at: Optional[str]) -> bool:
        row = self.session.get(BaselineCaseModel, case_id)
        if not row:
            return False
        self._assert_expected_updated_at(row, expected_updated_at)
        self.session.exec(delete(BaselineCaseRun).where(BaselineCaseRun.baseline_case_id == case_id))
        self.session.delete(row)
        self.session.commit()
        return True

    def delete_paper_group(self, paper_key: str, expected_updated_at: Optional[str] = None) -> int:
        cases = self.list_cases()
        case_ids: List[str] = []
        for case in cases:
            if case.get("paper_key") == paper_key:
                if expected_updated_at:
                    row = self.session.get(BaselineCaseModel, case["id"])
                    if row:
                        self._assert_expected_updated_at(row, expected_updated_at)
                case_ids.append(case["id"])
        if not case_ids:
            return 0
        self.session.exec(delete(BaselineCaseRun).where(BaselineCaseRun.baseline_case_id.in_(case_ids)))
        self.session.exec(delete(BaselineCaseModel).where(BaselineCaseModel.id.in_(case_ids)))
        self.session.commit()
        return len(case_ids)

    def seed_from_backup(self, index_payload: Dict[str, Any], dataset_cases: Dict[str, Iterable[Dict[str, Any]]]) -> int:
        if self.has_cases():
            return 0

        now = utc_now()
        dataset_rows = index_payload.get("datasets", []) if isinstance(index_payload, dict) else []
        known_ids = set()
        for entry in dataset_rows:
            dataset_id = _normalize_str((entry or {}).get("id"))
            if not dataset_id:
                continue
            known_ids.add(dataset_id)
            self.session.add(
                BaselineDataset(
                    id=dataset_id,
                    label=(entry or {}).get("label"),
                    description=(entry or {}).get("description"),
                    source_file=(entry or {}).get("source_file"),
                    original_count=int((entry or {}).get("count") or 0),
                    created_at=now,
                    updated_at=now,
                )
            )

        inserted = 0
        for dataset_id, cases in dataset_cases.items():
            normalized_dataset_id = _normalize_str(dataset_id)
            if not normalized_dataset_id:
                continue
            if normalized_dataset_id not in known_ids and not self.session.get(BaselineDataset, normalized_dataset_id):
                self.session.add(
                    BaselineDataset(
                        id=normalized_dataset_id,
                        label=normalized_dataset_id,
                        description=None,
                        source_file=None,
                        original_count=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
            for case_data in cases:
                case_id = _normalize_str((case_data or {}).get("id"))
                if not case_id:
                    continue
                if self.session.get(BaselineCaseModel, case_id):
                    continue
                self.session.add(
                    BaselineCaseModel(
                        id=case_id,
                        dataset_id=normalized_dataset_id,
                        sequence=_normalize_str((case_data or {}).get("sequence")),
                        n_terminal=_normalize_str((case_data or {}).get("n_terminal")),
                        c_terminal=_normalize_str((case_data or {}).get("c_terminal")),
                        labels_json=self._validate_and_dump_labels((case_data or {}).get("labels")),
                        doi=_normalize_doi((case_data or {}).get("doi")),
                        pubmed_id=_normalize_str((case_data or {}).get("pubmed_id")),
                        paper_url=_normalize_url((case_data or {}).get("paper_url")),
                        pdf_url=_normalize_url((case_data or {}).get("pdf_url")),
                        metadata_json=self._validate_and_dump_metadata((case_data or {}).get("metadata")),
                        source_unverified=bool((case_data or {}).get("source_unverified", False)),
                        created_at=now,
                        updated_at=now,
                    )
                )
                inserted += 1

        self.session.commit()
        return inserted

    def reset_from_backup(
        self,
        index_payload: Dict[str, Any],
        dataset_cases: Dict[str, Iterable[Dict[str, Any]]],
    ) -> Dict[str, int]:
        deleted_cases = int(self.session.exec(select(func.count(BaselineCaseModel.id))).one() or 0)
        self.session.exec(delete(BaselineCaseModel))
        self.session.exec(delete(BaselineDataset))
        self.session.commit()
        inserted = self.seed_from_backup(index_payload, dataset_cases)
        return {
            "deleted_cases": deleted_cases,
            "inserted_cases": inserted,
            "total_cases": inserted,
        }

    def relink_runs_to_cases_from_papers(
        self,
        *,
        dataset: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Dict[str, int]:
        cases = self.list_cases(dataset)
        if not cases:
            return {"matched_runs": 0, "updated_runs": 0, "created_links": 0}

        by_doi: Dict[str, set[str]] = {}
        by_doi_base: Dict[str, set[str]] = {}
        by_paper_url: Dict[str, set[str]] = {}
        case_dataset: Dict[str, str] = {}

        def _add(mapping: Dict[str, set[str]], key: Optional[str], case_id: str) -> None:
            if not key:
                return
            mapping.setdefault(key, set()).add(case_id)

        for case in cases:
            case_id = case.get("id")
            if not case_id:
                continue
            dataset_id = str(case.get("dataset") or "")
            case_dataset[case_id] = dataset_id
            doi = _normalize_doi(case.get("doi"))
            doi_base = re.sub(r"/v\d+$", "", doi) if doi else None
            paper_url = _normalize_url(case.get("paper_url"))
            _add(by_doi, doi, case_id)
            _add(by_doi_base, doi_base, case_id)
            _add(by_paper_url, paper_url, case_id)

        existing_pairs = {
            (row.baseline_case_id, row.run_id) for row in self.session.exec(select(BaselineCaseRun)).all()
        }

        run_stmt = select(ExtractionRun).where(ExtractionRun.paper_id.is_not(None))
        if batch_id:
            run_stmt = run_stmt.where(ExtractionRun.batch_id == batch_id)

        matched_runs = 0
        updated_runs = 0
        created_links = 0
        runs = self.session.exec(run_stmt).all()
        for run in runs:
            paper = self.session.get(Paper, run.paper_id) if run.paper_id else None
            if not paper:
                continue

            candidate_case_ids: set[str] = set()
            normalized_doi = _normalize_doi(paper.doi)
            normalized_doi_base = re.sub(r"/v\d+$", "", normalized_doi) if normalized_doi else None
            paper_url = _normalize_url(paper.url)
            if normalized_doi:
                candidate_case_ids.update(by_doi.get(normalized_doi, set()))
            if normalized_doi_base:
                candidate_case_ids.update(by_doi_base.get(normalized_doi_base, set()))
            if paper_url:
                candidate_case_ids.update(by_paper_url.get(paper_url, set()))

            if not candidate_case_ids:
                continue

            matched_runs += 1
            sorted_case_ids = sorted(candidate_case_ids)
            for case_id in sorted_case_ids:
                pair = (case_id, run.id)
                if pair in existing_pairs:
                    continue
                self.session.add(BaselineCaseRun(baseline_case_id=case_id, run_id=run.id))
                existing_pairs.add(pair)
                created_links += 1

            preferred_case_id = sorted_case_ids[0]
            changed = False
            if run.baseline_case_id != preferred_case_id:
                run.baseline_case_id = preferred_case_id
                changed = True
            preferred_dataset = case_dataset.get(preferred_case_id)
            if preferred_dataset and run.baseline_dataset != preferred_dataset:
                run.baseline_dataset = preferred_dataset
                changed = True
            if changed:
                self.session.add(run)
                updated_runs += 1

        self.session.commit()
        return {
            "matched_runs": matched_runs,
            "updated_runs": updated_runs,
            "created_links": created_links,
        }

    @staticmethod
    def _validate_and_dump_labels(labels: Any) -> str:
        if labels is None:
            return "[]"
        if not isinstance(labels, list):
            raise BaselineValidationError("labels must be a list")
        normalized: List[str] = []
        for item in labels:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                normalized.append(text)
        return _to_json_text(normalized, "[]")

    @staticmethod
    def _validate_and_dump_metadata(metadata: Any) -> str:
        if metadata is None:
            return "{}"
        if not isinstance(metadata, dict):
            raise BaselineValidationError("metadata must be an object")
        return _to_json_text(metadata, "{}")

    @staticmethod
    def _paper_key_from_row(row: BaselineCaseModel) -> str:
        if row.doi:
            return f"doi:{row.doi}"
        if row.pubmed_id:
            return f"pubmed:{row.pubmed_id.strip()}"
        if row.paper_url:
            return f"url:{row.paper_url.strip()}"
        return f"case:{row.id}"

    def _case_to_dict(self, row: BaselineCaseModel) -> Dict[str, Any]:
        labels = []
        metadata = {}
        try:
            labels = json.loads(row.labels_json or "[]")
        except Exception:
            labels = []
        try:
            metadata = json.loads(row.metadata_json or "{}")
        except Exception:
            metadata = {}
        return {
            "id": row.id,
            "dataset": row.dataset_id,
            "sequence": row.sequence,
            "n_terminal": row.n_terminal,
            "c_terminal": row.c_terminal,
            "labels": labels if isinstance(labels, list) else [],
            "doi": row.doi,
            "pubmed_id": row.pubmed_id,
            "paper_url": row.paper_url,
            "pdf_url": row.pdf_url,
            "metadata": metadata if isinstance(metadata, dict) else {},
            "source_unverified": bool(row.source_unverified),
            "paper_key": self._paper_key_from_row(row),
            "updated_at": iso_z(row.updated_at),
        }

    @staticmethod
    def _assert_expected_updated_at(row: BaselineCaseModel, expected_updated_at: Optional[str]) -> None:
        if not expected_updated_at:
            raise BaselineConflictError("expected_updated_at is required")
        expected = _parse_iso_timestamp(expected_updated_at)
        if expected is None:
            raise BaselineValidationError("expected_updated_at must be a valid ISO timestamp")

        current = row.updated_at
        if current.tzinfo is None and expected.tzinfo is not None:
            current = current.replace(tzinfo=expected.tzinfo)
        if current != expected:
            raise BaselineConflictError("Baseline case was updated by another user")
