"""A minimal locked-down container for running model-written code.

The fitness check asks each model to fix a small bug, then runs the fix against a test.
That is untrusted code, so it never runs on your machine directly (ADR-007). It runs in a
throwaway container with no network, no Linux capabilities, a read-only file system, a
non-root user, and limits on memory, CPU, processes and time.

This is deliberately small. M2 builds the full sandbox (workspaces, git worktrees,
allow-listed package installs); the hardening flags here are the same ones it will use.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass

PYTHON_IMAGE = "python:3.12.13-slim"  # pinned exact tag (ADR-037)

HARDENING = (
    "--network=none",
    "--read-only",
    "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--user=65534:65534",
    "--memory=256m",
    "--memory-swap=256m",
    "--cpus=0.5",
    "--pids-limit=64",
)


@dataclass(frozen=True, slots=True)
class SandboxRun:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class DockerSandbox:
    def __init__(self, image: str = PYTHON_IMAGE, docker: str | None = None) -> None:
        self.image = image
        self.docker = docker or shutil.which("docker")

    def command(self, name: str) -> list[str]:
        if self.docker is None:
            raise RuntimeError("docker CLI not found")
        return [
            self.docker, "run", "--rm", "-i", f"--name={name}", *HARDENING,
            self.image, "python", "-I", "-",
        ]  # fmt: skip

    async def _exec(self, *args: str, stdin: bytes | None = None, timeout_s: float) -> SandboxRun:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout_s)
        except TimeoutError:
            process.kill()
            await process.wait()
            return SandboxRun(-1, "", f"timed out after {timeout_s:g}s", timed_out=True)
        return SandboxRun(
            process.returncode if process.returncode is not None else -1,
            stdout.decode(errors="replace")[-4000:],
            stderr.decode(errors="replace")[-4000:],
        )

    async def available(self) -> tuple[bool, str]:
        """Whether Docker can run the sandbox image, pulling it once if needed."""
        if self.docker is None:
            return False, "docker CLI not found"
        info = await self._exec(self.docker, "info", "--format", "{{.ServerVersion}}", timeout_s=10)
        if not info.passed:
            return False, "Docker daemon not reachable"
        image = await self._exec(self.docker, "image", "inspect", self.image, timeout_s=10)
        if image.passed:
            return True, self.image
        pulled = await self._exec(self.docker, "pull", "--quiet", self.image, timeout_s=300)
        if not pulled.passed:
            return False, f"could not pull {self.image}"
        return True, self.image

    async def run_python(self, code: str, timeout_s: float = 30.0) -> SandboxRun:
        name = f"devokdev-probe-{uuid.uuid4().hex[:12]}"
        result = await self._exec(*self.command(name), stdin=code.encode(), timeout_s=timeout_s)
        if result.timed_out and self.docker is not None:
            # Killing the docker client does not stop the container; remove it by name.
            await self._exec(self.docker, "rm", "--force", name, timeout_s=20)
        return result
