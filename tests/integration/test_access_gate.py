import base64
import asyncio
import unittest
from unittest.mock import patch

from support import ApiIntegrationTestCase


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode("utf-8")
    token = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {token}"}


class AccessGateDisabledTests(ApiIntegrationTestCase):
    def test_dashboard_allows_unauthenticated_access_when_gate_disabled(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)


class AccessGateEnabledTests(ApiIntegrationTestCase):
    settings_overrides = {
        "ACCESS_GATE_ENABLED": True,
        "ACCESS_GATE_USERNAME": "demo",
        "ACCESS_GATE_PASSWORD": "secret",
    }

    def test_root_requires_authentication(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 401)
        self.assertIn("WWW-Authenticate", response.headers)
        self.assertIn("Basic", response.headers["WWW-Authenticate"])

    def test_authenticated_dashboard_request_succeeds(self) -> None:
        headers = _basic_auth_header("demo", "secret")
        response = self.client.get("/", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Search Scientific Literature", response.text)

    def test_authenticated_health_request_succeeds(self) -> None:
        headers = _basic_auth_header("demo", "secret")
        response = self.client.get("/api/health", headers=headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")

    def test_health_is_public_for_platform_health_checks(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")

    def test_stream_requires_auth_when_gate_enabled(self) -> None:
        response = self.client.get("/api/stream")
        self.assertEqual(response.status_code, 401)

    def test_authenticated_stream_connects_and_emits_connected_event(self) -> None:
        class _FakeQueue:
            async def get(self):
                raise asyncio.CancelledError

        class _FakeBroadcaster:
            async def subscribe(self):
                return _FakeQueue()

            async def unsubscribe(self, _queue):
                return None

        headers = _basic_auth_header("demo", "secret")
        with patch("app.api.routers.system_router.get_broadcaster", return_value=_FakeBroadcaster()):
            response = self.client.get("/api/stream", headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()
