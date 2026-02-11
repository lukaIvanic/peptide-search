import asyncio
import os
import random
import time
import unittest
from datetime import timedelta

from sqlalchemy import delete
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
from app.services.queue_coordinator import QueueCoordinator
from app.services.queue_service import ExtractionQueue
from app.services.runtime_maintenance import reconcile_orphan_run_states
from app.time_utils import utc_now
from queue_invariant_helpers import assert_queue_invariants
from support import ApiIntegrationTestCase


def _deep_enabled() -> bool:
    return os.getenv("RUN_QUEUE_RELIABILITY_DEEP", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@unittest.skipUnless(
    _deep_enabled(),
    "Deep randomized queue reliability tests are disabled. Set RUN_QUEUE_RELIABILITY_DEEP=1.",
)
class QueueRandomizedWorkflowTests(ApiIntegrationTestCase):
    settings_overrides = {
        "QUEUE_CLAIM_HEARTBEAT_SECONDS": 1,
        "QUEUE_CLAIM_TIMEOUT_SECONDS": 3,
    }

    _nonce_counter = 0

    @classmethod
    def _next_nonce(cls) -> int:
        cls._nonce_counter += 1
        return cls._nonce_counter

    def _assert_invariants(self, context: str) -> None:
        assert_queue_invariants(self, self.db_module.engine, context=context)

    @staticmethod
    def _int_env(name: str, default: int) -> int:
        raw = os.getenv(name)
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            return default
        return max(1, value)

    @staticmethod
    def _seed_list_env() -> list[int]:
        raw = os.getenv("RELIABILITY_RANDOM_SEEDS", "11,29,47,73,101")
        seeds: list[int] = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                seeds.append(int(token))
            except ValueError:
                continue
        return seeds or [11, 29, 47, 73, 101]

    @staticmethod
    def _float_env(name: str, default: float) -> float:
        raw = os.getenv(name)
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            return default
        return max(0.0, value)

    def _reset_scenario_state(self) -> None:
        with Session(self.db_module.engine) as session:
            session.exec(delete(ActiveSourceLock))
            session.exec(delete(QueueJob))
            session.exec(delete(BaselineCaseRun))
            session.exec(delete(ExtractionEntity))
            session.exec(delete(ExtractionRun))
            session.exec(delete(BatchRun))
            session.exec(delete(Paper))
            session.commit()

    def _ensure_batch_fixture(self, rng: random.Random, seed: int, scenario: int) -> str:
        with Session(self.db_module.engine) as session:
            existing = session.exec(select(BatchRun).order_by(BatchRun.id.asc())).first()
            if existing:
                return existing.batch_id

            batch_id = f"randq_{seed}_{scenario}_{rng.randint(1000, 9999)}"
            batch = BatchRun(
                batch_id=batch_id,
                label=f"Randomized {batch_id}",
                dataset="self_assembly",
                model_provider="mock",
                model_name="mock-model",
                status=BatchStatus.RUNNING.value,
                total_papers=3,
                completed=0,
                failed=1,
            )
            session.add(batch)
            session.commit()

        failed_batch_run = self.create_run_row(
            paper_id=self.create_paper(title=f"{batch_id} failed batch"),
            status=RunStatus.FAILED.value,
            failure_reason="seeded failure",
            model_provider="mock",
            model_name="mock-model",
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            pdf_url=f"https://example.org/{batch_id}-failed-batch.pdf",
        )

        queued_run = self.create_run_row(
            paper_id=self.create_paper(title=f"{batch_id} queued"),
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            model_name="mock-model",
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            pdf_url=f"https://example.org/{batch_id}-queued.pdf",
        )
        self.create_queue_job(
            run_id=queued_run.id,
            pdf_url=queued_run.pdf_url,
            status=QueueJobStatus.QUEUED.value,
        )
        self.create_source_lock(run_id=queued_run.id, source_url=queued_run.pdf_url)

        claimed_run = self.create_run_row(
            paper_id=self.create_paper(title=f"{batch_id} claimed"),
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            pdf_url=f"https://example.org/{batch_id}-claimed.pdf",
        )
        self.create_queue_job(
            run_id=claimed_run.id,
            pdf_url=claimed_run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token=f"token-{batch_id}",
            claimed_by="rand-worker",
            claimed_at=utc_now(),
        )
        self.create_source_lock(run_id=claimed_run.id, source_url=claimed_run.pdf_url)

        self.create_run_row(
            paper_id=self.create_paper(title=f"{batch_id} failed standalone"),
            status=RunStatus.FAILED.value,
            failure_reason="seeded standalone failure",
            model_provider="mock",
            model_name="mock-model",
            pdf_url=f"https://example.org/{batch_id}-failed-standalone.pdf",
        )

        _ = failed_batch_run
        return batch_id

    def _ensure_standalone_failed_run(self) -> ExtractionRun:
        with Session(self.db_module.engine) as session:
            run = session.exec(
                select(ExtractionRun)
                .where(ExtractionRun.status == RunStatus.FAILED.value)
                .where(ExtractionRun.batch_id.is_(None))
                .order_by(ExtractionRun.id.asc())
            ).first()
            if run:
                return run

        return self.create_run_row(
            paper_id=self.create_paper(title="Generated standalone failed"),
            status=RunStatus.FAILED.value,
            failure_reason="generated failed run",
            model_provider="mock",
            model_name="mock-model",
            pdf_url=f"https://example.org/generated-failed-{self._next_nonce()}.pdf",
        )

    def _ensure_queued_job(self) -> None:
        with Session(self.db_module.engine) as session:
            existing = session.exec(
                select(QueueJob).where(QueueJob.status == QueueJobStatus.QUEUED.value)
            ).first()
            if existing:
                return

        coordinator = QueueCoordinator()
        with Session(self.db_module.engine) as session:
            paper = Paper(
                title="Generated queued run",
                doi=None,
                url="https://example.org/generated-queued",
                source="test",
            )
            session.add(paper)
            session.commit()
            session.refresh(paper)

            run = ExtractionRun(
                paper_id=paper.id,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                model_name="mock-model",
                pdf_url=f"https://example.org/generated-queued-{self._next_nonce()}.pdf",
            )
            coordinator.enqueue_new_run(session, run=run, title="Generated queued")

    def _action_enqueue_new_run(self, _rng: random.Random) -> str:
        coordinator = QueueCoordinator()
        with Session(self.db_module.engine) as session:
            paper = Paper(
                title="Random enqueue new",
                doi=None,
                url="https://example.org/random-enqueue-new",
                source="test",
            )
            session.add(paper)
            session.commit()
            session.refresh(paper)

            run = ExtractionRun(
                paper_id=paper.id,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                model_name="mock-model",
                pdf_url=f"https://example.org/random-enqueue-new-{self._next_nonce()}.pdf",
            )
            coordinator.enqueue_new_run(session, run=run, title="Random enqueue new")
        return "enqueue_new_run"

    def _action_enqueue_existing_run(self, _rng: random.Random) -> str:
        coordinator = QueueCoordinator()
        target = self._ensure_standalone_failed_run()
        with Session(self.db_module.engine) as session:
            run = session.get(ExtractionRun, target.id)
            paper = session.get(Paper, run.paper_id) if run and run.paper_id else None
            if run:
                coordinator.enqueue_existing_run(
                    session,
                    run=run,
                    title=(paper.title if paper else "") or "Random enqueue existing",
                    provider="mock",
                    model="mock-model",
                    pdf_url=run.pdf_url,
                    pdf_urls=None,
                )
        return "enqueue_existing_run"

    def _action_retry_failed_run_api(self, _rng: random.Random) -> str:
        target = self._ensure_standalone_failed_run()
        response = self.client.post(f"/api/runs/{target.id}/retry")
        self.assertIn(response.status_code, {200, 400, 404})
        return "retry_failed_run"

    def _action_batch_retry(self, rng: random.Random, seed: int, scenario: int) -> str:
        batch_id = self._ensure_batch_fixture(rng, seed, scenario)
        response = self.client.post(
            "/api/baseline/batch-retry",
            json={"batch_id": batch_id, "provider": "mock"},
        )
        self.assertEqual(response.status_code, 200)
        return "batch_retry"

    def _action_batch_stop(self, rng: random.Random, seed: int, scenario: int) -> str:
        batch_id = self._ensure_batch_fixture(rng, seed, scenario)
        response = self.client.post(
            "/api/baseline/batch-stop",
            json={"batch_id": batch_id},
        )
        self.assertEqual(response.status_code, 200)
        return "batch_stop"

    def _action_batch_delete(self) -> str:
        with Session(self.db_module.engine) as session:
            batch = session.exec(select(BatchRun).order_by(BatchRun.id.asc())).first()
            if not batch:
                return "batch_delete_noop"
            batch_id = batch.batch_id

        response = self.client.delete(f"/api/baseline/batch/{batch_id}")
        self.assertEqual(response.status_code, 200)
        return "batch_delete"

    def _action_stale_recovery_tick(self, _rng: random.Random) -> str:
        coordinator = QueueCoordinator()
        with Session(self.db_module.engine) as session:
            claimed_jobs = session.exec(
                select(QueueJob).where(QueueJob.status == QueueJobStatus.CLAIMED.value)
            ).all()
            for job in claimed_jobs:
                job.claimed_at = utc_now() - timedelta(minutes=10)
                session.add(job)
            session.commit()

            coordinator.recover_stale_claims(
                session,
                stale_after_seconds=0,
                max_attempts=3,
            )
        return "stale_recovery_tick"

    def _action_reconcile_orphans(self) -> str:
        reconcile_orphan_run_states()
        return "reconcile_orphans"

    def _action_fault_provider_exception(self) -> str:
        self._ensure_queued_job()
        coordinator = QueueCoordinator()
        with Session(self.db_module.engine) as session:
            claimed = coordinator.claim_next_job(session, worker_id="fault-provider-worker")
        if not claimed:
            return "fault_provider_exception_noop"

        queue = ExtractionQueue(concurrency=0)

        async def failing_callback(**_kwargs):
            raise RuntimeError("Injected provider failure")

        queue.set_extract_callback(failing_callback)
        asyncio.run(queue._process_claimed_job(claimed, "fault-provider-worker"))
        return "fault_provider_exception"

    def _action_fault_claim_loss(self) -> str:
        self._ensure_queued_job()
        coordinator = QueueCoordinator()
        with Session(self.db_module.engine) as session:
            claimed = coordinator.claim_next_job(session, worker_id="fault-claim-loss-worker")
        if not claimed:
            return "fault_claim_loss_noop"

        queue = ExtractionQueue(concurrency=0)

        async def delayed_callback(**_kwargs):
            await asyncio.sleep(1.2)
            return {"run_id": claimed.run_id, "entity_count": 0}

        queue.set_extract_callback(delayed_callback)

        original_heartbeat = queue.coordinator.heartbeat_claim

        def reject_heartbeat(*_args, **_kwargs):
            return False

        queue._running = True
        queue.coordinator.heartbeat_claim = reject_heartbeat
        try:
            asyncio.run(queue._process_claimed_job(claimed, "fault-claim-loss-worker"))
        finally:
            queue._running = False
            queue.coordinator.heartbeat_claim = original_heartbeat

        return "fault_claim_loss"

    def test_seeded_randomized_queue_workflows(self) -> None:
        seeds = self._seed_list_env()
        steps = self._int_env("RELIABILITY_RANDOM_STEPS", 40)
        scenarios = self._int_env("RELIABILITY_RANDOM_SCENARIOS", 50)
        step_delay_s = self._float_env("RELIABILITY_RANDOM_STEP_DELAY_SECONDS", 0.02)
        scenario_cooldown_s = self._float_env(
            "RELIABILITY_RANDOM_SCENARIO_COOLDOWN_SECONDS",
            0.25,
        )

        for seed in seeds:
            rng = random.Random(seed)
            for scenario in range(scenarios):
                self._reset_scenario_state()
                self._ensure_batch_fixture(rng, seed, scenario)
                self._assert_invariants(f"seed={seed} scenario={scenario} step=bootstrap")

                for step in range(steps):
                    action = rng.choice(
                        [
                            lambda: self._action_enqueue_new_run(rng),
                            lambda: self._action_enqueue_existing_run(rng),
                            lambda: self._action_retry_failed_run_api(rng),
                            lambda: self._action_batch_retry(rng, seed, scenario),
                            lambda: self._action_batch_stop(rng, seed, scenario),
                            self._action_batch_delete,
                            lambda: self._action_stale_recovery_tick(rng),
                            self._action_reconcile_orphans,
                            self._action_fault_provider_exception,
                            self._action_fault_claim_loss,
                        ]
                    )
                    action_name = action()
                    context = f"seed={seed} scenario={scenario} step={step} action={action_name}"
                    self._assert_invariants(context)
                    if step_delay_s > 0:
                        time.sleep(step_delay_s)
                if scenario_cooldown_s > 0:
                    time.sleep(scenario_cooldown_s)


if __name__ == "__main__":
    unittest.main()
