"""The smoke-test activity: the simplest possible side effect.

Activities are where real work happens in Temporal. They may do I/O, they can
fail, and Temporal retries them according to the policy the workflow sets.
"""

from __future__ import annotations

from dataclasses import dataclass

from temporalio import activity


@dataclass(frozen=True, slots=True)
class GreetInput:
    name: str


def build_greeting(name: str, attempt: int) -> str:
    """Pure helper, unit-tested without Temporal."""
    cleaned = " ".join(name.split()) or "stranger"
    return f"Namaste, {cleaned}! Devo-K-Dev's stack is alive (activity attempt {attempt})."


@activity.defn
async def greet(params: GreetInput) -> str:
    info = activity.info()
    activity.logger.info("greeting %s", params.name)
    return build_greeting(params.name, info.attempt)
