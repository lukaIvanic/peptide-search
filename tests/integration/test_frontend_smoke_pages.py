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
        self.assertIn("Extraction Batches", text)
        self.assertIn("id=\"batchGrid\"", text)


if __name__ == "__main__":
    unittest.main()
