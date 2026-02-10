import tempfile
import unittest
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from app.persistence.models import BaselineCaseRun, ExtractionRun
from app.services.baseline_store import (
    BaselineConflictError,
    BaselineStore,
    BaselineValidationError,
)


class BaselineStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "baseline_store.db"
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.store = BaselineStore(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_create_case_normalizes_core_fields(self) -> None:
        payload = {
            "id": "case-1",
            "dataset": "self_assembly",
            "sequence": "  A C D  ",
            "labels": [" hydrogel ", None, "self-assembly"],
            "doi": "https://doi.org/10.1000/ABC",
            "paper_url": " https://example.org/paper ",
            "metadata": {"k": "v"},
            "source_unverified": True,
        }
        created = self.store.create_case(payload)

        self.assertEqual(created["id"], "case-1")
        self.assertEqual(created["dataset"], "self_assembly")
        self.assertEqual(created["doi"], "10.1000/abc")
        self.assertEqual(created["paper_url"], "https://example.org/paper")
        self.assertEqual(created["labels"], ["hydrogel", "self-assembly"])
        self.assertEqual(created["paper_key"], "doi:10.1000/abc")
        self.assertTrue(created["source_unverified"])
        self.assertTrue(created["updated_at"].endswith("Z"))

    def test_update_case_requires_fresh_expected_updated_at(self) -> None:
        created = self.store.create_case(
            {
                "id": "case-2",
                "dataset": "self_assembly",
                "labels": [],
                "metadata": {},
            }
        )
        with self.assertRaises(BaselineConflictError):
            self.store.update_case(
                "case-2",
                {"sequence": "UPDATED"},
                expected_updated_at="2000-01-01T00:00:00Z",
            )

        updated = self.store.update_case(
            "case-2",
            {"sequence": "UPDATED"},
            expected_updated_at=created["updated_at"],
        )
        self.assertEqual(updated["sequence"], "UPDATED")

    def test_create_case_rejects_non_object_metadata(self) -> None:
        with self.assertRaises(BaselineValidationError):
            self.store.create_case(
                {
                    "id": "case-invalid-meta",
                    "dataset": "self_assembly",
                    "labels": [],
                    "metadata": ["not", "an", "object"],
                }
            )

    def test_delete_paper_group_removes_all_cases_and_links(self) -> None:
        case_a = self.store.create_case(
            {
                "id": "group-a",
                "dataset": "self_assembly",
                "doi": "10.1000/group-paper",
                "labels": [],
                "metadata": {},
            }
        )
        case_b = self.store.create_case(
            {
                "id": "group-b",
                "dataset": "self_assembly",
                "doi": "10.1000/group-paper",
                "labels": [],
                "metadata": {},
            }
        )

        run = ExtractionRun(status="queued")
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        self.session.add(BaselineCaseRun(baseline_case_id=case_a["id"], run_id=run.id))
        self.session.add(BaselineCaseRun(baseline_case_id=case_b["id"], run_id=run.id))
        self.session.commit()

        deleted = self.store.delete_paper_group(case_a["paper_key"])
        self.assertEqual(deleted, 2)

        remaining_cases = self.store.list_cases("self_assembly")
        self.assertEqual([item["id"] for item in remaining_cases], [])
        remaining_links = self.session.exec(select(BaselineCaseRun)).all()
        self.assertEqual(len(remaining_links), 0)


if __name__ == "__main__":
    unittest.main()
