import unittest

from support import ApiIntegrationTestCase


class FrontendSmokePagesTests(ApiIntegrationTestCase):
    def test_dashboard_page_loads(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn("Search Scientific Literature", text)
        self.assertIn("id=\"papersTable\"", text)

    def test_baseline_page_loads(self) -> None:
        response = self.client.get("/baseline")
        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertTrue(
            ("Extraction Batches" in text and 'id="batchGrid"' in text)
            or ("Baseline Benchmark" in text and 'id="baselineList"' in text)
        )

    def test_baseline_detail_page_loads(self) -> None:
        response = self.client.get("/baseline/test-batch")
        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('id="baselineList"', text)
        self.assertTrue("Batch Details" in text or "Baseline Benchmark" in text)


if __name__ == "__main__":
    unittest.main()
