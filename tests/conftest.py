"""Shared pytest setup.

Integration tests need the local stack (`make up`) and are skipped unless
pytest is run with --run-integration, so `make test` works on any machine.

Unit tests are isolated from the machine they run on: the autouse fixture below
removes every DEVOKDEV_* variable, stops Settings from reading `.env`, and clears
the settings cache. This is the M0 lesson: a test that passed locally failed in CI
because CI sets DEVOKDEV_ENV=ci and the test read it. A unit test should depend only
on what it sets itself.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from devokdev.config import Settings, get_settings


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run tests that need the local stack (make up)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(reason="needs the local stack; run with --run-integration")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolated_settings(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Unit tests see no DEVOKDEV_* variables and no .env file. Integration tests do."""
    if request.node.get_closest_marker("integration") is not None:
        yield
        return
    for name in list(os.environ):
        if name.startswith("DEVOKDEV_"):
            monkeypatch.delenv(name)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
