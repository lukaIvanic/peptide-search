import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.integrations.llm.base import DocumentInput
from app.integrations.llm.gemini import GeminiProvider
from app.integrations.llm.openrouter import OpenRouterProvider


class LlmAdapterTests(unittest.TestCase):
    def test_openrouter_builds_url_file_payload_and_parses_json(self) -> None:
        provider = OpenRouterProvider(api_key="test-key", model="openai/gpt-4o-mini")
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        }

        with patch("app.integrations.llm.openrouter.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = fake_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aexit__.return_value = False

            output = asyncio.run(
                provider.generate(
                    system_prompt="sys",
                    user_prompt="usr",
                    document=DocumentInput.from_url("https://example.org/paper.pdf"),
                )
            )

            self.assertEqual(output, '{"ok": true}')
            self.assertEqual(provider.get_last_usage()["total_tokens"], 18)
            call = mock_client.post.call_args
            self.assertIsNotNone(call)
            payload = call.kwargs["json"]
            content = payload["messages"][1]["content"]
            self.assertEqual(content[1]["type"], "file")
            self.assertEqual(content[1]["file"]["url"], "https://example.org/paper.pdf")

    def test_gemini_builds_inline_pdf_payload_and_parses_json(self) -> None:
        provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}],
            "usageMetadata": {
                "promptTokenCount": 20,
                "candidatesTokenCount": 12,
                "totalTokenCount": 32,
            },
        }

        with patch("app.integrations.llm.gemini.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = fake_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aexit__.return_value = False

            output = asyncio.run(
                provider.generate(
                    system_prompt="sys",
                    user_prompt="usr",
                    document=DocumentInput.from_file(b"%PDF-1.4", "doc.pdf"),
                )
            )

            self.assertEqual(output, '{"ok": true}')
            self.assertEqual(provider.get_last_usage()["total_tokens"], 32)
            call = mock_client.post.call_args
            self.assertIsNotNone(call)
            payload = call.kwargs["json"]
            parts = payload["contents"][0]["parts"]
            self.assertEqual(parts[1]["inlineData"]["mimeType"], "application/pdf")
            self.assertTrue(parts[1]["inlineData"]["data"])


if __name__ == "__main__":
    unittest.main()
