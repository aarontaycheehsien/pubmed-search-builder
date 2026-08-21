import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "mesh_tool.py"
SPEC = importlib.util.spec_from_file_location("mesh_tool_resilience", MODULE_PATH)
mesh_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mesh_tool)

from pubmed_search_builder.infrastructure.env import (  # noqa: E402
    configure_env_file,
    reset_env_file_cache,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


class MeshResilienceTests(unittest.TestCase):
    ENV_NAMES = (
        "MESH_CACHE",
        "MESH_CACHE_DIR",
        "MESH_CACHE_TTL_DAYS",
        "MESH_RATE_LIMIT",
        "MESH_THROTTLE_RETRIES",
        "MESH_TRANSIENT_RETRIES",
        "MESH_CIRCUIT_THRESHOLD",
        "MESH_CIRCUIT_COOLDOWN",
        "MESH_CIRCUIT_MAX_COOLDOWN",
    )

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_environment = {name: os.environ.get(name) for name in self.ENV_NAMES}
        os.environ.update(
            {
                "MESH_CACHE": "on",
                "MESH_CACHE_DIR": self.temporary_directory.name,
                "MESH_CACHE_TTL_DAYS": "1",
                "MESH_RATE_LIMIT": "0",
                "MESH_THROTTLE_RETRIES": "1",
                "MESH_TRANSIENT_RETRIES": "3",
                "MESH_CIRCUIT_THRESHOLD": "3",
                "MESH_CIRCUIT_COOLDOWN": "10",
                "MESH_CIRCUIT_MAX_COOLDOWN": "60",
            }
        )
        self.original_urlopen = mesh_tool.urllib.request.urlopen
        self.original_sleep = mesh_tool.sleep_seconds
        self.original_wall_time = mesh_tool.SYSTEM_WALL_TIME
        self.original_uniform = mesh_tool.random.uniform
        self.original_lookup = mesh_tool.lookup
        self.original_terms = mesh_tool.terms
        self.original_details = mesh_tool.details
        mesh_tool.sleep_seconds = lambda _seconds: None
        mesh_tool.CACHE_BYPASS = False
        mesh_tool.REQUEST_CACHE.clear()
        mesh_tool.NETWORK_METRICS.clear()
        mesh_tool.FALLBACK_HOST_STATE.clear()
        configure_env_file(None)
        reset_env_file_cache()

    def tearDown(self):
        mesh_tool.urllib.request.urlopen = self.original_urlopen
        mesh_tool.sleep_seconds = self.original_sleep
        mesh_tool.SYSTEM_WALL_TIME = self.original_wall_time
        mesh_tool.random.uniform = self.original_uniform
        mesh_tool.lookup = self.original_lookup
        mesh_tool.terms = self.original_terms
        mesh_tool.details = self.original_details
        mesh_tool.CACHE_BYPASS = False
        mesh_tool.REQUEST_CACHE.clear()
        mesh_tool.NETWORK_METRICS.clear()
        mesh_tool.FALLBACK_HOST_STATE.clear()
        configure_env_file(None)
        reset_env_file_cache()
        for name, value in self.original_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temporary_directory.cleanup()

    def test_persistent_cache_is_reused_after_memory_and_process_boundaries(self):
        url = f"{mesh_tool.LOOKUP_BASE}/descriptor"
        params = {"label": "pressure ulcer", "match": "exact", "limit": "10"}
        calls = []

        def first_urlopen(*_args, **_kwargs):
            calls.append("network")
            return FakeResponse([{"resource": "D003668", "label": "Pressure Ulcer"}])

        mesh_tool.urllib.request.urlopen = first_urlopen
        expected = mesh_tool.request_json(url, params)
        self.assertEqual(len(calls), 1)

        mesh_tool.REQUEST_CACHE.clear()
        mesh_tool.urllib.request.urlopen = lambda *_args, **_kwargs: self.fail("persistent cache was not used")
        self.assertEqual(mesh_tool.request_json(url, params), expected)
        self.assertEqual(len(calls), 1)

        child_code = f"""
import importlib.util, json
spec = importlib.util.spec_from_file_location('mesh_child', {str(MODULE_PATH)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.urllib.request.urlopen = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network used'))
value = module.request_json({url!r}, {params!r})
print(json.dumps(value))
"""
        completed = subprocess.run(
            [sys.executable, "-c", child_code],
            check=True,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        self.assertEqual(json.loads(completed.stdout), expected)

    def test_stale_and_corrupt_cache_entries_are_safe_misses(self):
        url = f"{mesh_tool.LOOKUP_BASE}/descriptor"
        stale_params = {"label": "stale", "match": "exact", "limit": "1"}
        mesh_tool.SYSTEM_WALL_TIME = lambda: 100.0
        mesh_tool.persistent_cache_put(url, stale_params, {"value": "old"})
        mesh_tool.SYSTEM_WALL_TIME = lambda: 100.0 + 86401.0
        calls = []
        mesh_tool.urllib.request.urlopen = lambda *_args, **_kwargs: calls.append("stale") or FakeResponse(
            {"value": "fresh"}
        )
        self.assertEqual(mesh_tool.request_json(url, stale_params), {"value": "fresh"})

        corrupt_params = {"label": "corrupt", "match": "exact", "limit": "1"}
        corrupt_path = mesh_tool.cache_entry_path(url, corrupt_params)
        corrupt_path.parent.mkdir(parents=True, exist_ok=True)
        corrupt_path.write_text("{not-json", encoding="utf-8")
        mesh_tool.urllib.request.urlopen = lambda *_args, **_kwargs: calls.append("corrupt") or FakeResponse(
            {"value": "recovered"}
        )
        self.assertEqual(mesh_tool.request_json(url, corrupt_params), {"value": "recovered"})
        self.assertEqual(calls, ["stale", "corrupt"])

    def test_error_classifier_distinguishes_rate_transient_and_hard_failures(self):
        reset = ConnectionResetError(10054, "forcibly closed")
        unavailable = urllib.error.HTTPError("https://example.test", 503, "unavailable", {}, None)
        not_found = urllib.error.HTTPError("https://example.test", 404, "missing", {}, None)
        retry_after = urllib.error.HTTPError(
            "https://example.test", 403, "slow down", {"Retry-After": "3"}, None
        )

        self.assertEqual(mesh_tool.classify_request_error(reset), mesh_tool.ERROR_RATE_LIMIT_LIKE)
        self.assertEqual(mesh_tool.classify_request_error(unavailable), mesh_tool.ERROR_TRANSIENT)
        self.assertEqual(mesh_tool.classify_request_error(not_found), mesh_tool.ERROR_HARD)
        self.assertEqual(mesh_tool.classify_request_error(retry_after), mesh_tool.ERROR_RATE_LIMIT_LIKE)
        unavailable.close()
        not_found.close()
        retry_after.close()

    def test_rate_limit_like_retries_are_tighter_than_transient_retries(self):
        os.environ["MESH_CIRCUIT_THRESHOLD"] = "99"
        url = f"{mesh_tool.LOOKUP_BASE}/descriptor"
        calls = []

        def reset_urlopen(*_args, **_kwargs):
            calls.append("reset")
            raise ConnectionResetError(10054, "forcibly closed")

        mesh_tool.urllib.request.urlopen = reset_urlopen
        with self.assertRaises(mesh_tool.MeshError):
            mesh_tool.request_json(url, {"label": "reset", "match": "exact", "limit": "1"})
        self.assertEqual(calls, ["reset", "reset"])

        def unavailable_urlopen(*_args, **_kwargs):
            calls.append("503")
            raise urllib.error.HTTPError("https://example.test", 503, "unavailable", {}, None)

        mesh_tool.urllib.request.urlopen = unavailable_urlopen
        with self.assertRaises(mesh_tool.MeshError):
            mesh_tool.request_json(url, {"label": "unavailable", "match": "exact", "limit": "1"})
        self.assertEqual(calls.count("503"), 4)

    def test_only_successful_json_is_cached(self):
        os.environ["MESH_TRANSIENT_RETRIES"] = "0"
        url = f"{mesh_tool.LOOKUP_BASE}/descriptor"
        params = {"label": "invalid", "match": "exact", "limit": "1"}
        mesh_tool.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(b"not-json")

        with self.assertRaises(mesh_tool.MeshError):
            mesh_tool.request_json(url, params)
        self.assertFalse(mesh_tool.cache_entry_path(url, params).exists())

        mesh_tool.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse({"value": "valid"})
        self.assertEqual(mesh_tool.request_json(url, params), {"value": "valid"})
        self.assertTrue(mesh_tool.cache_entry_path(url, params).exists())

    def test_circuit_state_is_shared_and_allows_only_one_half_open_probe(self):
        os.environ["MESH_CIRCUIT_THRESHOLD"] = "2"
        now = [100.0]
        mesh_tool.SYSTEM_WALL_TIME = lambda: now[0]
        host = "id.nlm.nih.gov"

        self.assertFalse(mesh_tool.circuit_rate_limit_failure(host)["opened"])
        self.assertTrue(mesh_tool.circuit_rate_limit_failure(host)["opened"])
        with self.assertRaises(mesh_tool.CircuitOpenError):
            mesh_tool.circuit_before_request(host)

        child_code = f"""
import importlib.util
spec = importlib.util.spec_from_file_location('mesh_child', {str(MODULE_PATH)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.SYSTEM_WALL_TIME = lambda: 100.0
try:
    module.circuit_before_request('id.nlm.nih.gov')
except module.CircuitOpenError:
    print('open')
else:
    raise SystemExit('shared circuit was not open')
"""
        completed = subprocess.run(
            [sys.executable, "-c", child_code],
            check=True,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        self.assertEqual(completed.stdout.strip(), "open")

        now[0] = 111.0
        self.assertTrue(mesh_tool.circuit_before_request(host))
        with self.assertRaises(mesh_tool.CircuitOpenError):
            mesh_tool.circuit_before_request(host)
        mesh_tool.circuit_transient_failure(host, half_open_owner=True)
        reopened = mesh_tool.circuit_status(host)
        self.assertEqual(reopened["state"], "open")
        self.assertEqual(reopened["open_count"], 2)
        self.assertEqual(reopened["cooldown_until"], 131.0)

        now[0] = 132.0
        self.assertTrue(mesh_tool.circuit_before_request(host))
        mesh_tool.circuit_success(host)
        self.assertEqual(mesh_tool.circuit_status(host)["state"], "closed")

    def test_non_rate_failure_breaks_consecutive_rate_failure_sequence(self):
        os.environ["MESH_CIRCUIT_THRESHOLD"] = "2"
        host = "id.nlm.nih.gov"
        self.assertFalse(mesh_tool.circuit_rate_limit_failure(host)["opened"])
        mesh_tool.circuit_hard_failure(host, half_open_owner=False)
        self.assertFalse(mesh_tool.circuit_rate_limit_failure(host)["opened"])
        self.assertEqual(mesh_tool.circuit_status(host)["consecutive_rate_limit_failures"], 1)

    def test_rate_pacing_uses_shared_next_request_slot(self):
        os.environ["MESH_RATE_LIMIT"] = "2"
        mesh_tool.SYSTEM_WALL_TIME = lambda: 100.0
        mesh_tool.random.uniform = lambda _lower, _upper: 0.0
        waits = []
        mesh_tool.sleep_seconds = waits.append

        self.assertEqual(mesh_tool.reserve_request_slot("id.nlm.nih.gov"), 0.0)
        child_code = f"""
import importlib.util, json
spec = importlib.util.spec_from_file_location('mesh_child', {str(MODULE_PATH)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.SYSTEM_WALL_TIME = lambda: 100.0
module.random.uniform = lambda lower, upper: 0.0
waits = []
module.sleep_seconds = waits.append
wait = module.reserve_request_slot('id.nlm.nih.gov')
print(json.dumps({{'wait': wait, 'slept': waits}}))
"""
        completed = subprocess.run(
            [sys.executable, "-c", child_code],
            check=True,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        child_result = json.loads(completed.stdout)
        self.assertEqual(child_result, {"wait": 0.5, "slept": [0.5]})
        self.assertEqual(waits, [])

    def test_no_cache_bypasses_reads_and_writes(self):
        url = f"{mesh_tool.LOOKUP_BASE}/descriptor"
        params = {"label": "bypass", "match": "exact", "limit": "1"}
        mesh_tool.persistent_cache_put(url, params, {"value": "cached"})
        mesh_tool.CACHE_BYPASS = True
        mesh_tool.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse({"value": "network"})

        self.assertEqual(mesh_tool.request_json(url, params), {"value": "network"})
        mesh_tool.CACHE_BYPASS = False
        self.assertEqual(mesh_tool.persistent_cache_get(url, params), {"value": "cached"})

    def test_cli_exposes_cache_and_circuit_controls(self):
        parser = mesh_tool.build_parser()
        self.assertTrue(parser.parse_args(["lookup", "--label", "x", "--no-cache"]).no_cache)
        self.assertTrue(parser.parse_args(["sweep", "--concept", "x", "--no-cache"]).no_cache)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(mesh_tool.main(["cache", "stats"]), 0)
        self.assertEqual(json.loads(output.getvalue())["operation"], "mesh-cache-stats")

        cache_url = f"{mesh_tool.LOOKUP_BASE}/descriptor"
        cache_params = {"label": "clear", "match": "exact", "limit": "1"}
        mesh_tool.persistent_cache_put(cache_url, cache_params, {"value": "cached"})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(mesh_tool.main(["cache", "clear"]), 0)
        clear_result = json.loads(output.getvalue())
        self.assertEqual(clear_result["operation"], "mesh-cache-clear")
        self.assertEqual(clear_result["removed_entries"], 1)
        self.assertFalse(mesh_tool.cache_entry_path(cache_url, cache_params).exists())

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(mesh_tool.main(["circuit", "reset"]), 0)
        self.assertEqual(json.loads(output.getvalue())["operation"], "mesh-circuit-reset")

    def test_sweep_stops_once_on_open_circuit_and_preserves_pending_work(self):
        mesh_tool.lookup = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            mesh_tool.CircuitOpenError("id.nlm.nih.gov", 200.0)
        )
        mesh_tool.terms = lambda *_args, **_kwargs: self.fail("terms should not run after the circuit opens")

        result = mesh_tool.sweep("pressure ulcer", ["bed sore"], 20, False, 40, 30, max_seconds=0.0)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["stop_reason"], "circuit_open")
        self.assertEqual(result["coverage"]["units_pending"], 6)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["code"], "circuit_open")

    def test_sweep_preserves_pending_details_when_circuit_opens(self):
        descriptor = "http://id.nlm.nih.gov/mesh/D003668"
        mesh_tool.lookup = lambda label, match, limit, **_kwargs: {
            "operation": "lookup",
            "results": [{"resource": descriptor, "label": "Pressure Ulcer"}] if match == "exact" else [],
        }
        mesh_tool.terms = lambda *_args, **_kwargs: {"operation": "terms", "results": []}
        mesh_tool.details = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            mesh_tool.CircuitOpenError("id.nlm.nih.gov", 200.0)
        )

        result = mesh_tool.sweep("pressure ulcer", [], 20, True, 40, 30, max_seconds=0.0)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["stop_reason"], "circuit_open")
        self.assertEqual(result["pending"], [])
        self.assertEqual(result["pending_detail_descriptors"], ["D003668"])
        self.assertEqual(len(result["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
