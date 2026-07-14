"""Injectable standard-library HTTP transport shared by external services."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol


TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
SECRET_PARAMETER_NAMES = frozenset({"api_key", "apikey", "token", "access_token", "authorization"})


class Opener(Protocol):
    def __call__(self, request: urllib.request.Request, timeout: float): ...


class TransportError(RuntimeError):
    def __init__(self, message: str, *, service: str, attempts: int, transient: bool) -> None:
        super().__init__(message)
        self.service = service
        self.attempts = attempts
        self.transient = transient


@dataclass(frozen=True)
class RetryPolicy:
    retries: int = 3
    initial_backoff_seconds: float = 1.0
    timeout_seconds: float = 30.0
    rate_limit_per_second: float = 0.0
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: float = 120.0


@dataclass(frozen=True)
class TransportResponse:
    body: bytes
    attempts: int
    retries: int
    cache_hit: bool = False


def redact_url(url: str) -> str:
    """Redact known secret query values before a URL reaches an error message."""

    parsed = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_pairs = [
        (key, "***" if key.casefold() in SECRET_PARAMETER_NAMES else value)
        for key, value in pairs
    ]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(safe_pairs), parsed.fragment))


def decode_json(body: bytes, *, strict: bool = True) -> object:
    if not body:
        raise ValueError("empty JSON response body")
    return json.loads(body.decode("utf-8"), strict=strict)


class StdlibTransport:
    """Small policy-driven urllib transport.

    Callers inject the opener, clock, and sleeper in tests.  Circuit and pacing
    state is intentionally held per service name so NCBI and MeSH outages do
    not block one another.
    """

    def __init__(
        self,
        *,
        opener: Opener | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        cache: dict[str, bytes] | None = None,
    ) -> None:
        self._opener = opener or urllib.request.urlopen
        self._monotonic = monotonic
        self._sleep = sleeper
        self._cache = cache
        self._next_allowed: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self._circuit_open_until: dict[str, float] = {}

    def request(
        self,
        *,
        service: str,
        url: str,
        params: Mapping[str, str] | None = None,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        policy: RetryPolicy = RetryPolicy(),
        cache_key: str | None = None,
    ) -> TransportResponse:
        if cache_key and self._cache is not None and cache_key in self._cache:
            return TransportResponse(self._cache[cache_key], attempts=0, retries=0, cache_hit=True)

        now = self._monotonic()
        open_until = self._circuit_open_until.get(service, 0.0)
        if open_until > now:
            raise TransportError(
                f"{service} circuit is open until {open_until:.3f}",
                service=service,
                attempts=0,
                transient=True,
            )

        encoded = urllib.parse.urlencode(dict(params or {})).encode("utf-8")
        target = url
        data: bytes | None = None
        if method.upper() == "POST":
            data = encoded
        elif encoded:
            target = f"{url}?{encoded.decode('utf-8')}"
        request = urllib.request.Request(target, data=data, method=method.upper())
        for name, value in (headers or {}).items():
            request.add_header(name, value)

        attempts = 0
        for retry in range(policy.retries + 1):
            rate = policy.rate_limit_per_second
            if rate > 0:
                ready_at = self._next_allowed.get(service, 0.0)
                wait = ready_at - self._monotonic()
                if wait > 0:
                    self._sleep(wait)
            attempts += 1
            failure: Exception | None = None
            try:
                with self._opener(request, timeout=policy.timeout_seconds) as response:
                    body = response.read()
                self._failures[service] = 0
                if policy.rate_limit_per_second > 0:
                    self._next_allowed[service] = self._monotonic() + (1.0 / policy.rate_limit_per_second)
                if cache_key and self._cache is not None:
                    self._cache[cache_key] = body
                return TransportResponse(body, attempts=attempts, retries=retry)
            except urllib.error.HTTPError as exc:
                failure = exc
                transient = exc.code in TRANSIENT_STATUS_CODES
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                message = f"{service} HTTP {exc.code} for {redact_url(target)}: {detail}"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                failure = exc
                transient = True
                message = f"{service} request failed for {redact_url(target)}: {exc}"

            if not transient or retry >= policy.retries:
                failures = self._failures.get(service, 0) + 1
                self._failures[service] = failures
                if transient and failures >= policy.circuit_failure_threshold:
                    self._circuit_open_until[service] = self._monotonic() + policy.circuit_cooldown_seconds
                error = TransportError(message, service=service, attempts=attempts, transient=transient)
                if failure is not None:
                    raise error from failure
                raise error
            self._sleep(policy.initial_backoff_seconds * (2**retry))

        raise AssertionError("unreachable retry loop")
