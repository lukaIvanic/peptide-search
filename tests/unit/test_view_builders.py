import unittest
from datetime import datetime

from app.persistence.models import ExtractionRun, Paper
from app.services.view_builders import parse_json_list, build_run_payload


class ViewBuilderTests(unittest.TestCase):
    def test_parse_json_list_handles_invalid(self):
        self.assertEqual(parse_json_list("not-json"), [])

    def test_parse_json_list_handles_non_list(self):
        self.assertEqual(parse_json_list('{"a":1}'), [])

    def test_parse_json_list_handles_list(self):
        self.assertEqual(parse_json_list('["a","b"]'), ["a", "b"])

    def test_build_run_payload_parses_embedded_json(self):
        run = ExtractionRun(
            id=7,
            paper_id=3,
            status="stored",
            prompts_json='{"system_prompt":"x"}',
            raw_json='{"entities":[]}',
            model_provider="openai",
            model_name="gpt-test",
            pdf_url="https://example.com/a.pdf",
            created_at=datetime(2026, 1, 1),
        )
        paper = Paper(
            id=3,
            title="Paper",
            doi="10.1/abc",
            url="https://example.com",
            source="pmc",
            year=2025,
            authors_json='["Alice","Bob"]',
            created_at=datetime(2026, 1, 1),
        )

        payload = build_run_payload(run, paper)

        self.assertEqual(payload["paper"]["authors"], ["Alice", "Bob"])
        self.assertEqual(payload["run"]["prompts"], {"system_prompt": "x"})
        self.assertEqual(payload["run"]["raw_json"], {"entities": []})


if __name__ == "__main__":
    unittest.main()
