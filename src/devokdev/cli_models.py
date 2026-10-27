"""`devokdev models ...`: inspect the registry, check providers, profile models, try the router.

devokdev models list [--role ROLE]     every model, or the ranking for one role and why
devokdev models discover               what each provider serves vs the registry
devokdev models profile [MODEL ...]    run the fitness probes and cache the results
devokdev models chat "PROMPT"          route one prompt and show every decision
devokdev models demo                   the router's fallback story, offline, no keys
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Literal

import httpx
import typer
from rich.console import Console
from rich.table import Table

from devokdev.config import Settings, get_settings
from devokdev.llm.messages import CompletionRequest, Message
from devokdev.llm.registry import Registry, RegistryError, RoleClass
from devokdev.router.router import AllModelsUnavailable, Decision, Event

models_app = typer.Typer(
    name="models",
    help="Model registry, router and fitness check.",
    no_args_is_help=True,
)
console = Console()


@models_app.callback()
def _models(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Also print the router's structured logs.")
    ] = False,
) -> None:
    """These commands print routing decisions themselves; logs only add noise."""
    if not verbose:
        from devokdev.telemetry.logging import configure_logging

        settings = get_settings()
        configure_logging(settings.model_copy(update={"log_level": "WARNING"}))


_CLASS_LETTER = {
    RoleClass.REASONING: "R",
    RoleClass.CODING: "C",
    RoleClass.REVIEW: "Rv",
    RoleClass.VISION: "V",
    RoleClass.LIGHT: "L",
}


def _load_registry(settings: Settings) -> Registry:
    try:
        return Registry.load(settings.models_file)
    except RegistryError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None


def _yes(flag: bool) -> str:
    return "[green]yes[/green]" if flag else "[dim]-[/dim]"


def _ago(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


def _decision_line(decision: Decision) -> str:
    colour = {
        Event.OK: "green",
        Event.FAIL: "red",
        Event.SKIP: "yellow",
        Event.REPAIR: "yellow",
        Event.USE: "cyan",
    }[decision.event]
    return f"  [{colour}]•[/{colour}] {decision.describe()}"


# ------------------------------------------------------------------ list


@models_app.command("list")
def list_models(
    role: Annotated[
        str | None, typer.Option(help="Show the ranking for this role, with reasons.")
    ] = None,
) -> None:
    """Every model in the registry, or how the router would rank them for one role."""
    settings = get_settings()
    registry = _load_registry(settings)
    asyncio.run(_list(settings, registry, role))


async def _list(settings: Settings, registry: Registry, role: str | None) -> None:
    from devokdev.router.factory import open_router
    from devokdev.router.policy import RouteRequest

    async with open_router(settings, registry=registry) as ctx:
        if role is not None:
            try:
                plan = await ctx.router.plan(
                    RouteRequest(role=role, est_input_tokens=1000, max_output_tokens=1024)
                )
            except KeyError as exc:
                console.print(f"[red]{exc.args[0]}[/red]")
                raise typer.Exit(1) from None
            table = Table(title=f"Ranking for role {role!r} (state: {ctx.state_backend})")
            for column in ("#", "Model", "Tier", "Quota left", "Trains"):
                table.add_column(column)
            for i, c in enumerate(plan.candidates, start=1):
                table.add_row(
                    str(i),
                    c.model.id,
                    str(c.tier),
                    f"{c.headroom:.0%}",
                    _yes(c.model.trains_on_prompts),
                )
            console.print(table)
            skipped = Table(title="Not eligible", show_header=True)
            skipped.add_column("Model")
            skipped.add_column("Why")
            for e in plan.excluded:
                skipped.add_row(e.model_id, f"{e.reason.value} {e.detail}".strip())
            console.print(skipped)
            return

        usable = ctx.gateway.usable_ids()
        snapshot = await ctx.gateway.snapshot(list(registry.models.values()))
        now = ctx.gateway.clock()
        table = Table(title=f"Model registry: {registry.source} (state: {ctx.state_backend})")
        for column in (
            "Model",
            "Context",
            "Tools",
            "JSON",
            "Vision",
            "Trains",
            "Key",
            "State",
            "Tiers",
        ):
            table.add_column(column)
        for model in registry.models.values():
            health = snapshot.health.get(model.id)
            benched = health.benched_until(now) if health else None
            if benched is not None and health is not None:
                why = health.cooldown_reason or "breaker open"
                state = f"[yellow]benched {_ago(benched - now)} ({why})[/yellow]"
            else:
                state = "[green]ready[/green]" if model.id in usable else "[dim]-[/dim]"
            tiers = " ".join(
                f"{_CLASS_LETTER[c]}{t}" for c, t in sorted(model.tiers.items()) if t > 0
            )
            table.add_row(
                model.id,
                f"{model.context_window // 1024}k",
                _yes(model.tools),
                _yes(model.json_mode),
                _yes(model.vision),
                _yes(model.trains_on_prompts),
                _yes(model.id in usable),
                state,
                tiers,
            )
        console.print(table)
        providers = sorted({m.provider for m in registry.models.values() if m.id in usable})
        console.print(
            f"{len(usable)} of {len(registry.models)} models usable"
            + (f" (keys for: {', '.join(providers)})" if providers else ". Add keys to .env.")
        )
        console.print("[dim]Tiers: R reasoning, C coding, Rv review, V vision, L light.[/dim]")


# ------------------------------------------------------------------ discover


@models_app.command()
def discover() -> None:
    """Compare what each provider serves today with config/models.yaml."""
    settings = get_settings()
    registry = _load_registry(settings)

    async def run() -> None:
        from devokdev.fitness.discovery import discover as discover_all
        from devokdev.router.factory import open_router

        async with open_router(settings, registry=registry, use_redis=False) as ctx:
            reports = await discover_all(ctx.gateway)
        for report in reports:
            if report.status == "no_key":
                console.print(f"[dim]{report.provider}: no key, skipped[/dim]")
                continue
            if report.status == "not_supported":
                console.print(f"[dim]{report.provider}: has no model listing; check its docs[/dim]")
                continue
            if report.status == "error":
                console.print(f"[red]{report.provider}: {report.error}[/red]")
                continue
            console.print(
                f"[bold]{report.provider}[/bold]: serves {len(report.served)} models, "
                f"{len(report.registered) - len(report.missing)} of {len(report.registered)} "
                "registered ones found"
            )
            for name in report.missing:
                console.print(
                    f"  [red]missing[/red] {name} (renamed or withdrawn? fix models.yaml)"
                )
            for name in report.new[:15]:
                console.print(f"  [yellow]new[/yellow] {name}")
            if len(report.new) > 15:
                console.print(f"  [dim]… and {len(report.new) - 15} more[/dim]")

    asyncio.run(run())


# ------------------------------------------------------------------ profile


@models_app.command()
def profile(
    models: Annotated[
        list[str] | None, typer.Argument(help="Model IDs; default: every usable model.")
    ] = None,
    depth: Annotated[
        str, typer.Option(help="quick (2k and 8k recall) or full (up to 64k).")
    ] = "quick",
    force: Annotated[
        bool, typer.Option(help="Re-profile even if a fresh profile is cached.")
    ] = False,
    sandbox: Annotated[bool, typer.Option(help="Run the code-fix probe in Docker.")] = True,
) -> None:
    """Run the fitness probes on each model and cache the results."""
    if depth not in ("quick", "full"):
        console.print("[red]--depth must be quick or full[/red]")
        raise typer.Exit(2)
    settings = get_settings()
    registry = _load_registry(settings)
    chosen_depth: Literal["quick", "full"] = "full" if depth == "full" else "quick"
    asyncio.run(_profile(settings, registry, models or [], chosen_depth, force, sandbox))


async def _profile(
    settings: Settings,
    registry: Registry,
    model_ids: list[str],
    depth: Literal["quick", "full"],
    force: bool,
    use_sandbox: bool,
) -> None:
    from datetime import UTC, datetime

    from devokdev.fitness.profile import ModelProfile, ProfileStore, profile_model
    from devokdev.fitness.sandbox import DockerSandbox
    from devokdev.router.factory import open_router

    store = ProfileStore(settings.data_dir)
    usable = {m.id for m in registry.usable_models(settings)}
    targets = model_ids or sorted(usable)
    if not targets:
        console.print(
            "[yellow]No provider keys yet, so there is nothing to profile.[/yellow]\n"
            "Add at least one key to .env (see docs/learning/M1.md, 'Getting free keys'), "
            "then run this again. Meanwhile, try: devokdev models demo"
        )
        raise typer.Exit(1)
    unknown = [m for m in targets if m not in registry.models]
    if unknown:
        console.print(f"[red]Unknown models: {', '.join(unknown)}. See: devokdev models list[/red]")
        raise typer.Exit(1)

    box: DockerSandbox | None = None
    if use_sandbox:
        candidate = DockerSandbox()
        ok, detail = await candidate.available()
        if ok:
            box = candidate
        else:
            console.print(f"[yellow]Code-fix probe skipped: {detail}[/yellow]")

    results: list[ModelProfile] = []
    async with open_router(settings, registry=registry) as ctx:
        for model_id in targets:
            if model_id not in usable:
                console.print(f"[dim]{model_id}: no key, skipped[/dim]")
                continue
            cached = store.load(model_id)
            fingerprint = registry.model(model_id).fingerprint()
            if cached and not force and cached.is_fresh(fingerprint, datetime.now(UTC)):
                console.print(f"[dim]{model_id}: cached profile is fresh (use --force)[/dim]")
                results.append(cached)
                continue
            console.print(f"Profiling [bold]{model_id}[/bold] ({depth})…")
            started = time.perf_counter()
            result = await profile_model(ctx.gateway, model_id, depth, box)
            path = store.save(result)
            console.print(f"  done in {time.perf_counter() - started:.0f}s → {path}")
            results.append(result)

    def cell(p: ModelProfile, name: str) -> str:
        score = p.score(name)
        if score is None:
            return "[dim]n/a[/dim]"
        colour = "green" if score >= 0.999 else "yellow" if score >= 0.5 else "red"
        return f"[{colour}]{score:.2f}[/{colour}]"

    table = Table(title="Fitness profiles")
    for column in (
        "Model",
        "Status",
        "Instr",
        "JSON",
        "Tools",
        "Code",
        "Recall",
        "TTFT ms",
        "tok/s",
        "Overall",
    ):
        table.add_column(column)
    for p in results:
        table.add_row(
            p.model_id,
            p.status,
            cell(p, "instructions"),
            cell(p, "json"),
            cell(p, "tool_call"),
            cell(p, "code_fix"),
            cell(p, "recall"),
            f"{p.ttft_ms:.0f}" if p.ttft_ms is not None else "-",
            f"{p.tokens_per_s:.0f}" if p.tokens_per_s is not None else "-",
            f"{p.overall:.2f}" if p.overall is not None else "-",
        )
    console.print(table)


# ------------------------------------------------------------------ chat


@models_app.command()
def chat(
    prompt: Annotated[str, typer.Argument(help="What to ask.")],
    role: Annotated[str, typer.Option(help="Which role's models to use.")] = "liaison",
    simulate_429: Annotated[
        bool,
        typer.Option(
            "--simulate-429",
            help="Fail the first call with a fake 429 to watch the fallback (in-memory state).",
        ),
    ] = False,
    private: Annotated[
        bool, typer.Option(help="Treat the prompt as private: no providers that train.")
    ] = False,
) -> None:
    """Route one prompt through the router and show every decision it made."""
    settings = get_settings()
    registry = _load_registry(settings)

    async def run() -> int:
        from devokdev.llm.scripted import InjectFaults
        from devokdev.router.factory import open_router

        transport: httpx.AsyncBaseTransport | None = None
        if simulate_429:
            transport = InjectFaults(httpx.AsyncHTTPTransport())
        request = CompletionRequest(
            messages=(
                Message.system("You are a concise, helpful assistant."),
                Message.user(prompt),
            ),
            max_output_tokens=800,
        )
        async with open_router(
            settings, registry=registry, transport=transport, use_redis=not simulate_429
        ) as ctx:
            try:
                session = ctx.router.session(role, private_data=private)
            except KeyError as exc:
                console.print(f"[red]{exc.args[0]}[/red]")
                return 2
            try:
                routed = await session.complete(request)
            except AllModelsUnavailable as exc:
                console.print(f"[red]{exc}[/red]")
                for decision in exc.decisions:
                    console.print(_decision_line(decision))
                if exc.retry_at:
                    console.print(f"Earliest retry in {_ago(exc.retry_at - time.time())}.")
                if all(e.reason.value == "no_key" for e in exc.excluded):
                    console.print("Add a provider key to .env, or try: devokdev models demo")
                return 1
        console.print(routed.result.message.content or "")
        console.print()
        console.print(f"[dim]Router decisions (state: {ctx.state_backend}):[/dim]")
        for decision in routed.decisions:
            console.print(_decision_line(decision))
        usage = routed.result.usage
        console.print(
            f"[dim]{routed.model_id} · {usage.input_tokens} in / {usage.output_tokens} out"
            f"{' (estimated)' if usage.estimated else ''} · first token "
            f"{routed.result.ttft_ms or 0:.0f} ms · total {routed.result.duration_ms:.0f} ms[/dim]"
        )
        return 0

    raise typer.Exit(asyncio.run(run()))


# ------------------------------------------------------------------ demo


@models_app.command()
def demo() -> None:
    """Watch a 429 hand a live conversation to another model. Offline, no keys needed."""
    from devokdev.router.demo import DemoTurn, run_demo

    settings = get_settings()
    registry = _load_registry(settings)

    def show(turn: DemoTurn) -> None:
        console.rule(turn.title)
        console.print(f"[bold]You:[/bold] {turn.prompt}")
        for decision in turn.routed.decisions:
            console.print(_decision_line(decision))
        message = turn.routed.result.message
        if message.tool_calls:
            calls = ", ".join(f"{c.name}({c.arguments})" for c in message.tool_calls)
            console.print(f"[bold]{turn.routed.model_id}:[/bold] calls {calls}")
        else:
            console.print(f"[bold]{turn.routed.model_id}:[/bold] {message.content}")
        if turn.note:
            console.print(f"[dim]{turn.note}[/dim]")

    console.print(
        "[dim]Scripted providers and a fake clock: no network, no keys, nothing is sent.[/dim]"
    )
    try:
        asyncio.run(run_demo(registry, settings, on_turn=show))
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
