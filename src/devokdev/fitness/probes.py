"""The fitness probes: short, cheap tests of what a model can actually do.

Each probe sends one or a few small requests and scores the answer from 0 to 1 with
deterministic checks, never by asking another model. Together they take a handful of calls
per model, so a whole registry can be profiled within free quotas.

| Probe | What it checks | How it is scored |
| --- | --- | --- |
| instructions | follows an exact output format | each of three lines right |
| json | returns a JSON object matching a schema | valid object, then valid schema |
| tool_call | picks the right tool with the right arguments | right tool, then right args |
| code_fix | fixes a small bug so a hidden test passes | the test passes in the sandbox |
| recall | finds a fact in the middle of a long text | each length recalled |

Speed (time to first token, tokens per second) is measured from all of these calls.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from devokdev.fitness.sandbox import DockerSandbox
from devokdev.llm.messages import CompletionRequest, CompletionResult, Message, ToolSpec
from devokdev.llm.registry import ModelSpec
from devokdev.llm.tokens import estimate_text_tokens

SUITE_VERSION = "1"
CallFn = Callable[[CompletionRequest], Awaitable[CompletionResult]]
Depth = Literal["quick", "full"]
RECALL_LENGTHS: dict[str, tuple[int, ...]] = {
    "quick": (2_000, 8_000),
    "full": (2_000, 8_000, 32_000, 64_000),
}


@dataclass(frozen=True, slots=True)
class Timing:
    ttft_ms: float | None
    duration_ms: float
    output_tokens: int


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    name: str
    score: float | None  # None when the probe could not run
    detail: str
    timings: tuple[Timing, ...] = field(default=())

    @property
    def passed(self) -> bool:
        return self.score is not None and self.score >= 0.999


def _timing(result: CompletionResult) -> Timing:
    return Timing(result.ttft_ms, result.duration_ms, result.usage.output_tokens)


def strip_fences(text: str) -> str:
    """The body of the first fenced code block, or the text itself if there is none."""
    match = re.search(r"```[a-zA-Z0-9_+-]*\n(.*?)```", text, re.S)
    return (match.group(1) if match else text).strip()


# ------------------------------------------------------------------ instructions


async def probe_instructions(call: CallFn, model: ModelSpec) -> ProbeOutcome:
    request = CompletionRequest(
        messages=(
            Message.user(
                "Reply with exactly three lines and nothing else.\n"
                "Line 1: the word ALPHA in capital letters.\n"
                "Line 2: the number seven written as a word in lowercase.\n"
                "Line 3: the word OMEGA in capital letters."
            ),
        ),
        max_output_tokens=200,
        temperature=0.0,
    )
    result = await call(request)
    lines = [line.strip() for line in (result.message.content or "").strip().splitlines()]
    expected = ["ALPHA", "seven", "OMEGA"]
    hits = sum(1 for got, want in zip(lines, expected, strict=False) if got == want)
    score = hits / 3 if len(lines) == 3 else hits / 6
    detail = "exact" if score == 1 else f"got {lines[:4]!r}"
    return ProbeOutcome("instructions", round(score, 2), detail, (_timing(result),))


# ------------------------------------------------------------------ json


class _Developer(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    languages: list[str] = Field(min_length=3, max_length=3)
    years_experience: int = Field(ge=1, le=20)


async def probe_json(call: CallFn, model: ModelSpec) -> ProbeOutcome:
    request = CompletionRequest(
        messages=(
            Message.user(
                "Return a JSON object describing a fictional developer named Asha, with exactly "
                "these keys: name (a string), languages (an array of exactly 3 strings), "
                "years_experience (an integer from 1 to 20). Return only the JSON object."
            ),
        ),
        max_output_tokens=300,
        temperature=0.0,
        json_mode=model.json_mode,
    )
    result = await call(request)
    raw = result.message.content or ""
    text = strip_fences(raw)
    timings = (_timing(result),)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return ProbeOutcome("json", 0.0, "not valid JSON", timings)
    try:
        _Developer.model_validate(value)
    except ValidationError as exc:
        return ProbeOutcome(
            "json", 0.5, f"valid JSON, wrong shape: {exc.error_count()} errors", timings
        )
    if text != raw.strip():
        return ProbeOutcome("json", 0.9, "correct, but wrapped in a code fence", timings)
    return ProbeOutcome("json", 1.0, "valid and matches the schema", timings)


# ------------------------------------------------------------------ tool calls

WEATHER = ToolSpec(
    name="get_weather",
    description="Current weather for a city.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string"},
            "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
        },
        "required": ["city", "unit"],
    },
)
LIST_DIR = ToolSpec(
    name="list_dir",
    description="List the files in a directory of the project.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
)


async def probe_tool_call(call: CallFn, model: ModelSpec) -> ProbeOutcome:
    if not model.tools:
        return ProbeOutcome("tool_call", None, "registry says no tool calling")
    request = CompletionRequest(
        messages=(Message.user("What is the weather in Bengaluru right now, in celsius?"),),
        tools=(LIST_DIR, WEATHER),
        tool_choice="auto",
        max_output_tokens=300,
        temperature=0.0,
    )
    result = await call(request)
    timings = (_timing(result),)
    calls = result.message.tool_calls
    if not calls:
        return ProbeOutcome("tool_call", 0.0, "answered without calling a tool", timings)
    first = calls[0]
    if first.name != "get_weather":
        return ProbeOutcome("tool_call", 0.0, f"called {first.name}", timings)
    try:
        args = first.parsed_arguments()
    except ValueError:
        return ProbeOutcome("tool_call", 0.5, "right tool, arguments not JSON", timings)
    city_ok = "bengaluru" in str(args.get("city", "")).lower()
    unit_ok = args.get("unit") == "celsius"
    score = 0.5 + 0.25 * city_ok + 0.25 * unit_ok
    detail = "right tool and arguments" if score == 1 else f"right tool, arguments {args}"
    return ProbeOutcome("tool_call", score, detail, timings)


# ------------------------------------------------------------------ code fix

BUGGY_MEDIAN = '''def median(values):
    """Return the median of a non-empty list of numbers."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 0:
        return ordered[middle]
    return ordered[middle]
