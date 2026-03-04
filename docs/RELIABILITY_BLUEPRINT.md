# Reliability Blueprint (Queue + Baseline Runtime)

## 1) Goal

Build a production-reliable extraction system for small-team scale (10+ active users) where:

1. Queue lifecycle is resilient to crashes, retries, stale workers, and partial provider failures.
2. Existing historical results remain readable even if new runs fail.
3. Deploy/restart/migrate paths are deterministic and reversible.
4. Reliability behavior is proven by repeatable automated tests.

## 2) Reliability Contract (Current Product Scope)

1. Delivery semantics: **at-least-once**, not exactly-once.
2. Safety target: **no corruption, no stuck transient runs, no unrecoverable queue claims**.
3. Recovery target: crashes/restarts reconcile orphan states on boot.
4. UI target: historical evaluation pages remain functional under partial runtime failures.

## 3) Current Architecture (Implemented)

1. Persistent queue (`queue_job`) with claim token, heartbeat lease, stale-claim recovery, and bounded attempts.
2. Source-level dedupe lock (`active_source_lock`) to avoid duplicate active work per source.
3. Restart reconciliation (`reconcile_orphan_run_states`) to resolve transient runs with missing/inconsistent jobs.
4. Deterministic queue tests + randomized/fault-injection reliability suites.
5. Resource-safe runner for deep reliability loops (`scripts/run_queue_reliability_safe.sh`).

## 4) End Goals and Exit Criteria

Current completion gate for this cycle: **G1-G5 must be done and test evidence green**.

### G1. Deterministic Claim Correctness (P0)

Exit criteria:

1. Single claim ownership under concurrency.
2. Claim lease heartbeat rejection on token loss.
3. Stale claims requeued/failed according to max attempts.
4. No queue-state invariant violations in deterministic and randomized suites.

Status: **Done**

### G2. Postgres-Grade Claim Path (P0)

Exit criteria:

1. Postgres uses transactional claim with `FOR UPDATE SKIP LOCKED`.
2. Claim order is stable by `available_at, id`.
3. Claim path has supporting composite index for status + availability ordering.

Status: **Done**

### G3. Logical Queue Sharding for Horizontal Workers (P1)

Exit criteria:

1. Deterministic shard partitioning by `run_id % shard_count`.
2. Worker instances can claim only their shard.
3. Invalid shard configs fail fast.

Status: **Done**

### G4. Operational Guardrails (P1)

Exit criteria:

1. Smoke gate always runs before deep in default profile.
2. Deep run can be skipped under high load.
3. Deep suites have hard timeouts and reproducible seed/step controls.
4. Machine-readable report emitted for each run.

Status: **Done**

### G5. Postgres Contract Proof (P1)

Exit criteria:

1. Optional gated suite validates connectivity, schema head, app startup.
2. Optional gated suite validates Postgres claim path behavior.

Status: **Done** (when `TEST_POSTGRES_URL` is provided)

### G6. Observability Expansion (P2, Next Cycle)

Exit criteria:

1. Health checks include DB reachability.
2. Queue logs include claim/recovery/failure transitions.
3. Reliability runs produce persistent report artifacts.

Status: **Planned**

Open work:

1. Queue counters/latency metrics export (Prometheus or OpenTelemetry metrics).
2. Alert thresholds for stalled queue depth and repeated stale-claim failures.

### G7. Idempotent Side-Effects Boundary (P2, Next Cycle)

Exit criteria:

1. External-provider side effects and DB commit boundary are explicitly idempotent.
2. Replays do not duplicate durable extraction results.

Status: **Planned**

Open work:

1. Add idempotency key strategy at provider call/result write boundary.
2. Add replay tests for duplicate-delivery safety.

## 5) Required Test Evidence

Run all of the following before calling reliability changes complete for a PR:

1. `./scripts/test_local_reliability.sh`
2. `RELIABILITY_REPORT_PATH=/tmp/queue_reliability_report.json ./scripts/run_queue_reliability_safe.sh all`
3. Optional Postgres contracts:
   1. `TEST_POSTGRES_URL='postgresql://...' .venv/bin/python -m unittest discover -s tests/integration -p 'test_postgres_contracts.py'`

Expected:

1. Unit + integration + API smoke all green.
2. Queue smoke + deterministic + API-sequence + randomized all green.
3. No invariant failure output.

## 6) Execution Loop

Use this loop until all end goals are complete:

1. Pick highest-priority incomplete goal (lowest `P` number).
2. Implement smallest safe change that advances the goal.
3. Add tests that fail before and pass after.
4. Run required test evidence.
5. Update this blueprint status lines.
6. Only then move to next goal.

## 7) Current Reliability Snapshot

At the time of this document update:

1. `test_local_reliability.sh`: passing.
2. `run_queue_reliability_safe.sh all`: passing with deep randomized sweep.
3. Latest deep report: `/tmp/queue_reliability_all_after_shard_report.json` (`smoke=0`, `deep=0`, `timeout=false`).
4. Skip behavior in baseline integration runs is intentional (deep + Postgres gated unless env enabled).

## 8) External References (Primary Sources)

1. PostgreSQL locking and `SKIP LOCKED`: https://www.postgresql.org/docs/current/sql-select.html
2. PostgreSQL explicit locking behavior: https://www.postgresql.org/docs/current/explicit-locking.html
3. PostgreSQL transaction isolation: https://www.postgresql.org/docs/current/transaction-iso.html
4. PostgreSQL partial indexes (for queue access paths): https://www.postgresql.org/docs/current/indexes-partial.html
5. Stripe API idempotent requests: https://docs.stripe.com/api/idempotent_requests
6. AWS SQS at-least-once delivery: https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues-at-least-once-delivery.html
7. AWS SQS visibility timeout model: https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html
8. Google SRE workbook monitoring/alerting framing: https://sre.google/workbook/monitoring/
