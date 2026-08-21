"""Workspace-scoped NCBI response cache: reuse within a case, never across cases."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "scripts"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import pubmed_tool  # noqa: E402

from pubmed_search_builder.infrastructure.cache import (  # noqa: E402
    DEFAULT_CACHE_DIRNAME,
    ResponseCache,
    is_enabled_value,
)
from pubmed_search_builder.core.workspace import skill_root  # noqa: E402

SEARCH_PARAMS = {
    "db": "pubmed",
    "term": "asthma[tiab]",
    "retmode": "json",
    "retmax": "0",
    "tool": "test-tool",
    "email": "person@example.org",
    "api_key": "SECRET-KEY-VALUE",
}


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def cache_at(directory, clock=None, **kwargs) -> ResponseCache:
    return ResponseCache(Path(directory), clock=clock or Clock(), **kwargs)


class RoundTripTests(unittest.TestCase):
    def test_stored_response_is_returned_on_a_later_lookup(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td)
            self.assertIsNone(cache.get("esearch.fcgi", SEARCH_PARAMS))
            cache.put("esearch.fcgi", SEARCH_PARAMS, b'{"count": "7"}')
            self.assertEqual(cache.get("esearch.fcgi", SEARCH_PARAMS), b'{"count": "7"}')

    def test_a_separate_process_reads_the_same_entry(self):
        with tempfile.TemporaryDirectory() as td:
            cache_at(td).put("esearch.fcgi", SEARCH_PARAMS, b"body")
            # A fresh instance over the same directory is what a later CLI invocation sees.
            self.assertEqual(cache_at(td).get("esearch.fcgi", SEARCH_PARAMS), b"body")

    def test_non_utf8_bodies_survive_a_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td)
            payload = b"\xff\xfe binary \x00 body"
            cache.put("efetch.fcgi", SEARCH_PARAMS, payload)
            self.assertEqual(cache.get("efetch.fcgi", SEARCH_PARAMS), payload)

    def test_different_queries_do_not_share_an_entry(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td)
            cache.put("esearch.fcgi", SEARCH_PARAMS, b"first")
            other = {**SEARCH_PARAMS, "term": "diabetes[tiab]"}
            self.assertIsNone(cache.get("esearch.fcgi", other))

    def test_same_query_on_a_different_endpoint_does_not_share_an_entry(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td)
            cache.put("esearch.fcgi", SEARCH_PARAMS, b"search")
            self.assertIsNone(cache.get("elink.fcgi", SEARCH_PARAMS))


class CaseIsolationTests(unittest.TestCase):
    def test_two_workspaces_never_serve_each_others_responses(self):
        with tempfile.TemporaryDirectory() as case_a, tempfile.TemporaryDirectory() as case_b:
            cache_at(case_a).put("esearch.fcgi", SEARCH_PARAMS, b'{"count": "7"}')
            self.assertIsNone(cache_at(case_b).get("esearch.fcgi", SEARCH_PARAMS))

    def test_workspace_default_places_the_cache_inside_the_run_directory(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "runs" / "topic"
            workspace.mkdir(parents=True)
            cache = ResponseCache.for_workspace(workspace=workspace)
            self.assertTrue(cache.enabled)
            self.assertEqual(cache.directory, (workspace / DEFAULT_CACHE_DIRNAME).resolve())

    def test_distinct_workspaces_resolve_to_distinct_directories(self):
        with tempfile.TemporaryDirectory() as td:
            first = ResponseCache.for_workspace(workspace=Path(td) / "case-a")
            second = ResponseCache.for_workspace(workspace=Path(td) / "case-b")
            self.assertNotEqual(first.directory, second.directory)

    def test_caching_in_the_skill_installation_is_refused(self):
        cache = ResponseCache.for_workspace(workspace=skill_root())
        self.assertFalse(cache.enabled)
        self.assertIn("skill installation", cache.disabled_reason)
        # A disabled cache is a working no-op, never a crash or a silent shared cache.
        self.assertIsNone(cache.get("esearch.fcgi", SEARCH_PARAMS))
        cache.put("esearch.fcgi", SEARCH_PARAMS, b"body")
        self.assertIsNone(cache.get("esearch.fcgi", SEARCH_PARAMS))

    def test_an_explicit_directory_is_still_shared_deliberately(self):
        with tempfile.TemporaryDirectory() as shared:
            first = ResponseCache.for_workspace(directory=shared)
            second = ResponseCache.for_workspace(directory=shared)
            first.put("esearch.fcgi", SEARCH_PARAMS, b"body")
            self.assertEqual(second.get("esearch.fcgi", SEARCH_PARAMS), b"body")

    def test_env_cache_directory_cannot_escape_the_working_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = root / "run"
            external = root / "external"
            run.mkdir()
            values = {
                "NCBI_CACHE": "on",
                "NCBI_CACHE_DIR": str(external),
                "NCBI_RECORD_CACHE_TTL_DAYS": "30",
                "NCBI_CACHE_TTL_HOURS": "24",
            }
            previous = Path.cwd()
            try:
                os.chdir(run)
                with patch.object(pubmed_tool, "read_env", side_effect=lambda name, default="": values.get(name, default)):
                    cache = pubmed_tool.build_response_cache()
            finally:
                os.chdir(previous)
            self.assertFalse(cache.enabled)
            self.assertIn("outside the run workspace", cache.disabled_reason)

    def test_cli_cache_directory_is_an_explicit_external_override(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = root / "run"
            external = root / "external"
            run.mkdir()
            previous = Path.cwd()
            try:
                os.chdir(run)
                with patch.object(pubmed_tool, "read_env", side_effect=lambda name, default="": default):
                    cache = pubmed_tool.build_response_cache(directory=str(external))
            finally:
                os.chdir(previous)
            self.assertTrue(cache.enabled)
            self.assertEqual(cache.directory, external.resolve())


class SecretHygieneTests(unittest.TestCase):
    def test_the_api_key_never_reaches_the_stored_entry(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td)
            cache.put("esearch.fcgi", SEARCH_PARAMS, b"body")
            written = list(Path(td).rglob("*.json"))
            self.assertTrue(written)
            for path in written:
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("SECRET-KEY-VALUE", text)
                self.assertNotIn("person@example.org", text)
                self.assertNotIn("api_key", text)

    def test_rotating_the_api_key_or_email_keeps_the_entry_usable(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td)
            cache.put("esearch.fcgi", SEARCH_PARAMS, b"body")
            rotated = {**SEARCH_PARAMS, "api_key": "A-DIFFERENT-KEY", "email": "other@example.org", "tool": "other"}
            self.assertEqual(cache.get("esearch.fcgi", rotated), b"body")


class FreshnessTests(unittest.TestCase):
    def test_counts_expire_on_the_short_ttl(self):
        with tempfile.TemporaryDirectory() as td:
            clock = Clock()
            cache = cache_at(td, clock=clock, query_ttl_seconds=3600.0)
            cache.put("esearch.fcgi", SEARCH_PARAMS, b"body")
            clock.now += 3599
            self.assertEqual(cache.get("esearch.fcgi", SEARCH_PARAMS), b"body")
            clock.now += 2
            self.assertIsNone(cache.get("esearch.fcgi", SEARCH_PARAMS))
            self.assertEqual(cache.stats()["stale"], 1)

    def test_record_content_uses_the_long_ttl(self):
        with tempfile.TemporaryDirectory() as td:
            clock = Clock()
            cache = cache_at(td, clock=clock, query_ttl_seconds=3600.0, record_ttl_seconds=86400.0)
            cache.put("efetch.fcgi", SEARCH_PARAMS, b"record")
            clock.now += 7200  # past the query TTL, inside the record TTL
            self.assertEqual(cache.get("efetch.fcgi", SEARCH_PARAMS), b"record")

    def test_zero_ttl_disables_reuse_without_disabling_writes(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td, query_ttl_seconds=0.0)
            cache.put("esearch.fcgi", SEARCH_PARAMS, b"body")
            self.assertIsNone(cache.get("esearch.fcgi", SEARCH_PARAMS))


class CorruptionTests(unittest.TestCase):
    def test_unparsable_entries_are_a_miss_not_a_crash(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td)
            cache.put("esearch.fcgi", SEARCH_PARAMS, b"body")
            path = cache.entry_path("esearch.fcgi", SEARCH_PARAMS)
            path.write_text("not json", encoding="utf-8")
            self.assertIsNone(cache.get("esearch.fcgi", SEARCH_PARAMS))
            self.assertEqual(cache.stats()["unreadable"], 1)

    def test_an_entry_whose_request_does_not_match_is_never_served(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td)
            cache.put("esearch.fcgi", SEARCH_PARAMS, b"body")
            path = cache.entry_path("esearch.fcgi", SEARCH_PARAMS)
            entry = json.loads(path.read_text(encoding="utf-8"))
            entry["params"]["term"] = "tampered[tiab]"
            path.write_text(json.dumps(entry), encoding="utf-8")
            self.assertIsNone(cache.get("esearch.fcgi", SEARCH_PARAMS))


class ReportingTests(unittest.TestCase):
    def test_stats_report_activity_for_disclosure(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td)
            cache.get("esearch.fcgi", SEARCH_PARAMS)
            cache.put("esearch.fcgi", SEARCH_PARAMS, b"body")
            cache.get("esearch.fcgi", SEARCH_PARAMS)
            stats = cache.stats()
            self.assertEqual((stats["hits"], stats["misses"], stats["writes"]), (1, 1, 1))
            self.assertTrue(cache.served_from_cache())

    def test_disabled_cache_reports_its_reason(self):
        cache = ResponseCache.disabled("disabled by --no-cache")
        stats = cache.stats()
        self.assertFalse(stats["enabled"])
        self.assertEqual(stats["disabled_reason"], "disabled by --no-cache")
        self.assertFalse(cache.served_from_cache())

    def test_clear_removes_stored_entries(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td)
            cache.put("esearch.fcgi", SEARCH_PARAMS, b"body")
            self.assertEqual(cache.describe()["entries"], 1)
            self.assertEqual(cache.clear()["cleared"], 1)
            self.assertEqual(cache.describe()["entries"], 0)


class Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ClientIntegrationTests(unittest.TestCase):
    """The cache only matters if NcbiClient actually consults it on every request."""

    def _client(self, cache, calls):
        from pubmed_search_builder.infrastructure.transport import StdlibTransport

        def opener(request, timeout):
            calls.append(request.full_url)
            return Response(b'{"esearchresult": {"count": "7"}}')

        return pubmed_tool.NcbiClient(
            transport=StdlibTransport(opener=opener, sleeper=lambda _seconds: None),
            cache=cache,
        )

    def test_a_repeated_request_does_not_reach_the_network(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td)
            calls: list[str] = []
            client = self._client(cache, calls)
            first = client.request("esearch.fcgi", {"db": "pubmed", "term": "asthma[tiab]"})
            second = client.request("esearch.fcgi", {"db": "pubmed", "term": "asthma[tiab]"})
            self.assertEqual(first, second)
            self.assertEqual(len(calls), 1, "second identical request should have been served from cache")

    def test_a_different_query_still_reaches_the_network(self):
        with tempfile.TemporaryDirectory() as td:
            calls: list[str] = []
            client = self._client(cache_at(td), calls)
            client.request("esearch.fcgi", {"db": "pubmed", "term": "asthma[tiab]"})
            client.request("esearch.fcgi", {"db": "pubmed", "term": "diabetes[tiab]"})
            self.assertEqual(len(calls), 2)

    def test_a_disabled_cache_always_reaches_the_network(self):
        calls: list[str] = []
        client = self._client(ResponseCache.disabled("disabled by --no-cache"), calls)
        client.request("esearch.fcgi", {"db": "pubmed", "term": "asthma[tiab]"})
        client.request("esearch.fcgi", {"db": "pubmed", "term": "asthma[tiab]"})
        self.assertEqual(len(calls), 2)

    def test_metadata_discloses_cache_activity_in_saved_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            cache = cache_at(td)
            client = self._client(cache, [])
            client.request("esearch.fcgi", {"db": "pubmed", "term": "asthma[tiab]"})
            client.request("esearch.fcgi", {"db": "pubmed", "term": "asthma[tiab]"})
            disclosure = client.metadata()["response_cache"]
            self.assertTrue(disclosure["enabled"])
            self.assertEqual(disclosure["hits"], 1)

    def test_client_defaults_to_a_cache_without_any_caller_plumbing(self):
        client = pubmed_tool.NcbiClient()
        self.assertIsInstance(client.cache, ResponseCache)


class ConfigurationTests(unittest.TestCase):
    def test_on_off_values_are_interpreted(self):
        for value in ("0", "false", "no", "off", "disabled", "OFF"):
            self.assertFalse(is_enabled_value(value))
        for value in ("1", "true", "yes", "on", "ON"):
            self.assertTrue(is_enabled_value(value))
        self.assertTrue(is_enabled_value(""))

    def test_disabled_configuration_yields_a_no_op_cache(self):
        cache = ResponseCache.for_workspace(enabled=False)
        self.assertFalse(cache.enabled)
        self.assertIsNone(cache.directory)


if __name__ == "__main__":
    unittest.main()
