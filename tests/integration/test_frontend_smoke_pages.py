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
        has_evaluation_view = "Evaluation Runs" in text and 'id="batchGrid"' in text
        has_legacy_view = "Evaluation Details" in text and 'id="baselineList"' in text
        self.assertTrue(has_evaluation_view or has_legacy_view)
        if has_evaluation_view:
            self.assertIn('id="providerAccuracyChart"', text)
            self.assertIn('id="providerAccuracyPlot"', text)
            self.assertIn('id="resetBaselineDefaultsBtn"', text)

    def test_baseline_detail_page_loads(self) -> None:
        response = self.client.get("/baseline/test-batch")
        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('id="baselineList"', text)
        self.assertIn("Evaluation Details", text)

if __name__ == "__main__":
    unittest.main()
