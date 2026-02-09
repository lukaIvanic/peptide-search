import unittest
from datetime import timedelta

from app.persistence.models import BatchRun
from app.services.batch_metrics import (
    compute_batch_cost,
    compute_match_rate,
    compute_wall_clock_time_ms,
    generate_batch_id,
    get_model_name_for_provider,
)
from app.time_utils import utc_now


class BatchMetricsTests(unittest.TestCase):
    def test_get_model_name_for_provider(self) -> None:
        self.assertTrue(get_model_name_for_provider("openai"))
        self.assertEqual(get_model_name_for_provider("mock"), "mock-model")
        self.assertEqual(get_model_name_for_provider("custom-provider"), "custom-provider")

    def test_generate_batch_id_contains_model_fragment(self) -> None:
        batch_id = generate_batch_id("gpt-5-nano")
        self.assertIn("gpt-5-nano", batch_id)

    def test_compute_match_rate(self) -> None:
        batch = BatchRun(
            batch_id="b1",
            dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            matched_entities=7,
            total_expected_entities=10,
        )
        self.assertEqual(compute_match_rate(batch), 0.7)
        batch.total_expected_entities = 0
        self.assertIsNone(compute_match_rate(batch))

    def test_compute_batch_cost_and_wall_clock(self) -> None:
        now = utc_now()
        batch = BatchRun(
            batch_id="b2",
            dataset="self_assembly",
            model_provider="openai-nano",
            model_name="mock-model",
            total_input_tokens=1000,
            total_output_tokens=500,
            created_at=now - timedelta(seconds=10),
            completed_at=now,
        )
        cost = compute_batch_cost(batch)
        self.assertIsNotNone(cost)
        self.assertGreaterEqual(cost, 0)
        elapsed_ms = compute_wall_clock_time_ms(batch)
        self.assertGreaterEqual(elapsed_ms, 9000)


if __name__ == "__main__":
    unittest.main()
