from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Callable

import httpx


RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def _positive_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


@dataclass(frozen=True)
class ProviderRetryPolicy:
    attempts: int
    base_delay_ms: int
    max_delay_ms: int


def retry_policy() -> ProviderRetryPolicy:
    return ProviderRetryPolicy(
        attempts=_positive_int(
            "AI_PROVIDER_RETRY_ATTEMPTS",
            3,
            minimum=1,
            maximum=5,
        ),
        base_delay_ms=_positive_int(
            "AI_PROVIDER_RETRY_BASE_DELAY_MS",
            250,
            minimum=0,
            maximum=5000,
        ),
        max_delay_ms=_positive_int(
            "AI_PROVIDER_RETRY_MAX_DELAY_MS",
            1500,
            minimum=0,
            maximum=10000,
        ),
    )


def _retry_after_ms(response: httpx.Response | None, *, maximum_ms: int) -> int | None:
    if response is None:
        return None
    raw = (response.headers.get("retry-after") or "").strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return min(maximum_ms, max(0, round(seconds * 1000)))


def _delay_ms(policy: ProviderRetryPolicy, retry_number: int, response: httpx.Response | None) -> int:
    provider_delay = _retry_after_ms(response, maximum_ms=policy.max_delay_ms)
    if provider_delay is not None:
        return provider_delay
    if policy.base_delay_ms <= 0:
        return 0
    exponential = policy.base_delay_ms * (2 ** max(0, retry_number - 1))
    return min(policy.max_delay_ms, exponential)


def request_with_retries(
    method: str,
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    json: object | None = None,
    content: bytes | str | None = None,
    retry: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """Run a bounded same-provider HTTP request.

    Retries are deliberately transport/status retries only. This helper never
    changes providers, models, prompts, source material, or academic policy.
    Callers must leave retry=False for provider-side mutations where replay
    could create duplicate durable resources.
    """
    policy = retry_policy()
    attempts = policy.attempts if retry else 1
    last_error: httpx.HTTPError | None = None

    for attempt in range(1, attempts + 1):
        response: httpx.Response | None = None
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    content=content,
                )
        except httpx.HTTPError as exc:
            last_error = exc
            try:
                setattr(exc, "provider_attempts", attempt)
            except Exception:
                pass
            if attempt >= attempts:
                raise
        else:
            response.extensions["provider_attempts"] = attempt
            if response.status_code not in RETRYABLE_STATUS_CODES or attempt >= attempts:
                return response

        delay = _delay_ms(policy, attempt, response)
        if delay > 0:
            sleep(delay / 1000.0)

    if last_error is not None:
        raise last_error
    raise RuntimeError("provider request retry loop ended without a response")


def provider_attempts(response: httpx.Response) -> int:
    try:
        return max(1, int(response.extensions.get("provider_attempts", 1)))
    except (TypeError, ValueError):
        return 1


def provider_error_attempts(exc: BaseException) -> int:
    try:
        return max(1, int(getattr(exc, "provider_attempts", 1)))
    except (TypeError, ValueError):
        return 1


def retry_snapshot() -> dict:
    policy = retry_policy()
    return {
        "same_provider_only": True,
        "attempts": policy.attempts,
        "base_delay_ms": policy.base_delay_ms,
        "max_delay_ms": policy.max_delay_ms,
        "retryable_status_codes": sorted(RETRYABLE_STATUS_CODES),
        "provider_mutation_replay_disabled_by_default": True,
    }
