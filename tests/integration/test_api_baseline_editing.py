import unittest
from urllib.parse import quote

from sqlmodel import Session, select

from app.persistence.models import BaselineCaseRun, BatchRun, BatchStatus, RunStatus
from support import ApiIntegrationTestCase


class BaselineEditingApiTests(ApiIntegrationTestCase):
    def test_startup_seeds_baseline_cases_from_backup_when_empty(self) -> None:
        response = self.client.get("/api/baseline/cases?dataset=self_assembly")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("total_cases", payload)
        self.assertGreater(payload["total_cases"], 0)

    def test_create_update_delete_case_flow(self) -> None:
        create_response = self.client.post(
            "/api/baseline/cases",
            json={
                "id": "editable-case-1",
                "dataset": "self_assembly",
                "sequence": "ACDE",
                "labels": ["alpha"],
                "doi": "10.1000/editable-1",
                "metadata": {"note": "created"},
            },
        )
        self.assertEqual(create_response.status_code, 200)
        created = create_response.json()
        self.assertEqual(created["id"], "editable-case-1")
        self.assertIn("updated_at", created)
        self.assertTrue(created["updated_at"].endswith("Z"))

        patch_response = self.client.patch(
            "/api/baseline/cases/editable-case-1",
            json={
                "expected_updated_at": created["updated_at"],
                "sequence": "ACDEFG",
                "labels": ["alpha", "beta"],
                "source_unverified": True,
            },
        )
        self.assertEqual(patch_response.status_code, 200)
        updated = patch_response.json()
        self.assertEqual(updated["sequence"], "ACDEFG")
        self.assertEqual(updated["labels"], ["alpha", "beta"])
        self.assertTrue(updated["source_unverified"])
        self.assertNotEqual(updated["updated_at"], created["updated_at"])

        delete_response = self.client.request(
            "DELETE",
            "/api/baseline/cases/editable-case-1",
            json={"expected_updated_at": updated["updated_at"]},
        )
        self.assertEqual(delete_response.status_code, 200)
        delete_payload = delete_response.json()
        self.assertEqual(delete_payload["status"], "ok")
        self.assertEqual(delete_payload["deleted_cases"], 1)

    def test_update_case_stale_timestamp_returns_conflict_envelope(self) -> None:
        create_response = self.client.post(
            "/api/baseline/cases",
            json={
                "id": "editable-case-stale",
                "dataset": "self_assembly",
                "sequence": "AAAA",
                "labels": [],
                "metadata": {},
            },
        )
        self.assertEqual(create_response.status_code, 200)

        response = self.client.patch(
            "/api/baseline/cases/editable-case-stale",
            json={
                "expected_updated_at": "2000-01-01T00:00:00Z",
                "sequence": "BBBB",
            },
        )
        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertIn("error", payload)
        self.assertEqual(payload["error"]["code"], "conflict")

    def test_delete_paper_group_removes_all_group_cases(self) -> None:
        case_a = self.client.post(
            "/api/baseline/cases",
            json={
                "id": "group-delete-a",
                "dataset": "self_assembly",
                "pubmed_id": "group-delete-pmid",
                "sequence": "AAAA",
                "labels": [],
                "metadata": {},
            },
        )
        self.assertEqual(case_a.status_code, 200)
        case_b = self.client.post(
            "/api/baseline/cases",
            json={
                "id": "group-delete-b",
                "dataset": "self_assembly",
                "pubmed_id": "group-delete-pmid",
                "sequence": "BBBB",
                "labels": [],
                "metadata": {},
            },
        )
        self.assertEqual(case_b.status_code, 200)

        paper_key = case_a.json()["paper_key"]
        response = self.client.delete(f"/api/baseline/papers/{quote(paper_key, safe='')}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["deleted_cases"], 2)

        cases_response = self.client.get("/api/baseline/cases?dataset=self_assembly")
        self.assertEqual(cases_response.status_code, 200)
        remaining_ids = {item["id"] for item in cases_response.json()["cases"]}
        self.assertNotIn("group-delete-a", remaining_ids)
        self.assertNotIn("group-delete-b", remaining_ids)

    def test_delete_paper_group_accepts_url_based_paper_key(self) -> None:
        case_a = self.client.post(
            "/api/baseline/cases",
            json={
                "id": "group-url-a",
                "dataset": "self_assembly",
                "paper_url": "https://example.org/papers/group/url-path",
                "sequence": "AAAA",
                "labels": [],
                "metadata": {},
            },
        )
        self.assertEqual(case_a.status_code, 200)
        case_b = self.client.post(
            "/api/baseline/cases",
            json={
                "id": "group-url-b",
                "dataset": "self_assembly",
                "paper_url": "https://example.org/papers/group/url-path",
                "sequence": "BBBB",
                "labels": [],
                "metadata": {},
            },
        )
        self.assertEqual(case_b.status_code, 200)

        paper_key = case_a.json()["paper_key"]
        self.assertTrue(paper_key.startswith("url:"))
        response = self.client.delete(f"/api/baseline/papers/{quote(paper_key, safe='')}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["deleted_cases"], 2)

    def test_reset_baseline_defaults_restores_backup_and_removes_live_edits(self) -> None:
        create_response = self.client.post(
            "/api/baseline/cases",
            json={
                "id": "reset-me-live-case",
                "dataset": "self_assembly",
                "sequence": "ZZZZ",
                "labels": ["tmp"],
                "metadata": {"live": True},
            },
        )
        self.assertEqual(create_response.status_code, 200)

        reset_response = self.client.post("/api/baseline/reset-defaults")
        self.assertEqual(reset_response.status_code, 200)
        payload = reset_response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertGreaterEqual(payload["deleted_cases"], 1)
        self.assertGreater(payload["inserted_cases"], 0)
        self.assertGreater(payload["total_cases"], 0)

        cases_response = self.client.get("/api/baseline/cases?dataset=self_assembly")
        self.assertEqual(cases_response.status_code, 200)
        ids = {item["id"] for item in cases_response.json()["cases"]}
        self.assertNotIn("reset-me-live-case", ids)

    def test_reset_baseline_defaults_repairs_case_run_links_from_paper_metadata(self) -> None:
        paper_id = self.create_paper(
            title="Reset Repair Link",
            doi="10.1002/anie.200604014",
            url=None,
            source="baseline-test",
        )
        run_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.STORED.value,
            model_provider="mock",
            model_name="mock-model",
            batch_id="repair-link-batch",
        )
        with Session(self.db_module.engine) as session:
            session.add(
                BatchRun(
                    batch_id="repair-link-batch",
                    label="Repair Link Batch",
                    dataset="self_assembly",
                    model_provider="mock",
                    model_name="mock-model",
                    status=BatchStatus.RUNNING.value,
                    total_papers=69,
                    completed=0,
                    failed=0,
                )
            )
            session.commit()

        reset_response = self.client.post("/api/baseline/reset-defaults")
        self.assertEqual(reset_response.status_code, 200)

        with Session(self.db_module.engine) as session:
            links = session.exec(
                select(BaselineCaseRun).where(BaselineCaseRun.run_id == run_id)
            ).all()
            self.assertGreater(len(links), 0)

        cases_response = self.client.get("/api/baseline/cases?dataset=self_assembly")
        self.assertEqual(cases_response.status_code, 200)
        target = None
        for case in cases_response.json().get("cases", []):
            if case.get("doi") == "10.1002/anie.200604014":
                target = case
                break
        self.assertIsNotNone(target)
        self.assertIsNotNone(target.get("latest_run"))
        self.assertEqual(target["latest_run"]["run_id"], run_id)

        batches_response = self.client.get("/api/baseline/batches?dataset=self_assembly")
        self.assertEqual(batches_response.status_code, 200)
        row = next(
            (
                item
                for item in batches_response.json().get("batches", [])
                if item.get("batch_id") == "repair-link-batch"
            ),
            None,
        )
        self.assertIsNotNone(row)
        self.assertGreater(row["completed"], 0)
        self.assertGreater(row["total_expected_entities"], 0)

    def test_recompute_status_contract_shape(self) -> None:
        response = self.client.get("/api/baseline/recompute-status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for key in [
            "running",
            "queued",
            "stale_batches",
            "processing_batches",
            "last_started_at",
            "last_finished_at",
        ]:
            self.assertIn(key, payload)
        self.assertIsInstance(payload["running"], bool)
        self.assertIsInstance(payload["queued"], bool)
        self.assertIsInstance(payload["stale_batches"], int)
        self.assertIsInstance(payload["processing_batches"], int)


if __name__ == "__main__":
    unittest.main()
