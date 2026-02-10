import asyncio
import unittest

from app.config import settings
from app.integrations.llm.registry import (
    ProviderSelectionError,
    provider_catalog,
    refresh_provider_models,
    resolve_provider_selection,
)


class LlmRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_openai_key = settings.OPENAI_API_KEY
        self.old_gemini_key = settings.GEMINI_API_KEY
        self.old_openrouter_key = settings.OPENROUTER_API_KEY
        settings.OPENAI_API_KEY = "test-openai"
        settings.GEMINI_API_KEY = None
        settings.OPENROUTER_API_KEY = None

    def tearDown(self) -> None:
        settings.OPENAI_API_KEY = self.old_openai_key
        settings.GEMINI_API_KEY = self.old_gemini_key
        settings.OPENROUTER_API_KEY = self.old_openrouter_key

    def test_alias_resolution_maps_openai_mini_to_canonical_provider(self) -> None:
        selection = resolve_provider_selection(provider="openai-mini", model=None)
        self.assertEqual(selection.provider_id, "openai")
        self.assertEqual(selection.alias_used, "openai-mini")
        self.assertEqual(selection.model_id, settings.OPENAI_MODEL_MINI)

    def test_mock_rejects_unknown_custom_model(self) -> None:
        with self.assertRaises(ProviderSelectionError):
            resolve_provider_selection(provider="mock", model="mock-custom")

    def test_provider_catalog_exposes_required_fields(self) -> None:
        payload = provider_catalog()
        providers = payload.get("providers", [])
        self.assertGreaterEqual(len(providers), 5)
        by_id = {row["provider_id"]: row for row in providers}
        self.assertIn("openai", by_id)
        self.assertIn("gemini", by_id)
        self.assertIn("openrouter", by_id)
        self.assertIn("mock", by_id)
        self.assertIn("capabilities", by_id["openai"])
        self.assertIn("curated_models", by_id["openai"])
        self.assertIn("default_model", by_id["openai"])

    def test_refresh_provider_models_skips_disabled_and_returns_warnings(self) -> None:
        payload = asyncio.run(refresh_provider_models(force=True))
        warnings = payload.get("warnings", [])
        self.assertIsInstance(warnings, list)
        warned_ids = {item.get("provider_id") for item in warnings}
        self.assertIn("gemini", warned_ids)
        self.assertIn("openrouter", warned_ids)


if __name__ == "__main__":
    unittest.main()
