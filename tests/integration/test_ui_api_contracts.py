import re
import unittest
from pathlib import Path

from sqlmodel import Session

from app.config import settings
from app.persistence.models import BatchRun, BatchStatus, RunStatus
from support import ApiIntegrationTestCase


class UiApiContractTests(ApiIntegrationTestCase):
    def test_baseline_cases_contract_exposes_paper_key_unverified_and_updated_at(self) -> None:
        response = self.client.get("/api/baseline/cases?dataset=self_assembly")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("cases", payload)
        self.assertGreater(len(payload["cases"]), 0)

        first_case = payload["cases"][0]
        self.assertIn("paper_key", first_case)
        self.assertIn("source_unverified", first_case)
        self.assertIn("updated_at", first_case)
        self.assertIsInstance(first_case["paper_key"], str)
        self.assertIsInstance(first_case["source_unverified"], bool)
        if first_case["updated_at"] is not None:
            self.assertTrue(first_case["updated_at"].endswith("Z"))

    def test_baseline_batches_contract_has_required_keys(self) -> None:
        with Session(self.db_module.engine) as session:
            batch = BatchRun(
                batch_id="ui_contract_batch",
                label="UI Contract Batch",
                dataset="self_assembly",
                model_provider="mock",
                model_name="mock-model",
                status=BatchStatus.RUNNING.value,
                total_papers=3,
                completed=1,
                failed=1,
            )
            session.add(batch)
            session.commit()

        response = self.client.get("/api/baseline/batches")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("batches", payload)
        self.assertGreaterEqual(len(payload["batches"]), 1)

        row = next((item for item in payload["batches"] if item["batch_id"] == "ui_contract_batch"), None)
        self.assertIsNotNone(row)
        for key in ["batch_id", "status", "completed", "failed", "total_papers", "created_at"]:
            self.assertIn(key, row)
        self.assertTrue(row["created_at"].endswith("Z"))

    def test_run_detail_and_history_contracts_have_required_keys(self) -> None:
        paper_id = self.create_paper(
            title="UI Contract Run",
            doi="10.1000/ui-run",
            url="https://example.org/ui-run",
        )
        run_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider error",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/ui-run.pdf",
        )

        run_response = self.client.get(f"/api/runs/{run_id}")
        self.assertEqual(run_response.status_code, 200)
        run_payload = run_response.json()
        self.assertIn("paper", run_payload)
        self.assertIn("run", run_payload)
        for key in ["id", "status", "pdf_url", "created_at"]:
            self.assertIn(key, run_payload["run"])
        self.assertTrue(run_payload["run"]["created_at"].endswith("Z"))

        history_response = self.client.get(f"/api/runs/{run_id}/history")
        self.assertEqual(history_response.status_code, 200)
        history_payload = history_response.json()
        self.assertIn("versions", history_payload)
        self.assertGreaterEqual(len(history_payload["versions"]), 1)
        first = history_payload["versions"][0]
        for key in ["id", "parent_run_id", "status", "created_at"]:
            self.assertIn(key, first)
        self.assertTrue(first["created_at"].endswith("Z"))

    def test_frontend_api_adapter_exports_methods_used_by_ui_modules(self) -> None:
        static_dir = Path(settings.STATIC_DIR)
        api_path = static_dir / "js" / "api.js"
        self.assertTrue(api_path.exists())
        api_source = api_path.read_text(encoding="utf-8")

        # Collect api.<method>(...) usages only from files that import "* as api".
        required_methods: set[str] = set()
        for js_path in static_dir.rglob("*.js"):
            source = js_path.read_text(encoding="utf-8")
            if "import * as api from" not in source:
                continue
            required_methods.update(re.findall(r"\bapi\.([A-Za-z_]\w*)\s*\(", source))

        self.assertGreater(len(required_methods), 0)
        missing = []
        for method in sorted(required_methods):
            function_export = re.search(
                rf"export\s+(?:async\s+)?function\s+{re.escape(method)}\s*\(",
                api_source,
            )
            const_export = re.search(
                rf"export\s+const\s+{re.escape(method)}\s*=",
                api_source,
            )
            if not (function_export or const_export):
                missing.append(method)

        self.assertEqual(missing, [], f"public/js/api.js missing exports for: {missing}")


if __name__ == "__main__":
    unittest.main()
