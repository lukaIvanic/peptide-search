import unittest

from app.services.queue_coordinator import QueueCoordinator


class QueueCoordinatorUnitTests(unittest.TestCase):
    def test_source_fingerprints_normalize_and_dedupe_urls(self) -> None:
        fingerprints = QueueCoordinator.source_fingerprints(
            " https://example.org/main.pdf ",
            pdf_urls=[
                "https://example.org/main.pdf",
                "https://example.org/supp.pdf",
                " https://example.org/supp.pdf ",
            ],
        )
        self.assertEqual(len(fingerprints), 2)
        self.assertEqual(
            fingerprints[0],
            QueueCoordinator.source_fingerprint("https://example.org/main.pdf"),
        )
        self.assertEqual(
            fingerprints[1],
            QueueCoordinator.source_fingerprint("https://example.org/supp.pdf"),
        )

    def test_source_fingerprints_include_primary_when_missing_from_pdf_urls(self) -> None:
        fingerprints = QueueCoordinator.source_fingerprints(
            "https://example.org/main.pdf",
            pdf_urls=["https://example.org/supp.pdf"],
        )
        self.assertEqual(len(fingerprints), 2)
        self.assertEqual(
            fingerprints[0],
            QueueCoordinator.source_fingerprint("https://example.org/main.pdf"),
        )

    def test_load_payload_handles_invalid_json_with_safe_defaults(self) -> None:
        payload = QueueCoordinator._load_payload("not-json")
        self.assertEqual(payload.run_id, 0)
        self.assertEqual(payload.paper_id, 0)
        self.assertEqual(payload.pdf_url, "")
        self.assertEqual(payload.provider, "openai")
        self.assertIsNone(payload.pdf_urls)


if __name__ == "__main__":
    unittest.main()
