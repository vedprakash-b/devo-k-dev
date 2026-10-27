"""The failure table: for each kind of failure, what happens to the model and to the call.

Each rule has two halves:

- **Effects on shared state**, applied by the gateway so every caller sees them: bench the
  model for a while, bench its whole provider, or count a failure toward its breaker.
- **Navigation for this call**, applied by the router: retry the same model once, or move
  on to the next candidate.

| Failure | Bench | Breaker | This call |
| --- | --- | --- | --- |
| rate_limited | retry-after, else 30 s | no | switch |
| quota_exhausted | until reset, else 1 h | no | switch |
| auth_failed | whole provider, 1 h | no | switch |
| model_unavailable | 1 h | no | switch |
| context_too_long | no | no | switch to a larger window |
| bad_request | no | no | switch |
| server_error, network_error | no | yes | retry once, then switch |
| hung_stream | no | yes | switch |
| invalid_output | no | no | repair once, then switch |
"""

from __future__ import annotations

from dataclasses import dataclass

from devokdev.llm.errors import ErrorKind, ProviderError

DEFAULT_RATE_LIMIT_COOLDOWN_S = 30.0
DEFAULT_QUOTA_COOLDOWN_S = 3600.0
UNAVAILABLE_COOLDOWN_S = 3600.0
MAX_RETRY_AFTER_S = 86400.0


@dataclass(frozen=True, slots=True)
class Action:
    bench_s: float | None = None  # bench this model for this long
    bench_provider: bool = False  # bench every model of the provider instead
    breaker_failure: bool = False  # count toward the circuit breaker
    retry_same_once: bool = False  # worth one more try on the same model
    grow_context: bool = False  # the next model needs a bigger context window


def action_for(error: ProviderError) -> Action:
    hint = min(error.retry_after_s, MAX_RETRY_AFTER_S) if error.retry_after_s else None
    match error.kind:
        case ErrorKind.RATE_LIMITED:
            return Action(bench_s=hint or DEFAULT_RATE_LIMIT_COOLDOWN_S)
        case ErrorKind.QUOTA_EXHAUSTED:
            return Action(bench_s=hint or DEFAULT_QUOTA_COOLDOWN_S)
        case ErrorKind.AUTH_FAILED:
            return Action(bench_s=UNAVAILABLE_COOLDOWN_S, bench_provider=True)
        case ErrorKind.MODEL_UNAVAILABLE:
            return Action(bench_s=UNAVAILABLE_COOLDOWN_S)
        case ErrorKind.CONTEXT_TOO_LONG:
            return Action(grow_context=True)
        case ErrorKind.SERVER_ERROR | ErrorKind.NETWORK:
            return Action(breaker_failure=True, retry_same_once=True)
        case ErrorKind.HUNG_STREAM:
            return Action(breaker_failure=True)
        case ErrorKind.BAD_REQUEST | ErrorKind.INVALID_OUTPUT:
            return Action()
