import asyncio
import json
import unittest
from unittest.mock import patch

from sqlmodel import Session, select

from app.persistence.models import ExtractionEntity, QueueJob, QueueJobStatus, RunStatus
from app.services.extraction_service import run_queued_extraction
from app.services.queue_errors import RunCancelledError
from support import ApiIntegrationTestCase


class QueueClaimGuardTests(ApiIntegrationTestCase):
    @staticmethod
    def _cached_payload_json(*, entity_count: int) -> str:
        entities = []
        for idx in range(entity_count):
            entities.append(
                {
                    "type": "peptide",
                    "peptide": {
                        "sequence_one_letter": f"PEPTIDE{idx}",
                        "is_hydrogel": True,
                    },
                    "labels": [],
                    "morphology": [],
                    "validation_methods": [],
                    "reported_characteristics": [],
                }
            )
        return json.dumps(
            {
                "paper": {
                    "title": "Cached Replay Paper",
                    "doi": "10.1000/cached-replay",
                    "url": "https://example.org/cached-replay.pdf",
                    "source": "test",
                    "authors": [],
                },
                "entities": entities,
                "comment": "cached-result",
            }
        )

    def test_run_queued_extraction_rejects_lost_claim(self) -> None:
        paper_id = self.create_paper(
            title="Claim Guard",
            doi="10.1000/claim-guard",
            url="https://example.org/claim-guard",
        )
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/claim-guard.pdf",
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="correct-token",
            claimed_by="worker-test",
        )

        with self.assertRaises(RunCancelledError):
            asyncio.run(
                run_queued_extraction(
                    run_id=run.id,
                    paper_id=paper_id,
                    pdf_url=run.pdf_url or "",
                    provider="mock",
                    model="mock-model",
                    claim_job_id=job_id,
                    claim_token="wrong-token",
                )
            )

        with Session(self.db_module.engine) as session:
            refreshed_run = session.get(type(run), run.id)
            job = session.get(QueueJob, job_id)
            self.assertIsNotNone(refreshed_run)
            self.assertEqual(refreshed_run.status, RunStatus.PROVIDER.value)
            self.assertIsNone(refreshed_run.raw_json)
            self.assertIsNotNone(job)
            self.assertEqual(job.status, QueueJobStatus.CLAIMED.value)

    def test_run_queued_extraction_allows_active_claim(self) -> None:
        paper_id = self.create_paper(
            title="Claim Guard Success",
            doi="10.1000/claim-guard-ok",
            url="https://example.org/claim-guard-ok",
        )
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/claim-guard-ok.pdf",
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="active-token",
            claimed_by="worker-test",
        )

        result = asyncio.run(
            run_queued_extraction(
                run_id=run.id,
                paper_id=paper_id,
                pdf_url=run.pdf_url or "",
                provider="mock",
                model="mock-model",
                claim_job_id=job_id,
                claim_token="active-token",
            )
        )
        self.assertEqual(result["run_id"], run.id)

        with Session(self.db_module.engine) as session:
            refreshed_run = session.get(type(run), run.id)
            self.assertIsNotNone(refreshed_run)
            self.assertIsNotNone(refreshed_run.raw_json)

    def test_run_queued_extraction_replay_replaces_entities(self) -> None:
        paper_id = self.create_paper(
            title="Claim Guard Replay",
            doi="10.1000/claim-guard-replay",
            url="https://example.org/claim-guard-replay",
        )
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/claim-guard-replay.pdf",
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="replay-token",
            claimed_by="worker-replay",
        )

        first = asyncio.run(
            run_queued_extraction(
                run_id=run.id,
                paper_id=paper_id,
                pdf_url=run.pdf_url or "",
                provider="mock",
                model="mock-model",
                claim_job_id=job_id,
                claim_token="replay-token",
            )
        )
        second = asyncio.run(
            run_queued_extraction(
                run_id=run.id,
                paper_id=paper_id,
                pdf_url=run.pdf_url or "",
                provider="mock",
                model="mock-model",
                claim_job_id=job_id,
                claim_token="replay-token",
            )
        )
        self.assertEqual(first["run_id"], run.id)
        self.assertEqual(second["run_id"], run.id)

        with Session(self.db_module.engine) as session:
            entity_rows = session.exec(
                select(ExtractionEntity).where(ExtractionEntity.run_id == run.id)
            ).all()
            self.assertEqual(len(entity_rows), 1)

    def test_run_queued_extraction_replay_skips_provider_for_zero_entity_payload(self) -> None:
        paper_id = self.create_paper(
            title="Claim Guard Cached Zero",
            doi="10.1000/claim-guard-cached-zero",
            url="https://example.org/claim-guard-cached-zero",
        )
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/claim-guard-cached-zero.pdf",
            raw_json=self._cached_payload_json(entity_count=0),
            comment="cached-result",
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="cached-zero-token",
            claimed_by="worker-cached-zero",
        )

        with patch(
            "app.services.extraction_service.get_provider_by_name",
            side_effect=AssertionError("provider should not be called for cached replay"),
        ):
            result = asyncio.run(
                run_queued_extraction(
                    run_id=run.id,
                    paper_id=paper_id,
                    pdf_url=run.pdf_url or "",
                    provider="mock",
                    model="mock-model",
                    claim_job_id=job_id,
                    claim_token="cached-zero-token",
                )
            )

        self.assertEqual(result["run_id"], run.id)
        self.assertEqual(result["entity_count"], 0)

    def test_run_queued_extraction_replay_restores_entities_from_cached_payload(self) -> None:
        paper_id = self.create_paper(
            title="Claim Guard Cached Repair",
            doi="10.1000/claim-guard-cached-repair",
            url="https://example.org/claim-guard-cached-repair",
        )
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/claim-guard-cached-repair.pdf",
            raw_json=self._cached_payload_json(entity_count=1),
            comment="cached-result",
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="cached-repair-token",
            claimed_by="worker-cached-repair",
        )

        with patch(
            "app.services.extraction_service.get_provider_by_name",
            side_effect=AssertionError("provider should not be called for cached replay"),
        ):
            result = asyncio.run(
                run_queued_extraction(
                    run_id=run.id,
                    paper_id=paper_id,
                    pdf_url=run.pdf_url or "",
                    provider="mock",
                    model="mock-model",
                    claim_job_id=job_id,
                    claim_token="cached-repair-token",
                )
            )

        self.assertEqual(result["run_id"], run.id)
        self.assertEqual(result["entity_count"], 1)
        with Session(self.db_module.engine) as session:
            entity_rows = session.exec(
                select(ExtractionEntity).where(ExtractionEntity.run_id == run.id)
            ).all()
            self.assertEqual(len(entity_rows), 1)


if __name__ == "__main__":
    unittest.main()
