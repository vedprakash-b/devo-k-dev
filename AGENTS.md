# AGENTS.md

Guidance for any coding agent (GitHub Copilot, Codex, Cursor) working in this repository.

## What this project is

Devo-K-Dev is an AI engineering team: give it a job, from a bug fix to a full product, and an
Orchestrator (MahaDev) plans a task graph, gets it approved, and runs specialist agents on
Temporal durable execution, routing model calls across free LLM providers.

- Every design decision: [`docs/adr/`](docs/adr/).
- Current milestone and progress: [`docs/STATUS.md`](docs/STATUS.md).
- What exists today and where: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Environment

- Linux or WSL2 Ubuntu, Docker, [uv](https://docs.astral.sh/uv/). Python 3.12 (uv installs it).
- Never develop from a Windows path such as `/mnt/c/...`; keep the repo in the Linux file system.

## Commands

| Task | Command |
| --- | --- |
| First-time setup | `make setup` |
| Start / stop the local stack | `make up` / `make down` |
| Health check | `make doctor` |
| Temporal end-to-end check | `make smoke` |
| Router demo (offline, no keys) | `make demo` |
| Model registry and usable models | `make models` (or `uv run devokdev models list --role backend`) |
| Format and auto-fix | `make fmt` |
| Everything CI runs | `make check` (ruff, ruff format, mypy strict, pytest) |
| Integration tests (everything marked `integration`) | `make up && make test-integration` |

A change is done only when `make check` passes. Add or update tests with every behaviour change.

## Layout

```
src/devokdev/
  config.py        typed settings (DEVOKDEV_* env vars, .env)
  cli.py           Typer CLI: version, doctor, smoke; cli_models.py: `models` commands
  health/          doctor checks: runner (timeouts, redaction) and probes
  llm/             canonical messages, registry, streaming adapter, errors, rate-limit headers
  router/          policy, quota/health state (memory + Redis Lua), gateway, router sessions
  fitness/         model discovery, probes, sandbox for model-written code, cached profiles
  workflows/       Temporal workflows (deterministic code only)
  activities/      Temporal activities (all I/O and side effects)
  runtime/         processes that host workers and start workflows
  telemetry/       structured logging
config/models.yaml every provider and model the router may use; validated on load
deploy/            docker-compose stack and Postgres init scripts
tests/unit/        fast tests, no network except Temporal's test server download
tests/integration/ need `make up`; tests marked `integration` anywhere run with --run-integration
docs/              ARCHITECTURE.md, STATUS.md, adr/, learning/
```

Later milestones add `orchestrator/`, `agents/`, `context/`, `memory/`, `sandbox/` and
more; see `docs/ARCHITECTURE.md`. Do not create them before their milestone.

## Conventions

- Python 3.12, fully typed; `mypy --strict` must pass. Prefer dataclasses or Pydantic models
  over dicts for anything that crosses a module boundary.
- Async I/O everywhere. Workflow code must be deterministic: no I/O, clocks, randomness or
  threads inside `workflows/`; put those in `activities/`.
- Settings come only from `devokdev.config.Settings`. Secrets are `SecretStr` and are
  unwrapped only where used. Never log or print a secret.
- Errors are reported, not swallowed: a failing check or task returns a readable reason.
- Every model call goes through `router` (or, for a named model, `router.gateway.Gateway`),
  never straight to a provider, so quota, health and decisions are recorded.
- Tests never call real providers: use `devokdev.llm.scripted.ScriptedTransport`.
- Router state has two implementations; a behaviour change goes into both and into
  `tests/unit/router/test_state_contract.py`.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `ci:`); every change goes
  through a pull request into `main`.
- New decisions get a row in the design doc's Decision log and an ADR in `docs/adr/` once accepted.

## Do not

- Commit `.env`, keys, tokens or any secret. Gitleaks runs in pre-commit and CI.
- Send employer code, data or credentials anywhere, or to any model endpoint.
- Add a dependency without a reason in the PR description; dependencies are locked in `uv.lock`.
- Unpin GitHub Actions or pre-commit hooks; they are pinned to commit SHAs on purpose.
- Use LangChain, LiteLLM or an agent framework's prebuilt agent loop (ADR-004, ADR-014).
- Copy code or prompts from other projects; study them, then write our own.
