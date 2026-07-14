import io
import json
import unittest
import urllib.error

from pubmed_search_builder.infrastructure.transport import (
    RetryPolicy,
    StdlibTransport,
    TransportError,
    decode_json,
)
from pubmed_search_builder.infrastructure.services import MESH_EUTILS_POLICY, MESH_RDF_POLICY, REGISTRY_POLICY, ncbi_eutils_policy


class Response:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class TransportTests(unittest.TestCase):
    def test_service_policies_are_explicit_and_independent(self):
        self.assertEqual(ncbi_eutils_policy(10).rate_limit_per_second, 10)
        self.assertEqual(MESH_RDF_POLICY.rate_limit_per_second, 2)
        self.assertEqual(MESH_EUTILS_POLICY.rate_limit_per_second, 3)
        self.assertEqual(REGISTRY_POLICY.rate_limit_per_second, 2)

    def test_json_strictness_is_endpoint_selectable(self):
        raw = b'{"message":"literal\x1fcontrol"}'
        with self.assertRaises(json.JSONDecodeError):
            decode_json(raw)
        self.assertEqual(decode_json(raw, strict=False), {"message": "literal\x1fcontrol"})

    def test_transient_http_error_retries_then_succeeds(self):
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            if len(calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 503, "unavailable", {}, io.BytesIO(b"later"))
            return Response(b"{}")

        sleeps = []
        transport = StdlibTransport(opener=opener, sleeper=sleeps.append)
        response = transport.request(
            service="test",
            url="https://example.test/eutils",
            policy=RetryPolicy(retries=1, initial_backoff_seconds=0.25),
        )
        self.assertEqual(response.body, b"{}")
        self.assertEqual(response.retries, 1)
        self.assertEqual(sleeps, [0.25])

    def test_failures_open_circuit_and_redact_api_key(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 429, "limited", {}, io.BytesIO(b"slow down"))

        transport = StdlibTransport(opener=opener, sleeper=lambda _: None, monotonic=lambda: 10.0)
        policy = RetryPolicy(retries=0, circuit_failure_threshold=2, circuit_cooldown_seconds=30)
        for _ in range(2):
            with self.assertRaises(TransportError) as raised:
                transport.request(
                    service="ncbi",
                    url="https://example.test/eutils",
                    params={"api_key": "not-for-logs"},
                    policy=policy,
                )
            self.assertNotIn("not-for-logs", str(raised.exception))
        with self.assertRaises(TransportError) as raised:
            transport.request(service="ncbi", url="https://example.test/eutils", policy=policy)
        self.assertIn("circuit is open", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
