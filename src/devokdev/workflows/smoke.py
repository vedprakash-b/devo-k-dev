"""The smoke-test workflow: proves the Temporal server, a worker and an activity
can talk to each other.

Workflow code is replayed from history after a crash, so it must make the same
decisions every time: no network, no files, no clock, no random numbers. Anything
like that goes in an activity. The sandbox Temporal runs workflows in enforces this.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from devokdev.activities.smoke import GreetInput, greet


@dataclass(frozen=True, slots=True)
class SmokeInput:
    name: str


@dataclass(frozen=True, slots=True)
class SmokeResult:
    greeting: str
    workflow_id: str


@workflow.defn
class SmokeWorkflow:
    @workflow.run
    async def run(self, params: SmokeInput) -> SmokeResult:
        greeting = await workflow.execute_activity(
            greet,
            GreetInput(params.name),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1)),
        )
        return SmokeResult(greeting=greeting, workflow_id=workflow.info().workflow_id)
