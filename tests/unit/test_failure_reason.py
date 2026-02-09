import unittest

from app.services.failure_reason import bucket_failure_reason, normalize_failure_reason


class FailureReasonTests(unittest.TestCase):
    def test_bucket_provider_error(self):
        self.assertEqual(bucket_failure_reason("Provider error: timeout"), "provider")

    def test_bucket_fetch_error(self):
        self.assertEqual(
            bucket_failure_reason("Failed to fetch the provided URL (HTTP 403)."),
            "fetch_error",
        )

    def test_bucket_unknown_when_missing(self):
        self.assertEqual(bucket_failure_reason(None), "unknown")

    def test_normalize_validation(self):
        self.assertEqual(
            normalize_failure_reason("Parse/validation error: bad json"),
            "Parse/validation error",
        )

    def test_normalize_fallback_truncates(self):
        text = "x" * 300
        self.assertEqual(len(normalize_failure_reason(text)), 120)


if __name__ == "__main__":
    unittest.main()
