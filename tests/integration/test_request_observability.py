import unittest
from unittest.mock import patch

from support import ApiIntegrationTestCase


class RequestObservabilityEnabledTests(ApiIntegrationTestCase):
    def test_health_response_sets_request_id_header(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        request_id = response.headers.get("x-request-id")
        self.assertIsNotNone(request_id)
        self.assertGreater(len(request_id), 0)

    def test_request_id_header_is_propagated(self) -> None:
        expected = "integration-request-id-123"
        response = self.client.get("/api/health", headers={"X-Request-Id": expected})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("x-request-id"), expected)

    def test_health_fails_when_database_ping_fails(self) -> None:
        with patch("app.api.routers.system_router.ping_database", return_value=False):
            response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertIsNotNone(response.headers.get("x-request-id"))


class RequestObservabilityDisabledTests(ApiIntegrationTestCase):
    settings_overrides = {"REQUEST_LOGGING_ENABLED": False}

    def test_health_response_has_no_request_id_header_when_disabled(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get("x-request-id"))


if __name__ == "__main__":
    unittest.main()
