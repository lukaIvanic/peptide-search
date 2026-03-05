import unittest
from unittest.mock import AsyncMock, patch

from sqlmodel import Session, select

from app.persistence.models import (
    ActiveSourceLock,
    BaselineCaseRun,
    BatchRun,
    BatchStatus,
    ExtractionEntity,
    ExtractionRun,
    Paper,
    QueueJob,
    QueueJobStatus,
    RunStatus,
)
from support import ApiIntegrationTestCase


class ApiRunAndPaperDeleteTests(ApiIntegrationTestCase):
    def test_delete_run_subtree_removes_descendants_and_dependencies(self) -> None:
        paper_id = self.create_paper(
            title="Delete tree",
            doi="10.1000/delete-tree",
            url="https://example.org/delete-tree",
        )
        parent = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/delete-tree-parent.pdf",
        )
        child = self.create_run_row(
            paper_id=paper_id,
            parent_run_id=parent.id,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/delete-tree-child.pdf",
        )
        grandchild = self.create_run_row(
            paper_id=paper_id,
            parent_run_id=child.id,
            status=RunStatus.STORED.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/delete-tree-grandchild.pdf",
        )
        unrelated = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.STORED.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/delete-tree-unrelated.pdf",
        )

        with Session(self.db_module.engine) as session:
            session.add(ExtractionEntity(run_id=parent.id, entity_type="peptide"))
            session.add(ExtractionEntity(run_id=child.id, entity_type="peptide"))
            session.add(ExtractionEntity(run_id=grandchild.id, entity_type="peptide"))
            session.add(BaselineCaseRun(baseline_case_id="case-delete-1", run_id=child.id))
            session.commit()

        self.create_queue_job(
            run_id=parent.id,
            pdf_url="https://example.org/delete-tree-parent.pdf",
            status=QueueJobStatus.CLAIMED.value,
            claim_token="claim-delete-parent",
            claimed_by="worker-1",
        )
        self.create_queue_job(
            run_id=child.id,
            pdf_url="https://example.org/delete-tree-child.pdf",
            status=QueueJobStatus.QUEUED.value,
        )
        self.create_source_lock(run_id=parent.id, source_url="https://example.org/delete-tree-parent.pdf")
        self.create_source_lock(run_id=child.id, source_url="https://example.org/delete-tree-child.pdf")

        response = self.client.delete(f"/api/runs/{parent.id}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["deleted_runs"], 3)
        self.assertEqual(payload["deleted_entities"], 3)
        self.assertEqual(payload["deleted_queue_jobs"], 2)
        self.assertEqual(payload["deleted_source_locks"], 2)
        self.assertEqual(payload["deleted_case_links"], 1)

        with Session(self.db_module.engine) as session:
            self.assertIsNone(session.get(ExtractionRun, parent.id))
            self.assertIsNone(session.get(ExtractionRun, child.id))
            self.assertIsNone(session.get(ExtractionRun, grandchild.id))
            self.assertIsNotNone(session.get(ExtractionRun, unrelated.id))
            self.assertIsNotNone(session.get(Paper, paper_id))
            self.assertIsNone(session.exec(select(QueueJob).where(QueueJob.run_id == parent.id)).first())
            self.assertIsNone(session.exec(select(QueueJob).where(QueueJob.run_id == child.id)).first())
            self.assertIsNone(session.exec(select(ActiveSourceLock).where(ActiveSourceLock.run_id == parent.id)).first())
            self.assertIsNone(session.exec(select(BaselineCaseRun).where(BaselineCaseRun.run_id == child.id)).first())

    def test_delete_run_missing_returns_not_found(self) -> None:
        response = self.client.delete("/api/runs/999999")
        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_delete_paper_removes_paper_and_associated_runs(self) -> None:
        paper_id = self.create_paper(
            title="Delete paper",
            doi="10.1000/delete-paper",
            url="https://example.org/delete-paper",
        )
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/delete-paper-run.pdf",
        )
        child = self.create_run_row(
            paper_id=paper_id,
            parent_run_id=run.id,
            status=RunStatus.FAILED.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/delete-paper-child.pdf",
        )
        keep_paper_id = self.create_paper(
            title="Keep paper",
            doi="10.1000/keep-paper",
            url="https://example.org/keep-paper",
        )
        keep_run = self.create_run_row(
            paper_id=keep_paper_id,
            status=RunStatus.STORED.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/keep-paper.pdf",
        )

        with Session(self.db_module.engine) as session:
            session.add(ExtractionEntity(run_id=run.id, entity_type="peptide"))
            session.add(ExtractionEntity(run_id=child.id, entity_type="peptide"))
            session.add(BaselineCaseRun(baseline_case_id="case-delete-paper", run_id=run.id))
            session.commit()

        self.create_queue_job(
            run_id=run.id,
            pdf_url="https://example.org/delete-paper-run.pdf",
            status=QueueJobStatus.CLAIMED.value,
            claim_token="claim-delete-paper",
            claimed_by="worker-2",
        )
        self.create_source_lock(run_id=run.id, source_url="https://example.org/delete-paper-run.pdf")

        response = self.client.delete(f"/api/papers/{paper_id}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["paper_id"], paper_id)
        self.assertEqual(payload["deleted_runs"], 2)
        self.assertEqual(payload["deleted_entities"], 2)
        self.assertEqual(payload["deleted_queue_jobs"], 1)
        self.assertEqual(payload["deleted_source_locks"], 1)
        self.assertEqual(payload["deleted_case_links"], 1)

        with Session(self.db_module.engine) as session:
            self.assertIsNone(session.get(Paper, paper_id))
            self.assertIsNone(session.get(ExtractionRun, run.id))
            self.assertIsNone(session.get(ExtractionRun, child.id))
            self.assertIsNotNone(session.get(Paper, keep_paper_id))
            self.assertIsNotNone(session.get(ExtractionRun, keep_run.id))

    def test_delete_paper_missing_returns_not_found(self) -> None:
        response = self.client.delete("/api/papers/999999")
        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_delete_run_with_claimed_job_removes_queue_artifacts(self) -> None:
        paper_id = self.create_paper(
            title="Delete claimed run",
            doi="10.1000/delete-claimed",
            url="https://example.org/delete-claimed",
        )
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/delete-claimed.pdf",
        )
        self.create_queue_job(
            run_id=run.id,
            pdf_url="https://example.org/delete-claimed.pdf",
            status=QueueJobStatus.CLAIMED.value,
            claim_token="claim-delete-claimed",
            claimed_by="worker-3",
        )
        self.create_source_lock(run_id=run.id, source_url="https://example.org/delete-claimed.pdf")

        response = self.client.delete(f"/api/runs/{run.id}")
        self.assertEqual(response.status_code, 200)

        with Session(self.db_module.engine) as session:
            self.assertIsNone(session.get(ExtractionRun, run.id))
            self.assertIsNone(session.exec(select(QueueJob).where(QueueJob.run_id == run.id)).first())
            self.assertIsNone(session.exec(select(ActiveSourceLock).where(ActiveSourceLock.run_id == run.id)).first())

    def test_delete_batch_linked_run_marks_batch_stale(self) -> None:
        batch_id = "delete_batch_stale"
        paper_id = self.create_paper(
            title="Delete batch run",
            doi="10.1000/delete-batch-run",
            url="https://example.org/delete-batch-run",
        )
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/delete-batch-run.pdf",
            batch_id=batch_id,
        )

        with Session(self.db_module.engine) as session:
            session.add(
                BatchRun(
                    batch_id=batch_id,
                    label="Delete batch run",
                    dataset="self_assembly",
                    model_provider="mock",
                    model_name="mock-model",
                    status=BatchStatus.RUNNING.value,
                    total_papers=1,
                    completed=0,
                    failed=0,
                    metrics_stale=False,
                )
            )
            session.commit()

        with patch("app.services.baseline_recompute_service._schedule_recompute", new=AsyncMock()) as mocked_schedule:
            response = self.client.delete(f"/api/runs/{run.id}")
            self.assertEqual(response.status_code, 200)
            mocked_schedule.assert_awaited()

        with Session(self.db_module.engine) as session:
            batch = session.exec(select(BatchRun).where(BatchRun.batch_id == batch_id)).first()
            self.assertIsNotNone(batch)
            self.assertTrue(batch.metrics_stale)


if __name__ == "__main__":
    unittest.main()