'''

MEDIAN_TESTS = """
assert median([3, 1, 2]) == 2
assert median([4, 1, 3, 2]) == 2.5
assert median([7]) == 7
assert median([-1, -3]) == -2
assert median([1.5, 2.5, 3.5, 4.5]) == 3.0
print("all tests passed")
"""


async def probe_code_fix(
    call: CallFn, model: ModelSpec, sandbox: DockerSandbox | None
) -> ProbeOutcome:
    if sandbox is None:
        return ProbeOutcome("code_fix", None, "no sandbox (Docker not available)")
    request = CompletionRequest(
        messages=(
            Message.user(
                "This function returns the wrong answer for lists with an even number of "
                "items. Fix it. Reply with only the corrected function in one ```python "
                f"code block.\n\n```python\n{BUGGY_MEDIAN}```"
            ),
        ),
        max_output_tokens=600,
        temperature=0.0,
    )
    result = await call(request)
    timings = (_timing(result),)
    code = strip_fences(result.message.content or "")
    if "def median" not in code:
        return ProbeOutcome("code_fix", 0.0, "no median function in the reply", timings)
    run = await sandbox.run_python(f"{code}\n\n{MEDIAN_TESTS}", timeout_s=30)
    if run.passed:
        return ProbeOutcome("code_fix", 1.0, "fix passes the hidden tests", timings)
    reason = "timed out" if run.timed_out else (run.stderr.strip().splitlines() or ["failed"])[-1]
    return ProbeOutcome("code_fix", 0.0, f"tests failed: {reason[:120]}", timings)


# ------------------------------------------------------------------ recall

_FILLER = (
    "The river ran past the old mill and the mill wheel turned slowly in the current.",
    "Traders arrived at dawn with baskets of mangoes, jackfruit and fresh curry leaves.",
    "A committee met to discuss the drainage plan for the eastern side of the town.",
    "The library kept its rare manuscripts in a cool room behind a heavy teak door.",
    "Students practised the veena in the courtyard while the afternoon light faded.",
    "Engineers measured the load on the bridge twice a year and logged every reading.",
    "The bus to the station left every twenty minutes, except on festival days.",
)


def haystack(tokens: int, needle: str, depth: float = 0.5) -> str:
    """Filler text of about ``tokens`` tokens with ``needle`` placed at ``depth``."""
    sentences: list[str] = []
    used = 0
    index = 0
    while used < tokens:
        sentence = f"Note {index}: {_FILLER[index % len(_FILLER)]}"
        sentences.append(sentence)
        used += estimate_text_tokens(sentence) + 1
        index += 1
    sentences.insert(int(len(sentences) * depth), needle)
    return " ".join(sentences)


def recall_lengths(model: ModelSpec, depth: Depth) -> tuple[list[int], str]:
    """The haystack sizes this model can be tested at, and why larger ones are skipped."""
    ceiling = int(model.context_window * 0.8)
    why = f"context {model.context_window}"
    if model.limits.tpm is not None and int(model.limits.tpm * 0.8) < ceiling:
        ceiling = int(model.limits.tpm * 0.8)
        why = f"{model.limits.tpm} tokens/minute"
    lengths = [n for n in RECALL_LENGTHS[depth] if n <= ceiling]
    return lengths, why


async def probe_recall(call: CallFn, model: ModelSpec, depth: Depth) -> ProbeOutcome:
    lengths, ceiling_reason = recall_lengths(model, depth)
    if not lengths:
        return ProbeOutcome("recall", None, f"too small to test ({ceiling_reason})")
    timings: list[Timing] = []
    recalled: list[int] = []
    for i, length in enumerate(lengths):
        code = f"KESAR-{4207 + i * 113}"
        text = haystack(length, f"The vault code is {code}.")
        request = CompletionRequest(
            messages=(
                Message.user(f"{text}\n\nWhat is the vault code? Answer with the code only."),
            ),
            max_output_tokens=50,
            temperature=0.0,
        )
        result = await call(request)
        timings.append(_timing(result))
        if code in (result.message.content or ""):
            recalled.append(length)
    score = len(recalled) / len(lengths)
    best = max(recalled) if recalled else 0
    tested = "/".join(f"{n // 1000}k" for n in lengths)
    detail = f"recalled at {len(recalled)} of {tested} tokens"
    if len(lengths) < len(RECALL_LENGTHS[depth]):
        detail += f" (larger sizes skipped: {ceiling_reason})"
    return ProbeOutcome("recall", round(score, 2), detail + f"; best {best}", tuple(timings))


def speed(outcomes: Sequence[ProbeOutcome]) -> tuple[float | None, float | None]:
    """Median time to first token (ms) and output tokens per second across all calls."""
    timings = [t for o in outcomes for t in o.timings]
    first = sorted(t.ttft_ms for t in timings if t.ttft_ms is not None)
    ttft = first[len(first) // 2] if first else None
    streaming_ms = sum(max(t.duration_ms - (t.ttft_ms or 0.0), 1.0) for t in timings)
    tokens = sum(t.output_tokens for t in timings)
    rate = round(tokens / (streaming_ms / 1000), 1) if timings and tokens else None
    return ttft, rate
