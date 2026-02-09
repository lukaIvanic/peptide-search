import unittest
from unittest.mock import AsyncMock, patch

from sqlmodel import Session, select

from app.baseline.loader import list_cases
from app.persistence.models import BaselineCaseRun, BatchRun, BatchStatus, ExtractionRun, RunStatus
from app.schemas import SearchItem
from support import ApiIntegrationTestCase


class ApiQueueAndBaselineRetryTests(ApiIntegrationTestCase):
    def first_case(self) -> dict:
        cases = list_cases()
        self.assertGreater(len(cases), 0)
        return cases[0]

    def first_case_id(self) -> str:
        return self.first_case()["id"]

    def assert_error(
        self,
        response,
        *,
        status_code: int,
        code: str,
        message_contains: str,
    ) -> None:
        self.assertEqual(response.status_code, status_code)
        body = response.json()
        self.assertEqual(body["error"]["code"], code)
        self.assertIn(message_contains, body["error"]["message"])

    def test_retry_failed_runs_api_transitions_to_queued(self) -> None:
        paper_id = self.create_paper(doi="10.1000/test-queue", url="https://example.org/queue")
        run_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider error: timeout",
            model_provider="mock",
            pdf_url="https://example.org/queue.pdf",
        )

        response = self.client.post(
            "/api/runs/failures/retry",
            json={
                "days": 30,
                "limit": 10,
                "max_runs": 1000,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["requested"], 1)
        self.assertEqual(payload["enqueued"], 1)
        self.assertEqual(payload["skipped"], 0)

        with Session(self.db_module.engine) as session:
            updated = session.get(ExtractionRun, run_id)
            self.assertIsNotNone(updated)
            self.assertEqual(updated.status, RunStatus.QUEUED.value)
            self.assertIsNone(updated.failure_reason)

    def test_baseline_case_retry_requeues_once_and_then_deduplicates(self) -> None:
        case = self.first_case()
        case_id = case["id"]
        source_url = "https://example.org/baseline-case.pdf"

        paper_id = self.create_paper(doi=case.get("doi"), url=case.get("paper_url"))
        with Session(self.db_module.engine) as session:
            failed_run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.FAILED.value,
                failure_reason="provider error: empty",
                model_provider="mock",
                pdf_url=source_url,
            )
            session.add(failed_run)
            session.commit()
            session.refresh(failed_run)
            session.add(BaselineCaseRun(baseline_case_id=case_id, run_id=failed_run.id))
            session.commit()

        first = self.client.post(
            f"/api/baseline/cases/{case_id}/retry",
            json={"source_url": source_url, "provider": "mock"},
        )
        self.assertEqual(first.status_code, 200)
        first_payload = first.json()
        self.assertEqual(first_payload["status"], RunStatus.QUEUED.value)
        self.assertEqual(first_payload["message"], "Baseline case re-queued for processing")

        second = self.client.post(
            f"/api/baseline/cases/{case_id}/retry",
            json={"source_url": source_url, "provider": "mock"},
        )
        self.assertEqual(second.status_code, 200)
        second_payload = second.json()
        self.assertEqual(second_payload["message"], "Baseline case already queued for processing")

        with Session(self.db_module.engine) as session:
            runs = session.exec(
                select(ExtractionRun)
                .where(ExtractionRun.pdf_url == source_url)
                .order_by(ExtractionRun.created_at.asc())
            ).all()
            self.assertEqual(len(runs), 2)
            self.assertEqual(runs[-1].status, RunStatus.QUEUED.value)

    def test_baseline_batch_retry_requeues_failed_runs(self) -> None:
        batch_id = "batch_retry_test"
        paper_id = self.create_paper(doi="10.1000/batch", url="https://example.org/batch")

        with Session(self.db_module.engine) as session:
            batch = BatchRun(
                batch_id=batch_id,
                label="Retry batch",
                dataset="self_assembly",
                model_provider="mock",
                model_name="mock-model",
                status=BatchStatus.FAILED.value,
                total_papers=1,
                completed=0,
                failed=1,
            )
            session.add(batch)
            run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.FAILED.value,
                failure_reason="provider error: temp",
                model_provider="mock",
                pdf_url="https://example.org/batch.pdf",
                batch_id=batch_id,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id

        response = self.client.post(
            "/api/baseline/batch-retry",
            json={"batch_id": batch_id, "provider": "mock"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["batch_id"], batch_id)
        self.assertEqual(payload["retried"], 1)
        self.assertEqual(payload["skipped"], 0)

        with Session(self.db_module.engine) as session:
            updated_run = session.get(ExtractionRun, run_id)
            self.assertEqual(updated_run.status, RunStatus.QUEUED.value)
            self.assertIsNone(updated_run.failure_reason)

            batch = session.exec(select(BatchRun).where(BatchRun.batch_id == batch_id)).first()
            self.assertEqual(batch.status, BatchStatus.RUNNING.value)
            self.assertEqual(batch.failed, 0)

    def test_retry_failed_runs_api_applies_filters_and_limit_boundary(self) -> None:
        paper_a = self.create_paper(
            title="Provider fail",
            doi="10.1000/filter-a",
            url="https://example.org/filter-a",
            source="pmc",
        )
        run_a = self.create_run(
            paper_id=paper_a,
            status=RunStatus.FAILED.value,
            failure_reason="provider error: timeout",
            model_provider="mock",
            pdf_url="https://example.org/filter-a.pdf",
        )
        paper_c = self.create_paper(
            title="Provider fail second",
            doi="10.1000/filter-c",
            url="https://example.org/filter-c",
            source="pmc",
        )
        run_c = self.create_run(
            paper_id=paper_c,
            status=RunStatus.FAILED.value,
            failure_reason="provider error: retry me",
            model_provider="mock",
            pdf_url="https://example.org/filter-c.pdf",
        )
        paper_b = self.create_paper(
            title="Validation fail",
            doi="10.1000/filter-b",
            url="https://example.org/filter-b",
            source="arxiv",
        )
        self.create_run(
            paper_id=paper_b,
            status=RunStatus.FAILED.value,
            failure_reason="parse/validation error: bad schema",
            model_provider="openai",
            pdf_url="https://example.org/filter-b.pdf",
        )

        response = self.client.post(
            "/api/runs/failures/retry",
            json={
                "days": 30,
                "limit": 1,
                "max_runs": 10,
                "bucket": "provider",
                "provider": "mock",
                "source": "pmc",
                "reason": "Provider error",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["requested"], 1)
        self.assertEqual(payload["enqueued"], 1)
        self.assertEqual(payload["skipped"], 0)

        with Session(self.db_module.engine) as session:
            statuses = {
                run_a: session.get(ExtractionRun, run_a).status,
                run_c: session.get(ExtractionRun, run_c).status,
            }
            self.assertIn(RunStatus.QUEUED.value, statuses.values())
            self.assertIn(RunStatus.FAILED.value, statuses.values())
            updated_b = session.exec(
                select(ExtractionRun).where(ExtractionRun.paper_id == paper_b)
            ).first()
            self.assertEqual(updated_b.status, RunStatus.FAILED.value)

    def test_retry_failed_runs_api_honors_max_runs_boundary(self) -> None:
        paper_a = self.create_paper(
            title="Provider max runs A",
            doi="10.1000/max-runs-a",
            url="https://example.org/max-runs-a",
            source="pmc",
        )
        run_a = self.create_run(
            paper_id=paper_a,
            status=RunStatus.FAILED.value,
            failure_reason="provider error: timeout",
            model_provider="mock",
            pdf_url="https://example.org/max-runs-a.pdf",
        )
        paper_b = self.create_paper(
            title="Provider max runs B",
            doi="10.1000/max-runs-b",
            url="https://example.org/max-runs-b",
            source="pmc",
        )
        run_b = self.create_run(
            paper_id=paper_b,
            status=RunStatus.FAILED.value,
            failure_reason="provider error: timeout",
            model_provider="mock",
            pdf_url="https://example.org/max-runs-b.pdf",
        )

        response = self.client.post(
            "/api/runs/failures/retry",
            json={
                "days": 30,
                "limit": 10,
                "max_runs": 1,
                "bucket": "provider",
                "provider": "mock",
                "source": "pmc",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["requested"], 1)
        self.assertEqual(payload["enqueued"], 1)
        self.assertEqual(payload["skipped"], 0)

        with Session(self.db_module.engine) as session:
            statuses = {
                run_a: session.get(ExtractionRun, run_a).status,
                run_b: session.get(ExtractionRun, run_b).status,
            }
            self.assertIn(RunStatus.QUEUED.value, statuses.values())
            self.assertIn(RunStatus.FAILED.value, statuses.values())

    def test_retry_failed_runs_api_reconciles_skips_for_missing_pdf(self) -> None:
        paper_id = self.create_paper(doi="10.1000/missing-pdf", url="https://example.org/missing-pdf")
        self.create_run(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider error: timeout",
            model_provider="mock",
            pdf_url=None,
        )

        response = self.client.post(
            "/api/runs/failures/retry",
            json={"days": 30, "limit": 10, "max_runs": 1000},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["requested"], 1)
        self.assertEqual(payload["enqueued"], 0)
        self.assertEqual(payload["skipped"], 1)
        self.assertEqual(payload["skipped_missing_pdf"], 1)

    def test_retry_baseline_case_nonexistent_case_returns_not_found(self) -> None:
        response = self.client.post(
            "/api/baseline/cases/does-not-exist/retry",
            json={"provider": "mock"},
        )
        self.assert_error(
            response,
            status_code=404,
            code="not_found",
            message_contains="Baseline case not found",
        )

    def test_retry_baseline_case_unresolved_source_returns_bad_request(self) -> None:
        case_id = self.first_case_id()
        with patch(
            "app.services.baseline_retry_service.resolve_baseline_source",
            new=AsyncMock(return_value=None),
        ):
            response = self.client.post(
                f"/api/baseline/cases/{case_id}/retry",
                json={"provider": "mock"},
            )
        self.assert_error(
            response,
            status_code=400,
            code="bad_request",
            message_contains="No source URL resolved",
        )

    def test_retry_baseline_case_links_related_cases_by_shared_source_keys(self) -> None:
        shared_case_id = "case-shared-1"
        related_case_id = "case-shared-2"
        fake_cases = [
            {
                "id": shared_case_id,
                "dataset": "self_assembly",
                "sequence": "AAAA",
                "doi": "10.1000/shared",
                "paper_url": "https://example.org/shared",
                "pdf_url": None,
                "labels": [],
                "metadata": {},
            },
            {
                "id": related_case_id,
                "dataset": "self_assembly",
                "sequence": "BBBB",
                "doi": "10.1000/shared",
                "paper_url": "https://example.org/shared-2",
                "pdf_url": None,
                "labels": [],
                "metadata": {},
            },
        ]

        with patch("app.services.baseline_retry_service.get_case", return_value=fake_cases[0]), patch(
            "app.services.baseline_retry_service.list_cases", return_value=fake_cases
        ), patch(
            "app.services.baseline_retry_service.resolve_baseline_source",
            new=AsyncMock(
                return_value=SearchItem(
                    title="Shared source",
                    doi="10.1000/shared",
                    url="https://example.org/shared",
                    pdf_url="https://example.org/shared.pdf",
                    source="pmc",
                    year=2024,
                    authors=[],
                )
            ),
        ):
            response = self.client.post(
                f"/api/baseline/cases/{shared_case_id}/retry",
                json={"provider": "mock"},
            )

        self.assertEqual(response.status_code, 200)
        run_id = response.json()["id"]
        with Session(self.db_module.engine) as session:
            links = session.exec(
                select(BaselineCaseRun.baseline_case_id)
                .where(BaselineCaseRun.run_id == run_id)
                .order_by(BaselineCaseRun.baseline_case_id.asc())
            ).all()
            self.assertEqual(links, [shared_case_id, related_case_id])

    def test_batch_retry_remaps_upload_source_and_skips_missing_pdf(self) -> None:
        case_id = self.first_case_id()
        batch_id = "batch_retry_mixed"
        paper_id = self.create_paper(doi="10.1000/batch-mixed", url="https://example.org/batch-mixed")

        with Session(self.db_module.engine) as session:
            batch = BatchRun(
                batch_id=batch_id,
                label="Retry mixed batch",
                dataset="self_assembly",
                model_provider="mock",
                model_name="mock-model",
                status=BatchStatus.FAILED.value,
                total_papers=2,
                completed=0,
                failed=2,
            )
            session.add(batch)
            upload_run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.FAILED.value,
                failure_reason="provider error: temp",
                model_provider="mock",
                pdf_url="upload://stale-token",
                batch_id=batch_id,
                baseline_case_id=case_id,
            )
            missing_run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.FAILED.value,
                failure_reason="provider error: temp",
                model_provider="mock",
                pdf_url=None,
                batch_id=batch_id,
            )
            session.add(upload_run)
            session.add(missing_run)
            session.commit()
            session.refresh(upload_run)
            upload_run_id = upload_run.id
            session.add(BaselineCaseRun(baseline_case_id=case_id, run_id=upload_run_id))
            session.commit()

        with patch(
            "app.services.baseline_retry_service.resolve_local_pdf_source",
            return_value=SearchItem(
                title="Local override",
                doi="10.1000/batch-mixed",
                url="https://example.org/batch-mixed",
                pdf_url="https://example.org/remapped.pdf",
                source="local",
                year=None,
                authors=[],
            ),
        ):
            response = self.client.post(
                "/api/baseline/batch-retry",
                json={"batch_id": batch_id, "provider": "mock"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["retried"], 1)
        self.assertEqual(payload["skipped"], 1)

        with Session(self.db_module.engine) as session:
            updated_upload_run = session.get(ExtractionRun, upload_run_id)
            self.assertEqual(updated_upload_run.status, RunStatus.QUEUED.value)
            self.assertEqual(updated_upload_run.pdf_url, "https://example.org/remapped.pdf")

    def test_batch_retry_keeps_failed_counter_non_negative(self) -> None:
        batch_id = "batch_retry_counter_floor"
        paper_id = self.create_paper(doi="10.1000/batch-counter", url="https://example.org/batch-counter")

        with Session(self.db_module.engine) as session:
            batch = BatchRun(
                batch_id=batch_id,
                label="Retry counter floor",
                dataset="self_assembly",
                model_provider="mock",
                model_name="mock-model",
                status=BatchStatus.RUNNING.value,
                total_papers=1,
                completed=0,
                failed=0,
            )
            session.add(batch)
            run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.FAILED.value,
                failure_reason="provider error: temp",
                model_provider="mock",
                pdf_url="https://example.org/batch-counter.pdf",
                batch_id=batch_id,
            )
            session.add(run)
            session.commit()

        response = self.client.post(
            "/api/baseline/batch-retry",
            json={"batch_id": batch_id, "provider": "mock"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["retried"], 1)

        with Session(self.db_module.engine) as session:
            batch = session.exec(select(BatchRun).where(BatchRun.batch_id == batch_id)).first()
            self.assertEqual(batch.failed, 0)
            self.assertEqual(batch.status, BatchStatus.RUNNING.value)


if __name__ == "__main__":
    unittest.main()
