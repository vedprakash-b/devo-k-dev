from __future__ import annotations

import uuid

from hypothesis import given
from hypothesis import strategies as st
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from devokdev.activities.smoke import GreetInput, build_greeting
from devokdev.workflows.smoke import SmokeInput, SmokeWorkflow


def test_greeting_normalises_whitespace() -> None:
    assert build_greeting("  Ved   Prakash ", 1).startswith("Namaste, Ved Prakash!")


def test_greeting_handles_an_empty_name() -> None:
    assert build_greeting("   ", 2).startswith("Namaste, stranger!")
    assert "attempt 2" in build_greeting("", 2)


@given(name=st.text(), attempt=st.integers(min_value=1, max_value=100))
def test_greeting_always_names_the_attempt(name: str, attempt: int) -> None:
    assert f"attempt {attempt})" in build_greeting(name, attempt)


async def test_workflow_runs_its_activity_and_returns_its_id() -> None:
    """Runs the real workflow on Temporal's in-process test server.

    The first run downloads the test server binary, so it needs internet once.
    The activity is replaced by a stub with the same name: the workflow is under
    test here, not the activity.
    """

    @activity.defn(name="greet")
    async def fake_greet(params: GreetInput) -> str:
        return f"stub hello {params.name}"

    task_queue = f"test-{uuid.uuid4().hex[:8]}"
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue=task_queue,
            workflows=[SmokeWorkflow],
            activities=[fake_greet],
        ),
    ):
        result = await env.client.execute_workflow(
            SmokeWorkflow.run,
            SmokeInput("Ved"),
            id="smoke-test-1",
            task_queue=task_queue,
        )
    assert result.greeting == "stub hello Ved"
    assert result.workflow_id == "smoke-test-1"
