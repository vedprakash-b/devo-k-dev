"""Run the smoke workflow end to end: connect, start a worker, execute, stop."""

from __future__ import annotations

import uuid

from temporalio.client import Client
from temporalio.worker import Worker

from devokdev.activities.smoke import greet
from devokdev.config import Settings
from devokdev.workflows.smoke import SmokeInput, SmokeResult, SmokeWorkflow


async def run_smoke(settings: Settings, name: str) -> SmokeResult:
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    # A dedicated task queue per run keeps this worker from picking up real work.
    task_queue = f"{settings.temporal_task_queue}-smoke-{uuid.uuid4().hex[:8]}"
    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[SmokeWorkflow],
        activities=[greet],
    ):
        return await client.execute_workflow(
            SmokeWorkflow.run,
            SmokeInput(name),
            id=f"smoke-{uuid.uuid4().hex[:12]}",
            task_queue=task_queue,
        )
