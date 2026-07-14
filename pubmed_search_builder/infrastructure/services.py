"""Named transport policies for the skill's external services."""

from __future__ import annotations

from pubmed_search_builder.infrastructure.transport import RetryPolicy


def ncbi_eutils_policy(rate_limit_per_second: float) -> RetryPolicy:
    return RetryPolicy(
        retries=3,
        initial_backoff_seconds=1.0,
        timeout_seconds=30.0,
        rate_limit_per_second=rate_limit_per_second,
        circuit_failure_threshold=3,
        circuit_cooldown_seconds=120.0,
    )


MESH_RDF_POLICY = RetryPolicy(
    retries=3,
    initial_backoff_seconds=1.0,
    timeout_seconds=30.0,
    rate_limit_per_second=2.0,
    circuit_failure_threshold=3,
    circuit_cooldown_seconds=120.0,
)
MESH_EUTILS_POLICY = RetryPolicy(
    retries=3,
    initial_backoff_seconds=1.0,
    timeout_seconds=30.0,
    rate_limit_per_second=3.0,
    circuit_failure_threshold=3,
    circuit_cooldown_seconds=120.0,
)
REGISTRY_POLICY = RetryPolicy(
    retries=3,
    initial_backoff_seconds=1.0,
    timeout_seconds=30.0,
    rate_limit_per_second=2.0,
    circuit_failure_threshold=3,
    circuit_cooldown_seconds=120.0,
)
