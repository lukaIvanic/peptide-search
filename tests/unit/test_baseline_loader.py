import unittest
from unittest.mock import patch

from app.baseline.loader import is_local_pdf_unverified


class BaselineLoaderTests(unittest.TestCase):
    def test_is_local_pdf_unverified_when_explicitly_false(self) -> None:
        mapping = {
            "10.1000/test-doi": {
                "main": ["data/test.pdf"],
                "verified": False,
            }
        }
        with patch("app.baseline.loader.load_local_pdf_mapping", return_value=mapping):
            self.assertTrue(is_local_pdf_unverified("10.1000/test-doi"))

    def test_is_local_pdf_unverified_defaults_to_false_when_key_missing(self) -> None:
        mapping = {
            "10.1000/test-doi": {
                "main": ["data/test.pdf"],
            }
        }
        with patch("app.baseline.loader.load_local_pdf_mapping", return_value=mapping):
            self.assertFalse(is_local_pdf_unverified("10.1000/test-doi"))

    def test_is_local_pdf_unverified_false_when_doi_missing_from_mapping(self) -> None:
        with patch("app.baseline.loader.load_local_pdf_mapping", return_value={}):
            self.assertFalse(is_local_pdf_unverified("10.1000/absent"))


if __name__ == "__main__":
    unittest.main()
