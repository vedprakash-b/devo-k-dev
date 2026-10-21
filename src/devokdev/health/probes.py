"""The probes `devokdev doctor` runs against the local stack.

Each probe answers one question, quickly, and explains a failure in words a
person can act on. Imports of client libraries happen inside the probes so the
CLI starts fast and a missing optional tool only affects its own check.
"""

from __future__ import annotations

import asyncio
import shutil
import sys

from devokdev.config import Settings
from devokdev.health.runner import HealthCheck, Outcome, Status

MIN_PYTHON = (3, 12)


async def check_python() -> Outcome:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info[:2] < MIN_PYTHON:
        return Outcome(Status.FAIL, f"Python {version}; Devo-K-Dev needs 3.12 or newer")
    return Outcome(Status.OK, f"Python {version}")


async def check_docker() -> Outcome:
    """Docker runs the local stack now and the agent sandboxes from M2."""
    docker = shutil.which("docker")
    if docker is None:
        return Outcome(Status.FAIL, "docker CLI not found; install Docker Desktop with WSL2")
    process = await asyncio.create_subprocess_exec(
        docker,
        "info",
        "--format",
        "{{.ServerVersion}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        reason = stderr.decode(errors="replace").strip().splitlines()
        hint = reason[-1] if reason else "daemon not reachable"
        return Outcome(
            Status.FAIL, f"Docker daemon not reachable ({hint}); is Docker Desktop running?"
        )
    return Outcome(Status.OK, f"Docker Engine {stdout.decode().strip()}")


def make_postgres_check(settings: Settings) -> HealthCheck:
    async def probe() -> Outcome:
        import psycopg

        if not settings.postgres_password.get_secret_value():
            return Outcome(
                Status.FAIL, "DEVOKDEV_POSTGRES_PASSWORD is empty; copy .env.example to .env"
            )
        async with await psycopg.AsyncConnection.connect(
            settings.postgres_conninfo(), connect_timeout=3
        ) as conn:
            cursor = await conn.execute("SHOW server_version")
            server = await cursor.fetchone()
            cursor = await conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
            vector = await cursor.fetchone()
        version = server[0] if server else "unknown"
        if vector is None:
            return Outcome(
                Status.FAIL, f"PostgreSQL {version}, but the pgvector extension is missing"
            )
        return Outcome(Status.OK, f"PostgreSQL {version}, pgvector {vector[0]}")

    return HealthCheck("PostgreSQL + pgvector", probe)


def make_redis_check(settings: Settings) -> HealthCheck:
    async def probe() -> Outcome:
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, socket_connect_timeout=3)
        try:
            await client.ping()
            info = await client.info("server")
        finally:
            await client.aclose()
        return Outcome(Status.OK, f"Redis {info.get('redis_version', 'unknown')}")

    return HealthCheck("Redis", probe)


def make_temporal_check(settings: Settings) -> HealthCheck:
    async def probe() -> Outcome:
        from temporalio.client import Client

        client = await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace
        )
        healthy = await client.service_client.check_health()
        if not healthy:
            return Outcome(
                Status.FAIL, f"Temporal at {settings.temporal_address} reports unhealthy"
            )
        return Outcome(
            Status.OK,
            f"Temporal at {settings.temporal_address}, UI {settings.temporal_ui_url}",
        )

    return HealthCheck("Temporal", probe)


def make_provider_keys_check(settings: Settings) -> HealthCheck:
    """Only a warning: keys are not needed until M1."""

    async def probe() -> Outcome:
        providers = settings.configured_providers()
        if not providers:
            return Outcome(Status.WARN, "no model provider keys yet (needed from M1)")
        return Outcome(Status.OK, f"{len(providers)} configured: {', '.join(providers)}")

    return HealthCheck("Model provider keys", probe, required=False)


def default_checks(settings: Settings) -> list[HealthCheck]:
    return [
        HealthCheck("Python", check_python),
        HealthCheck("Docker", check_docker),
        make_postgres_check(settings),
        make_redis_check(settings),
        make_temporal_check(settings),
        make_provider_keys_check(settings),
    ]
