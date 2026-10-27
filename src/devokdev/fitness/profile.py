"""Profiling a model: run the probes, summarise, and cache the result.

A ``ModelProfile`` is a small JSON file per model under ``<data_dir>/fitness/``. It is
reused until it goes stale: when the probe suite changes (``SUITE_VERSION``), when the
model's registry entry changes (its ``fingerprint``), or after ``MAX_AGE``. Providers
update models behind the same name, so even an unchanged entry is re-profiled every two
weeks.

Probes go through the gateway, so they spend quota like any other call and cannot push a
provider over its limits. When a model runs out of per-minute quota mid-profile (Cerebras
allows five requests a minute), the runner waits for the window to reset, up to a limit,
instead of giving up.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from devokdev.fitness.probes import (
    SUITE_VERSION,
    Depth,
    ProbeOutcome,
    probe_code_fix,
    probe_instructions,
    probe_json,
    probe_recall,
    probe_tool_call,
    speed,
)
from devokdev.fitness.sandbox import DockerSandbox
from devokdev.llm.errors import ErrorKind, ProviderError
from devokdev.llm.messages import CompletionRequest, CompletionResult
from devokdev.router.gateway import Gateway, ModelUnavailableNow
from devokdev.router.policy import SkipReason

MAX_AGE = timedelta(days=14)
MAX_QUOTA_WAIT_S = 75.0  # wait this long at most for a per-minute window to reset
STOP_PROFILING = {ErrorKind.AUTH_FAILED, ErrorKind.QUOTA_EXHAUSTED, ErrorKind.MODEL_UNAVAILABLE}
TRANSIENT = {ErrorKind.SERVER_ERROR, ErrorKind.NETWORK, ErrorKind.RATE_LIMITED}
Sleep = Callable[[float], Awaitable[None]]


class ProbeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    score: float | None
    detail: str


class ModelProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    fingerprint: str
    suite_version: str
    depth: str
    profiled_at: datetime
    status: Literal["ok", "partial", "failed"]
    probes: tuple[ProbeResult, ...]
    ttft_ms: float | None = None
    tokens_per_s: float | None = None

    def score(self, name: str) -> float | None:
        for probe in self.probes:
            if probe.name == name:
                return probe.score
        return None

    @property
    def overall(self) -> float | None:
        scores = [p.score for p in self.probes if p.score is not None]
        return round(sum(scores) / len(scores), 2) if scores else None

    def is_fresh(self, fingerprint: str, now: datetime) -> bool:
        return (
            self.suite_version == SUITE_VERSION
            and self.fingerprint == fingerprint
            and now - self.profiled_at < MAX_AGE
            and self.status != "failed"
        )


class ProfileStore:
    """One JSON file per model. Human-readable and easy to diff or delete."""

    def __init__(self, root: Path) -> None:
        self.root = root / "fitness"

    def path(self, model_id: str) -> Path:
        return self.root / (re.sub(r"[^A-Za-z0-9._-]+", "_", model_id) + ".json")

    def load(self, model_id: str) -> ModelProfile | None:
        path = self.path(model_id)
        if not path.is_file():
            return None
        try:
            return ModelProfile.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            return None  # an old or damaged file is simply re-profiled

    def save(self, profile: ModelProfile) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path(profile.model_id)
        path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        return path


class _StopProfilingError(Exception):
    """The model cannot continue (bad key, daily quota gone); stop probing it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def profile_model(
    gateway: Gateway,
    model_id: str,
    depth: Depth = "quick",
    sandbox: DockerSandbox | None = None,
    sleep: Sleep = asyncio.sleep,
) -> ModelProfile:
    model = gateway.registry.model(model_id)

    async def call(request: CompletionRequest) -> CompletionResult:
        """One probe call: waits out a short quota window, retries one blip, stops on dead ends."""
        retried = False
        for _ in range(4):
            try:
                return await gateway.call(model_id, request)
            except ModelUnavailableNow as unavailable:
                wait = (unavailable.until or 0) - gateway.clock()
                short_wait = 0 < wait <= MAX_QUOTA_WAIT_S
                if unavailable.reason is not SkipReason.NO_QUOTA or not short_wait:
                    reason = f"{unavailable.reason.value} {unavailable.detail}".strip()
                    raise _StopProfilingError(reason) from None
                await sleep(wait + 0.5)
            except ProviderError as error:
                if error.kind in STOP_PROFILING:
                    raise _StopProfilingError(error.kind.value) from None
                if error.kind in TRANSIENT and not retried:
                    retried = True
                    await sleep(1.0)
                    continue
                raise
        raise _StopProfilingError("no quota after waiting")

    probes: list[Callable[[], Awaitable[ProbeOutcome]]] = [
        lambda: probe_instructions(call, model),
        lambda: probe_json(call, model),
        lambda: probe_tool_call(call, model),
        lambda: probe_code_fix(call, model, sandbox),
        lambda: probe_recall(call, model, depth),
    ]
    names = ["instructions", "json", "tool_call", "code_fix", "recall"]
    outcomes: list[ProbeOutcome] = []
    stopped: str | None = None
    for name, run in zip(names, probes, strict=True):
        if stopped is not None:
            outcomes.append(ProbeOutcome(name, None, f"not run: {stopped}"))
            continue
        try:
            outcomes.append(await run())
        except _StopProfilingError as stop:
            stopped = stop.reason
            outcomes.append(ProbeOutcome(name, None, f"stopped: {stop.reason}"))
        except ProviderError as error:
            # A refused request is the model failing the probe; anything else (a timeout, a
            # server error) says nothing about the model, so the probe counts as unmeasured.
            failed_probe = error.kind in (ErrorKind.BAD_REQUEST, ErrorKind.CONTEXT_TOO_LONG)
            detail = f"{error.kind.value}: {error.message[:120]}"
            outcomes.append(ProbeOutcome(name, 0.0 if failed_probe else None, detail))

    ttft, rate = speed(outcomes)
    status: Literal["ok", "partial", "failed"]
    if not any(o.score is not None for o in outcomes):
        status = "failed"
    elif stopped is not None:
        status = "partial"
    else:
        status = "ok"
    return ModelProfile(
        model_id=model_id,
        fingerprint=model.fingerprint(),
        suite_version=SUITE_VERSION,
        depth=depth,
        profiled_at=datetime.now(UTC),
        status=status,
        probes=tuple(ProbeResult(name=o.name, score=o.score, detail=o.detail) for o in outcomes),
        ttft_ms=round(ttft, 1) if ttft is not None else None,
        tokens_per_s=rate,
    )
