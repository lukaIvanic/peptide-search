import unittest
import json

from sqlmodel import Session, select

from app.persistence.models import ExtractionRun, QueueJob, RunStatus
from support import ApiIntegrationTestCase


class ApiEnqueueAndHistoryContractTests(ApiIntegrationTestCase):
    def assert_error_envelope(
        self,
        response,
        *,
        status_code: int,
        code: str,
    ) -> dict:
        self.assertEqual(response.status_code, status_code)
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["code"], code)
        self.assertIn("message", body["error"])
        return body

    def assert_utc_timestamp(self, value: str) -> None:
        self.assertIsInstance(value, str)
        self.assertTrue(value.endswith("Z"))

    def test_error_envelope_shape_for_missing_run(self) -> None:
        response = self.client.get("/api/runs/999999")
        self.assert_error_envelope(response, status_code=404, code="not_found")

    def test_removed_search_and_enqueue_endpoints_return_not_found(self) -> None:
        search_response = self.client.get("/api/search?q=peptide")
        self.assertEqual(search_response.status_code, 404)
        search_body = search_response.json()
        if "error" in search_body:
            self.assertEqual(search_body["error"].get("code"), "not_found")
        else:
            self.assertIn("detail", search_body)

        enqueue_response = self.client.post("/api/enqueue", json={"provider": "mock"})
        self.assertEqual(enqueue_response.status_code, 404)
        enqueue_body = enqueue_response.json()
        if "error" in enqueue_body:
            self.assertEqual(enqueue_body["error"].get("code"), "not_found")
        else:
            self.assertIn("detail", enqueue_body)

    def test_bad_request_error_mapping_for_extract_contract(self) -> None:
        response = self.client.post("/api/extract", json={})
        self.assert_error_envelope(response, status_code=400, code="bad_request")

    def test_extract_file_enqueues_with_canonical_primary_source(self) -> None:
        response = self.client.post(
            "/api/extract-file",
            files=[
                ("files", ("paper-main.pdf", b"%PDF-1.4 main", "application/pdf")),
                ("files", ("paper-si.pdf", b"%PDF-1.4 si", "application/pdf")),
            ],
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        run_id = body["run_id"]

        with Session(self.db_module.engine) as session:
            run = session.get(ExtractionRun, run_id)
            self.assertIsNotNone(run)
            self.assertTrue(run.pdf_url)

            job = session.exec(select(QueueJob).where(QueueJob.run_id == run_id)).first()
            self.assertIsNotNone(job)
            payload = json.loads(job.payload_json or "{}")
            self.assertEqual(payload.get("pdf_url"), run.pdf_url)
            self.assertIsInstance(payload.get("pdf_urls"), list)
            self.assertGreaterEqual(len(payload["pdf_urls"]), 2)
            self.assertEqual(payload["pdf_urls"][0], run.pdf_url)

    def test_run_detail_schema_keys_are_stable(self) -> None:
        paper_id = self.create_paper(
            title="Detail Paper",
            doi="10.1000/detail",
            url="https://example.org/detail",
        )
        run_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider error",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/detail.pdf",
        )

        response = self.client.get(f"/api/runs/{run_id}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertSetEqual(set(body.keys()), {"paper", "run"})

        run_payload = body["run"]
        for key in [
            "id",
            "paper_id",
            "parent_run_id",
            "baseline_case_id",
            "baseline_dataset",
            "status",
            "failure_reason",
            "prompts",
            "raw_json",
            "comment",
            "model_provider",
            "model_name",
            "pdf_url",
            "created_at",
        ]:
            self.assertIn(key, run_payload)
        self.assert_utc_timestamp(run_payload["created_at"])

    def test_retry_response_schema_keys_are_stable(self) -> None:
        paper_id = self.create_paper(
            title="Retry Contract",
            doi="10.1000/retry-contract",
            url="https://example.org/retry-contract",
        )
        run_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider error",
            model_provider="mock",
            pdf_url="https://example.org/retry-contract.pdf",
        )

        response = self.client.post(f"/api/runs/{run_id}/retry")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertSetEqual(set(payload.keys()), {"id", "status", "message", "source_url"})
        self.assertEqual(payload["id"], run_id)
        self.assertEqual(payload["status"], RunStatus.QUEUED.value)

    def test_delete_run_response_schema_keys_are_stable(self) -> None:
        paper_id = self.create_paper(
            title="Delete Run Contract",
            doi="10.1000/delete-run-contract",
            url="https://example.org/delete-run-contract",
        )
        run_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            model_provider="mock",
            pdf_url="https://example.org/delete-run-contract.pdf",
        )

        response = self.client.delete(f"/api/runs/{run_id}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertSetEqual(
            set(payload.keys()),
            {
                "status",
                "deleted_runs",
                "deleted_entities",
                "deleted_queue_jobs",
                "deleted_source_locks",
                "deleted_case_links",
            },
        )
        self.assertEqual(payload["status"], "ok")

    def test_delete_paper_response_schema_keys_are_stable(self) -> None:
        paper_id = self.create_paper(
            title="Delete Paper Contract",
            doi="10.1000/delete-paper-contract",
            url="https://example.org/delete-paper-contract",
        )
        self.create_run(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            model_provider="mock",
            pdf_url="https://example.org/delete-paper-contract.pdf",
        )

        response = self.client.delete(f"/api/papers/{paper_id}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertSetEqual(
            set(payload.keys()),
            {
                "status",
                "paper_id",
                "deleted_runs",
                "deleted_entities",
                "deleted_queue_jobs",
                "deleted_source_locks",
                "deleted_case_links",
            },
        )
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["paper_id"], paper_id)

    def test_recent_runs_timestamp_contract_uses_utc_z_suffix(self) -> None:
        paper_id = self.create_paper(
            title="Recent Contract",
            doi="10.1000/recent-contract",
            url="https://example.org/recent-contract",
        )
        self.create_run(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            pdf_url="https://example.org/recent-contract.pdf",
        )

        response = self.client.get("/api/runs/recent?limit=5")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("runs", body)
        self.assertGreaterEqual(len(body["runs"]), 1)
        self.assert_utc_timestamp(body["runs"][0]["created_at"])

    def test_extractions_timestamp_contract_uses_utc_z_suffix(self) -> None:
        paper_id = self.create_paper(
            title="Extraction Contract",
            doi="10.1000/extraction-contract",
            url="https://example.org/extraction-contract",
        )
        run_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.STORED.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/extraction-contract.pdf",
        )

        response = self.client.get("/api/extractions")
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        row = next((item for item in rows if item["id"] == run_id), None)
        self.assertIsNotNone(row)
        self.assert_utc_timestamp(row["created_at"])

    def test_run_history_lineage_contract(self) -> None:
        paper_id = self.create_paper(
            title="History Paper",
            doi="10.1000/history-1",
            url="https://example.org/history-1",
        )
        parent_id = self.create_run(
            paper_id=paper_id,
            status="failed",
            failure_reason="provider error",
            model_provider="mock",
            pdf_url="https://example.org/history-parent.pdf",
        )

        child_resp = self.client.post(
            f"/api/runs/{parent_id}/retry-with-source",
            json={"source_url": "https://example.org/history-child.pdf", "provider": "mock"},
        )
        self.assertEqual(child_resp.status_code, 200)
        child_id = child_resp.json()["id"]

        grandchild_resp = self.client.post(
            f"/api/runs/{child_id}/retry-with-source",
            json={"source_url": "https://example.org/history-grandchild.pdf", "provider": "mock"},
        )
        self.assertEqual(grandchild_resp.status_code, 200)
        grandchild_id = grandchild_resp.json()["id"]

        history = self.client.get(f"/api/runs/{grandchild_id}/history")
        self.assertEqual(history.status_code, 200)
        body = history.json()

        self.assertEqual(body["paper_id"], paper_id)
        self.assertIsInstance(body["versions"], list)
        self.assertGreaterEqual(len(body["versions"]), 3)

        by_id = {item["id"]: item for item in body["versions"]}
        self.assertIn(parent_id, by_id)
        self.assertIn(child_id, by_id)
        self.assertIn(grandchild_id, by_id)

        self.assertIsNone(by_id[parent_id]["parent_run_id"])
        self.assertEqual(by_id[child_id]["parent_run_id"], parent_id)
        self.assertEqual(by_id[grandchild_id]["parent_run_id"], child_id)

        for run_id in [parent_id, child_id, grandchild_id]:
            self.assertIn("status", by_id[run_id])
            self.assertIn("model_provider", by_id[run_id])
            self.assertIn("model_name", by_id[run_id])
            self.assertIn("created_at", by_id[run_id])
            self.assert_utc_timestamp(by_id[run_id]["created_at"])

    def test_run_history_for_null_paper_is_scoped_to_lineage(self) -> None:
        parent_id = self.create_run(
            paper_id=None,
            status=RunStatus.FAILED.value,
            failure_reason="provider error",
            model_provider="mock",
            pdf_url="https://example.org/null-parent.pdf",
        )
        child_id = self.create_run(
            paper_id=None,
            parent_run_id=parent_id,
            status=RunStatus.STORED.value,
            model_provider="mock",
            pdf_url="https://example.org/null-child.pdf",
        )
        unrelated_id = self.create_run(
            paper_id=None,
            status=RunStatus.STORED.value,
            model_provider="mock",
            pdf_url="https://example.org/null-unrelated.pdf",
        )

        history = self.client.get(f"/api/runs/{child_id}/history")
        self.assertEqual(history.status_code, 200)
        body = history.json()

        self.assertIsNone(body["paper_id"])
        version_ids = {item["id"] for item in body["versions"]}
        self.assertIn(parent_id, version_ids)
        self.assertIn(child_id, version_ids)
        self.assertNotIn(unrelated_id, version_ids)


if __name__ == "__main__":
    unittest.main()
