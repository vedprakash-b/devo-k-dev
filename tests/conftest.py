"""Shared pytest setup.

Integration tests need the local stack (`make up`) and are skipped unless
pytest is run with --run-integration, so `make test` works on any machine.
"""

from __future__ import annotations

import pytest


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
