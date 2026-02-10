import json
import unittest

from sqlmodel import Session, select

from app.config import settings
from app.persistence.models import ExtractionRun, QueueJob, RunStatus
from support import ApiIntegrationTestCase


class ApiProvidersAndModelsTests(ApiIntegrationTestCase):
    settings_overrides = {"OPENAI_API_KEY": "test-openai-key"}

    def test_providers_contract_exposes_required_fields(self) -> None:
        response = self.client.get("/api/providers")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("providers", payload)
        by_id = {item["provider_id"]: item for item in payload["providers"]}
        for key in ["openai", "deepseek", "gemini", "openrouter", "mock"]:
            self.assertIn(key, by_id)
        for required in [
            "provider_id",
            "label",
            "enabled",
            "capabilities",
            "default_model",
            "curated_models",
            "supports_custom_model",
        ]:
            self.assertIn(required, by_id["openai"])

    def test_providers_refresh_returns_warnings_when_discovery_credentials_missing(self) -> None:
        response = self.client.post("/api/providers/refresh")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("providers", payload)
        self.assertIn("warnings", payload)
        self.assertIsInstance(payload["warnings"], list)

    def test_enqueue_accepts_openai_alias_and_persists_canonical_provider_plus_model(self) -> None:
        response = self.client.post(
            "/api/enqueue",
            json={
                "papers": [
                    {
                        "title": "Provider alias",
                        "doi": "10.1000/provider-alias",
                        "url": "https://example.org/provider-alias",
                        "pdf_url": "https://example.org/provider-alias.pdf",
                    }
                ],
                "provider": "openai-mini",
            },
        )
        self.assertEqual(response.status_code, 200)
        run_id = response.json()["runs"][0]["run_id"]

        with Session(self.db_module.engine) as session:
            run = session.get(ExtractionRun, run_id)
            self.assertIsNotNone(run)
            self.assertEqual(run.model_provider, "openai")
            self.assertEqual(run.model_name, settings.OPENAI_MODEL_MINI)

            job = session.exec(select(QueueJob).where(QueueJob.run_id == run_id)).first()
            self.assertIsNotNone(job)
            payload = json.loads(job.payload_json or "{}")
            self.assertEqual(payload.get("provider"), "openai")
            self.assertEqual(payload.get("model"), settings.OPENAI_MODEL_MINI)

    def test_unknown_provider_returns_deterministic_bad_request_with_hint(self) -> None:
        response = self.client.post(
            "/api/enqueue",
            json={
                "papers": [
                    {
                        "title": "Unknown provider",
                        "pdf_url": "https://example.org/unknown-provider.pdf",
                    }
                ],
                "provider": "unknown-provider",
            },
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "bad_request")
        self.assertIn("details", payload["error"])
        self.assertEqual(payload["error"]["details"].get("hint"), "/api/providers")

    def test_retry_with_source_model_override_propagates_to_new_run_and_queue_payload(self) -> None:
        paper_id = self.create_paper(
            title="Retry model",
            doi="10.1000/retry-model",
            url="https://example.org/retry-model",
        )
        failed_run_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider timeout",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/retry-model-old.pdf",
        )
        response = self.client.post(
            f"/api/runs/{failed_run_id}/retry-with-source",
            json={
                "source_url": "https://example.org/retry-model-new.pdf",
                "provider": "mock",
                "model": "mock-model",
            },
        )
        self.assertEqual(response.status_code, 200)
        new_run_id = response.json()["id"]

        with Session(self.db_module.engine) as session:
            new_run = session.get(ExtractionRun, new_run_id)
            self.assertIsNotNone(new_run)
            self.assertEqual(new_run.model_provider, "mock")
            self.assertEqual(new_run.model_name, "mock-model")

            job = session.exec(select(QueueJob).where(QueueJob.run_id == new_run_id)).first()
            self.assertIsNotNone(job)
            payload = json.loads(job.payload_json or "{}")
            self.assertEqual(payload.get("provider"), "mock")
            self.assertEqual(payload.get("model"), "mock-model")


if __name__ == "__main__":
    unittest.main()
