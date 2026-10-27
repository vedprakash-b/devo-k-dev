"""The fitness sandbox on real Docker: the hardening flags actually hold.

Run: make test-integration (needs Docker; pulls python:3.12.13-slim once).
"""

from __future__ import annotations

import os

import pytest

from devokdev.fitness.sandbox import DockerSandbox

pytestmark = pytest.mark.integration


@pytest.fixture
async def sandbox() -> DockerSandbox:
    box = DockerSandbox()
    ok, detail = await box.available()
    if not ok:
        if os.environ.get("DEVOKDEV_ENV") == "ci":  # CI has Docker: a skip would hide a bug
            pytest.fail(f"Docker sandbox unavailable in CI: {detail}")
        pytest.skip(f"Docker sandbox unavailable: {detail}")
    return box


async def test_correct_code_runs(sandbox: DockerSandbox) -> None:
    run = await sandbox.run_python("print(sum(range(10)))")
    assert run.passed
    assert run.stdout.strip() == "45"


async def test_there_is_no_network(sandbox: DockerSandbox) -> None:
    code = "import socket\nsocket.create_connection(('1.1.1.1', 53), timeout=3)"
    run = await sandbox.run_python(code)
    assert not run.passed
    assert "OSError" in run.stderr or "Network is unreachable" in run.stderr


async def test_the_file_system_is_read_only_and_the_user_is_not_root(
    sandbox: DockerSandbox,
) -> None:
    run = await sandbox.run_python("import os\nprint(os.getuid())\nopen('/etc/evil', 'w')")
    assert not run.passed
    assert run.stdout.strip() == "65534"
    assert "Read-only file system" in run.stderr or "Permission denied" in run.stderr


async def test_runaway_code_is_stopped(sandbox: DockerSandbox) -> None:
    run = await sandbox.run_python("while True:\n    pass", timeout_s=3)
    assert run.timed_out
