import unittest

from app.services.retry_policies import (
    failure_matches_filters,
    reconcile_skipped_count,
    resolve_retry_source_url,
)


class RetryPoliciesTests(unittest.TestCase):
    def test_failure_matches_filters(self) -> None:
        reason = "Provider error: timeout"
        self.assertTrue(failure_matches_filters(reason))
        self.assertTrue(failure_matches_filters(reason, bucket="provider"))
        self.assertTrue(failure_matches_filters(reason, reason="Provider error"))
        self.assertFalse(failure_matches_filters(reason, bucket="pdf_processing"))
        self.assertFalse(failure_matches_filters(reason, reason="Parse/validation error"))

    def test_reconcile_skipped_count(self) -> None:
        self.assertEqual(
            reconcile_skipped_count(requested=5, enqueued=2, skipped=1, skipped_not_failed=1),
            2,
        )
        self.assertEqual(
            reconcile_skipped_count(requested=3, enqueued=2, skipped=1, skipped_not_failed=0),
            1,
        )

    def test_resolve_retry_source_url(self) -> None:
        self.assertEqual(
            resolve_retry_source_url("https://override", "https://run", "https://paper"),
            "https://override",
        )
        self.assertEqual(
            resolve_retry_source_url(None, "https://run", "https://paper"),
            "https://run",
        )
        self.assertEqual(
            resolve_retry_source_url(None, None, "https://paper"),
            "https://paper",
        )
        self.assertIsNone(resolve_retry_source_url(None, None, None))


if __name__ == "__main__":
    unittest.main()
