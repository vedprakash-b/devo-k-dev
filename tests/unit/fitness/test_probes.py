"""Probe scoring, tested with canned answers: no network, no models."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from devokdev.fitness.probes import (
    ProbeOutcome,
    Timing,
    haystack,
    probe_code_fix,
    probe_instructions,
    probe_json,
    probe_recall,
    probe_tool_call,
    recall_lengths,
    speed,
    strip_fences,
)
from devokdev.fitness.sandbox import HARDENING, DockerSandbox, SandboxRun
from devokdev.llm.messages import (
    CompletionRequest,
    CompletionResult,
    FinishReason,
    Message,
    ToolCall,
    Usage,
)
from devokdev.llm.tokens import estimate_text_tokens
from tests.support import make_registry

REGISTRY = make_registry()
LARGE = REGISTRY.model("alpha/alpha-large")


def answer(text: str | None = None, *calls: ToolCall) -> CompletionResult:
    return CompletionResult(
        model_id=LARGE.id,
        message=Message.assistant(text, tuple(calls)),
        finish_reason=FinishReason.STOP,
        usage=Usage(input_tokens=10, output_tokens=5),
        ttft_ms=100.0,
        duration_ms=600.0,
    )


class Canned:
    """A call function that returns prepared answers and keeps the requests."""

    def __init__(self, *answers: CompletionResult) -> None:
        self._answers: Iterator[CompletionResult] = iter(answers)
        self.requests: list[CompletionRequest] = []

    async def __call__(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        return next(self._answers)


@pytest.mark.parametrize(
    ("text", "score"),
    [
        ("ALPHA\nseven\nOMEGA", 1.0),
        ("  ALPHA\nseven\nOMEGA\n", 1.0),
        ("ALPHA\nSeven\nOMEGA", 0.67),
        ("Sure! Here you go:\nALPHA\nseven\nOMEGA", 0.0),
    ],
)
async def test_instructions_are_scored_line_by_line(text: str, score: float) -> None:
    outcome = await probe_instructions(Canned(answer(text)), LARGE)
    assert outcome.score == pytest.approx(score, abs=0.01)


@pytest.mark.parametrize(
    ("text", "score"),
    [
        ('{"name": "Asha", "languages": ["Python", "Go", "Rust"], "years_experience": 6}', 1.0),
        (
            '```json\n{"name": "Asha", "languages": ["a", "b", "c"], "years_experience": 3}\n```',
            0.9,
        ),
        ('{"name": "Asha", "languages": ["Python"], "years_experience": 6}', 0.5),
        ("Asha is a developer.", 0.0),
    ],
)
async def test_json_is_scored_for_validity_then_schema(text: str, score: float) -> None:
    canned = Canned(answer(text))
    outcome = await probe_json(canned, LARGE)
    assert outcome.score == score
    assert canned.requests[0].json_mode is True  # alpha-large supports JSON mode


async def test_tool_calls_need_the_right_tool_and_arguments() -> None:
    right = ToolCall(name="get_weather", arguments='{"city": "Bengaluru", "unit": "celsius"}')
    half = ToolCall(name="get_weather", arguments='{"city": "Mumbai", "unit": "kelvin"}')
    wrong = ToolCall(name="list_dir", arguments='{"path": "."}')
    assert (await probe_tool_call(Canned(answer(None, right)), LARGE)).score == 1.0
    assert (await probe_tool_call(Canned(answer(None, half)), LARGE)).score == 0.5
    assert (await probe_tool_call(Canned(answer(None, wrong)), LARGE)).score == 0.0
    assert (await probe_tool_call(Canned(answer("It is sunny")), LARGE)).score == 0.0


class FakeSandbox(DockerSandbox):
    def __init__(self, passes: bool) -> None:
        super().__init__(docker="/usr/bin/docker")
        self.passes = passes
        self.code: list[str] = []

    async def run_python(self, code: str, timeout_s: float = 30.0) -> SandboxRun:
        self.code.append(code)
        return SandboxRun(0 if self.passes else 1, "", "" if self.passes else "AssertionError")


async def test_a_code_fix_passes_only_if_the_hidden_tests_pass_in_the_sandbox() -> None:
    fix = "```python\ndef median(values):\n    return 2.5\n```"
    sandbox = FakeSandbox(passes=True)
    outcome = await probe_code_fix(Canned(answer(fix)), LARGE, sandbox)
    assert outcome.score == 1.0
    assert "assert median([4, 1, 3, 2]) == 2.5" in sandbox.code[0]
    failing = await probe_code_fix(Canned(answer(fix)), LARGE, FakeSandbox(passes=False))
    assert failing.score == 0.0
    assert "AssertionError" in failing.detail


async def test_without_a_sandbox_the_code_fix_is_not_run_at_all() -> None:
    canned = Canned()
    outcome = await probe_code_fix(canned, LARGE, None)
    assert outcome.score is None
    assert canned.requests == []  # no tokens spent on an answer nobody can check


def test_the_sandbox_is_locked_down() -> None:
    command = DockerSandbox(docker="/usr/bin/docker").command("probe-1")
    for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--user=65534:65534"):
        assert flag in command
    assert set(HARDENING) <= set(command)
    assert command[-3:] == ["python", "-I", "-"]


async def test_the_sandbox_reports_a_missing_docker() -> None:
    box = DockerSandbox()
    box.docker = None
    assert await box.available() == (False, "docker CLI not found")


def test_haystacks_hide_the_needle_near_the_requested_size() -> None:
    text = haystack(2000, "The vault code is KESAR-1.")
    assert "KESAR-1" in text
    assert 1900 <= estimate_text_tokens(text) <= 2300


def test_recall_lengths_respect_context_and_per_minute_tokens() -> None:
    lengths, why = recall_lengths(LARGE, "full")  # tpm 8000
    assert lengths == [2000]
    assert "tokens/minute" in why
    lengths, _ = recall_lengths(REGISTRY.model("beta/beta-coder"), "full")  # 65k context
    assert lengths == [2000, 8000, 32000]


async def test_recall_scores_each_length() -> None:
    beta = REGISTRY.model("beta/beta-coder")
    canned = Canned(answer("KESAR-4207"), answer("I don't know"))
    outcome = await probe_recall(canned, beta, "quick")
    assert outcome.score == 0.5
    assert "1 of 2k/8k" in outcome.detail


def test_strip_fences_takes_the_first_block() -> None:
    assert strip_fences("Here:\n```python\nx = 1\n```\nmore") == "x = 1"
    assert strip_fences("plain") == "plain"


def test_speed_uses_the_median_first_token_and_streaming_time() -> None:
    timings = (Timing(100.0, 1100.0, 50), Timing(300.0, 1300.0, 50), Timing(200.0, 1200.0, 50))
    ttft, rate = speed([ProbeOutcome("x", 1.0, "", timings)])
    assert ttft == 200.0
    assert rate == 50.0  # 150 tokens over 3 seconds of streaming
    assert speed([]) == (None, None)
