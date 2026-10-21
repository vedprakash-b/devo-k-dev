"""End-to-end checks against the real local stack. Run: make test-integration"""

from __future__ import annotations

import pytest

from devokdev.config import Settings
from devokdev.health.probes import default_checks
from devokdev.health.runner import Status, run_checks
from devokdev.runtime.smoke import run_smoke

pytestmark = pytest.mark.integration


async def test_every_required_check_passes() -> None:
    settings = Settings()
    results = await run_checks(default_checks(settings), secrets=settings.secret_values())
    failed = {r.name: r.detail for r in results if r.status is Status.FAIL}
    assert failed == {}


async def test_smoke_workflow_completes_on_the_real_server() -> None:
    result = await run_smoke(Settings(), "integration test")
    assert result.greeting.startswith("Namaste, integration test!")
    assert result.workflow_id.startswith("smoke-")
