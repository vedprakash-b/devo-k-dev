"""The `devokdev` command line.

  devokdev version   print the version
  devokdev doctor    check that the local stack and configuration are healthy
  devokdev smoke     run a tiny Temporal workflow end to end
  devokdev models    model registry, router and fitness check (M1; see cli_models.py)
Later milestones add new, status, pause, resume and replay.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from devokdev import __version__
from devokdev.cli_models import models_app
from devokdev.config import get_settings
from devokdev.health.probes import default_checks
from devokdev.health.runner import CheckResult, Status, exit_code, run_checks
from devokdev.telemetry.logging import configure_logging

app = typer.Typer(
    name="devokdev",
    help="Devo-K-Dev: an AI engineering team on durable execution.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(models_app)
console = Console()

_STYLE = {Status.OK: "green", Status.WARN: "yellow", Status.FAIL: "red"}


@app.callback()
def main() -> None:
    """Runs before every command."""
    configure_logging(get_settings())


@app.command()
def version() -> None:
    """Print the Devo-K-Dev version."""
    console.print(f"devokdev {__version__}")


def render_results(results: list[CheckResult]) -> Table:
    table = Table(title="Devo-K-Dev doctor", show_lines=False)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    table.add_column("ms", justify="right")
    for r in results:
        style = _STYLE[r.status]
        table.add_row(
            r.name, f"[{style}]{r.status.value}[/{style}]", r.detail, f"{r.duration_ms:.0f}"
        )
    return table


@app.command()
def doctor(
    timeout: Annotated[
        float, typer.Option(min=0.5, help="Seconds each check may take before it fails.")
    ] = 5.0,
) -> None:
    """Check Python, Docker, PostgreSQL + pgvector, Redis, Temporal and provider keys."""
    settings = get_settings()
    results = asyncio.run(
        run_checks(default_checks(settings), timeout_s=timeout, secrets=settings.secret_values())
    )
    console.print(render_results(results))
    code = exit_code(results)
    if code == 0:
        console.print("[green]All required checks passed.[/green]")
    else:
        console.print("[red]Some checks failed. Is the stack running? Try: make up[/red]")
    raise typer.Exit(code)


@app.command()
def smoke(
    name: Annotated[str, typer.Option(help="Who the smoke workflow should greet.")] = "Ved",
) -> None:
    """Run a one-activity Temporal workflow to prove the durable-execution stack works."""
    from devokdev.runtime.smoke import run_smoke

    settings = get_settings()
    result = asyncio.run(run_smoke(settings, name))
    console.print(f"[green]{result.greeting}[/green]")
    console.print(
        f"See it in the Temporal UI: {settings.temporal_ui_url}/namespaces/"
        f"{settings.temporal_namespace}/workflows/{result.workflow_id}"
    )


if __name__ == "__main__":
    app()
