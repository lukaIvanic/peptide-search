import unittest

from app.schemas import BaselineCase, SearchItem
from app.services.baseline_helpers import (
    get_case_paper_key,
    normalize_case_doi,
    get_source_key,
    get_source_keys,
    select_baseline_result,
)


class BaselineHelperTests(unittest.TestCase):
    def test_normalize_case_doi_removes_version_suffix(self):
        self.assertEqual(
            normalize_case_doi("10.21203/rs.3.rs-109949/v13"),
            "10.21203/rs.3.rs-109949",
        )

    def test_get_source_key_prefers_url(self):
        case = BaselineCase(
            id="c1",
            dataset="self_assembly",
            doi="10.1/abc",
            paper_url="https://example.com/paper",
        )
        self.assertEqual(
            get_source_key(case, "https://example.com/pdf"),
            "url:https://example.com/pdf",
        )

    def test_get_source_keys_includes_doi_and_pubmed(self):
        case = BaselineCase(
            id="c1",
            dataset="self_assembly",
            doi="10.1/abc",
            pubmed_id="12345",
        )
        keys = get_source_keys(case, None)
        self.assertIn("doi:10.1/abc", keys)
        self.assertIn("pubmed:12345", keys)

    def test_get_case_paper_key_preserves_doi_version(self):
        case = BaselineCase(
            id="c1",
            dataset="self_assembly",
            doi="10.21203/rs.3.rs-109949/v13",
        )
        self.assertEqual(
            get_case_paper_key(case),
            "doi:10.21203/rs.3.rs-109949/v13",
        )

    def test_select_baseline_result_uses_exact_doi_match(self):
        results = [
            SearchItem(title="a", doi="10.1/no", url="u1", source="x"),
            SearchItem(title="b", doi="10.1/yes", url="u2", source="x"),
        ]
        picked = select_baseline_result(results, "10.1/YES")
        self.assertIsNotNone(picked)
        self.assertEqual(picked.title, "b")


if __name__ == "__main__":
    unittest.main()
