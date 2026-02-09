import unittest

from app.persistence.models import RunStatus
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

    def test_validation_error_envelope_for_malformed_enqueue_payload(self) -> None:
        response = self.client.post("/api/enqueue", json={"provider": "mock"})
        body = self.assert_error_envelope(response, status_code=422, code="validation_error")
        self.assertIsInstance(body["error"].get("details"), list)

    def test_bad_request_error_mapping_for_extract_contract(self) -> None:
        response = self.client.post("/api/extract", json={})
        self.assert_error_envelope(response, status_code=400, code="bad_request")

    def test_enqueue_contract_and_url_dedupe(self) -> None:
        payload = {
            "papers": [
                {
                    "title": "Contract Test Paper",
                    "doi": "10.1000/contract-1",
                    "url": "https://example.org/contract-1",
                    "pdf_url": "https://example.org/contract-1.pdf",
                    "source": "pmc",
                    "year": 2024,
                    "authors": ["A. Author"],
                    "force": False,
                }
            ],
            "provider": "mock",
            "prompt_id": None,
        }

        first = self.client.post("/api/enqueue", json=payload)
        self.assertEqual(first.status_code, 200)
        first_body = first.json()

        self.assertEqual(first_body["total"], 1)
        self.assertEqual(first_body["enqueued"], 1)
        self.assertEqual(first_body["skipped"], 0)
        self.assertEqual(len(first_body["runs"]), 1)

        first_run = first_body["runs"][0]
        for key in ["run_id", "paper_id", "title", "status", "skipped", "skip_reason"]:
            self.assertIn(key, first_run)
        self.assertEqual(first_run["status"], "queued")
        self.assertFalse(first_run["skipped"])

        second = self.client.post("/api/enqueue", json=payload)
        self.assertEqual(second.status_code, 200)
        second_body = second.json()

        self.assertEqual(second_body["total"], 1)
        self.assertEqual(second_body["enqueued"], 0)
        self.assertEqual(second_body["skipped"], 1)
        self.assertEqual(len(second_body["runs"]), 1)

        second_run = second_body["runs"][0]
        self.assertTrue(second_run["skipped"])
        self.assertEqual(second_run["skip_reason"], "Already queued")
        self.assertEqual(second_run["run_id"], first_run["run_id"])
        self.assertEqual(second_run["paper_id"], first_run["paper_id"])

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


if __name__ == "__main__":
    unittest.main()
