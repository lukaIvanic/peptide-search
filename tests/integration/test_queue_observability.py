import unittest

from support import ApiIntegrationTestCase


class QueueHealthEndpointTests(ApiIntegrationTestCase):
    def test_queue_health_returns_diagnostics_snapshot(self) -> None:
        response = self.client.get("/api/queue/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(payload.get("status"), {"ok", "degraded"})
        self.assertIn("db_ok", payload)
        self.assertIsInstance(payload["db_ok"], bool)
        queue = payload.get("queue")
        self.assertIsInstance(queue, dict)

        expected_keys = {
            "queued_jobs",
            "claimed_jobs",
            "stale_claimed_jobs",
            "failed_jobs",
            "cancelled_jobs",
            "done_jobs",
            "active_source_locks",
            "running",
            "configured_concurrency",
            "worker_tasks",
            "active_claims",
            "claim_timeout_seconds",
            "claim_heartbeat_seconds",
            "recovery_interval_seconds",
            "shard_count",
            "shard_id",
        }
        self.assertTrue(expected_keys.issubset(set(queue.keys())))
        self.assertEqual(queue["shard_count"], 1)
        self.assertEqual(queue["shard_id"], 0)


class QueueHealthEndpointShardConfigTests(ApiIntegrationTestCase):
    settings_overrides = {"QUEUE_SHARD_COUNT": 4, "QUEUE_SHARD_ID": 2}

    def test_queue_health_reflects_shard_configuration(self) -> None:
        response = self.client.get("/api/queue/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        queue = payload.get("queue", {})
        self.assertEqual(queue.get("shard_count"), 4)
        self.assertEqual(queue.get("shard_id"), 2)


if __name__ == "__main__":
    unittest.main()
