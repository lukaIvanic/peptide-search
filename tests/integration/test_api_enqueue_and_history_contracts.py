import unittest

from support import ApiIntegrationTestCase


class ApiEnqueueAndHistoryContractTests(ApiIntegrationTestCase):
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


if __name__ == "__main__":
    unittest.main()
