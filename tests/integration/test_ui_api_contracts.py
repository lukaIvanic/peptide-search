import json
import re
import unittest
from datetime import timedelta
from pathlib import Path

from sqlmodel import Session, select

from app.config import settings
from app.persistence.models import (
    ActiveSourceLock,
    BaselineCaseRun,
    BatchRun,
    BatchStatus,
    QueueJob,
    QueueJobStatus,
    RunStatus,
)
from app.time_utils import utc_now
from support import ApiIntegrationTestCase


class UiApiContractTests(ApiIntegrationTestCase):
    def test_baseline_latest_run_supports_batch_scope(self) -> None:
        initial = self.client.get("/api/baseline/cases?dataset=self_assembly")
        self.assertEqual(initial.status_code, 200)
        cases = initial.json().get("cases", [])
        self.assertGreater(len(cases), 0)
        case_id = cases[0]["id"]

        older_ts = utc_now()
        newer_ts = older_ts + timedelta(seconds=1)
        target_batch_id = "ui_contract_latest_run_scope_target"
        other_batch_id = "ui_contract_latest_run_scope_other"

        target_run = self.create_run_row(
            status=RunStatus.STORED.value,
            batch_id=target_batch_id,
            baseline_dataset="self_assembly",
            baseline_case_id=case_id,
            model_provider="mock",
            model_name="mock-model",
            created_at=older_ts,
        )
        other_run = self.create_run_row(
            status=RunStatus.STORED.value,
            batch_id=other_batch_id,
            baseline_dataset="self_assembly",
            baseline_case_id=case_id,
            model_provider="mock",
            model_name="mock-model",
            created_at=newer_ts,
        )

        with Session(self.db_module.engine) as session:
            session.add(BaselineCaseRun(baseline_case_id=case_id, run_id=target_run.id))
            session.add(BaselineCaseRun(baseline_case_id=case_id, run_id=other_run.id))
            session.commit()

        scoped = self.client.get(
            f"/api/baseline/cases/{case_id}/latest-run?batch_id={target_batch_id}"
        )
        self.assertEqual(scoped.status_code, 200)
        scoped_payload = scoped.json()
        self.assertEqual(scoped_payload["run"]["id"], target_run.id)
        self.assertEqual(scoped_payload["run"]["batch_id"], target_batch_id)

        unscoped = self.client.get(f"/api/baseline/cases/{case_id}/latest-run")
        self.assertEqual(unscoped.status_code, 200)
        unscoped_payload = unscoped.json()
        self.assertEqual(unscoped_payload["run"]["id"], other_run.id)
        self.assertEqual(unscoped_payload["run"]["batch_id"], other_batch_id)

    def test_baseline_cases_supports_batch_scoped_latest_run(self) -> None:
        initial = self.client.get("/api/baseline/cases?dataset=self_assembly")
        self.assertEqual(initial.status_code, 200)
        cases = initial.json().get("cases", [])
        self.assertGreater(len(cases), 0)
        case_id = cases[0]["id"]

        older_ts = utc_now()
        newer_ts = older_ts + timedelta(seconds=1)
        target_batch_id = "ui_contract_scope_target"
        other_batch_id = "ui_contract_scope_other"

        target_run = self.create_run_row(
            status=RunStatus.STORED.value,
            batch_id=target_batch_id,
            baseline_dataset="self_assembly",
            baseline_case_id=case_id,
            model_provider="mock",
            model_name="mock-model",
            created_at=older_ts,
        )
        other_run = self.create_run_row(
            status=RunStatus.STORED.value,
            batch_id=other_batch_id,
            baseline_dataset="self_assembly",
            baseline_case_id=case_id,
            model_provider="mock",
            model_name="mock-model",
            created_at=newer_ts,
        )

        with Session(self.db_module.engine) as session:
            session.add(BaselineCaseRun(baseline_case_id=case_id, run_id=target_run.id))
            session.add(BaselineCaseRun(baseline_case_id=case_id, run_id=other_run.id))
            session.commit()

        scoped = self.client.get(
            f"/api/baseline/cases?dataset=self_assembly&batch_id={target_batch_id}"
        )
        self.assertEqual(scoped.status_code, 200)
        scoped_cases = scoped.json().get("cases", [])
        scoped_case = next((item for item in scoped_cases if item.get("id") == case_id), None)
        self.assertIsNotNone(scoped_case)
        self.assertIsNotNone(scoped_case["latest_run"])
        self.assertEqual(scoped_case["latest_run"]["run_id"], target_run.id)
        self.assertEqual(scoped_case["latest_run"]["batch_id"], target_batch_id)

        unscoped = self.client.get("/api/baseline/cases?dataset=self_assembly")
        self.assertEqual(unscoped.status_code, 200)
        unscoped_cases = unscoped.json().get("cases", [])
        unscoped_case = next((item for item in unscoped_cases if item.get("id") == case_id), None)
        self.assertIsNotNone(unscoped_case)
        self.assertIsNotNone(unscoped_case["latest_run"])
        self.assertEqual(unscoped_case["latest_run"]["run_id"], other_run.id)
        self.assertEqual(unscoped_case["latest_run"]["batch_id"], other_batch_id)

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
        for key in ["batch_id", "status", "completed", "failed", "total_papers", "papers_all_matched", "created_at"]:
            self.assertIn(key, row)
        self.assertTrue(row["created_at"].endswith("Z"))

    def test_baseline_batches_reports_papers_all_matched_from_run_level_coverage(self) -> None:
        cases_response = self.client.get("/api/baseline/cases?dataset=self_assembly")
        self.assertEqual(cases_response.status_code, 200)
        cases = cases_response.json().get("cases", [])

        grouped: dict[str, list[dict[str, object]]] = {}
        for case in cases:
            case_id = case.get("id")
            paper_key = case.get("paper_key")
            sequence = case.get("sequence")
            if not case_id or not paper_key or not sequence:
                continue
            grouped.setdefault(str(paper_key), []).append(case)
        self.assertGreater(len(grouped), 0)

        paper_cases = next(iter(grouped.values()))
        batch_id = "ui_contract_all_matched_batch"
        with Session(self.db_module.engine) as session:
            batch = BatchRun(
                batch_id=batch_id,
                label="All Matched Contract Batch",
                dataset="self_assembly",
                model_provider="mock",
                model_name="mock-model",
                status=BatchStatus.COMPLETED.value,
                total_papers=1,
                completed=1,
                failed=0,
            )
            session.add(batch)
            session.commit()

        raw_json = json.dumps(
            {
                "entities": [
                    {
                        "peptide": {
                            "sequence_one_letter": str(case.get("sequence")),
                        }
                    }
                    for case in paper_cases
                ]
            }
        )
        run = self.create_run_row(
            status=RunStatus.STORED.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            baseline_case_id=str(paper_cases[0].get("id")),
            model_provider="mock",
            model_name="mock-model",
            raw_json=raw_json,
        )

        with Session(self.db_module.engine) as session:
            for case in paper_cases:
                session.add(
                    BaselineCaseRun(
                        baseline_case_id=str(case.get("id")),
                        run_id=run.id,
                    )
                )
            session.commit()

        response = self.client.get("/api/baseline/batches?dataset=self_assembly")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        row = next((item for item in payload.get("batches", []) if item.get("batch_id") == batch_id), None)
        self.assertIsNotNone(row)
        self.assertEqual(row.get("papers_all_matched"), 1)

    def test_batch_stop_cancels_in_progress_runs(self) -> None:
        batch_id = "ui_contract_batch_stop"
        with Session(self.db_module.engine) as session:
            batch = BatchRun(
                batch_id=batch_id,
                label="Batch Stop Contract",
                dataset="self_assembly",
                model_provider="mock",
                model_name="mock-model",
                status=BatchStatus.RUNNING.value,
                total_papers=2,
                completed=0,
                failed=0,
            )
            session.add(batch)
            session.commit()

        running_run = self.create_run_row(
            status=RunStatus.PROVIDER.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/stop-1.pdf",
        )
        stored_run = self.create_run_row(
            status=RunStatus.STORED.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/stop-2.pdf",
        )
        self.create_queue_job(
            run_id=running_run.id,
            pdf_url="https://example.org/stop-1.pdf",
            status=QueueJobStatus.CLAIMED.value,
            claim_token="test-token",
            claimed_by="worker-test",
            claimed_at=utc_now(),
        )
        self.create_source_lock(run_id=running_run.id, source_url="https://example.org/stop-1.pdf")

        response = self.client.post(
            "/api/baseline/batch-stop",
            json={"batch_id": batch_id},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("batch_id"), batch_id)
        self.assertEqual(payload.get("cancelled_runs"), 1)
        self.assertEqual(payload.get("cancelled_jobs"), 1)

        with Session(self.db_module.engine) as session:
            refreshed_running = session.get(type(running_run), running_run.id)
            refreshed_stored = session.get(type(stored_run), stored_run.id)
            self.assertIsNotNone(refreshed_running)
            self.assertIsNotNone(refreshed_stored)
            self.assertEqual(refreshed_running.status, RunStatus.CANCELLED.value)
            self.assertEqual(refreshed_stored.status, RunStatus.STORED.value)

            cancelled_job = session.exec(
                select(QueueJob).where(QueueJob.run_id == running_run.id)
            ).first()
            self.assertIsNotNone(cancelled_job)
            self.assertEqual(cancelled_job.status, QueueJobStatus.CANCELLED.value)

            lock = session.exec(
                select(ActiveSourceLock).where(ActiveSourceLock.run_id == running_run.id)
            ).first()
            self.assertIsNone(lock)

            refreshed_batch = session.exec(
                select(BatchRun).where(BatchRun.batch_id == batch_id)
            ).first()
            self.assertIsNotNone(refreshed_batch)
            self.assertEqual(refreshed_batch.completed, 1)
            self.assertEqual(refreshed_batch.failed, 1)
            self.assertEqual(refreshed_batch.status, BatchStatus.PARTIAL.value)

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
