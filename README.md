# Devo-K-Dev

**An AI engineering team.** Give it any engineering job, from a bug fix to a full product, and it
assembles the roles the job needs, asks the questions a good team would ask, shows you a task
graph to approve, then designs, builds, tests, secures and documents the result while you watch
and steer.

> Status: **M1 — model router.** Every model call goes through Devo-K-Dev's own router: it
> ranks free models per role, survives rate limits by handing a live conversation to another
> provider, and measures what each model can do. Agents arrive in M2.
> See [docs/STATUS.md](docs/STATUS.md).

## What makes it different

- **A plan per job, approved by you.** The Orchestrator generates a task graph; nothing runs
  until you approve it.
- **Steer a running job.** A Liaison agent answers questions mid-run and turns change requests
  into plan updates. Pause, edit and resume at any time.
- **Does not die.** Built on [Temporal](https://temporal.io) durable execution, with loop
  detection, an escalation ladder and chaos tests that prove recovery.
- **Free to run.** Its own router spreads work across free and open-weight model providers and
  hands a half-finished conversation to another model when a quota runs out.
- **Remembers.** Working, episodic, knowledge and procedural memory, plus a Scribe agent that
  records every decision, mistake and result.

Every design decision, with its reasoning, is recorded in [docs/adr/](docs/adr/).

## The team

Agents are named after figures from Hindu mythology, ranked as in the pantheon: MahaDev
(Orchestrator) directs, with Durga (Troubleshooter) and Saraswati (Technical Writer) at the
top; Nandi (Liaison), Ganesh (Scribe), Hanuman (Researcher), Ganga (Intake) and Aditi (Code
Reviewer) come next; the devas and sages do the specialist work. Technical docs use role names.

## Quick start

Requires Linux or WSL2 Ubuntu, Docker and [uv](https://docs.astral.sh/uv/).
Windows users: follow [docs/SETUP-WINDOWS.md](docs/SETUP-WINDOWS.md) first.

```bash
git clone https://github.com/<you>/devo-k-dev.git && cd devo-k-dev
make setup        # Python 3.12, dependencies, git hooks, .env
make up           # Temporal, PostgreSQL + pgvector, Redis
make doctor       # every required check should say ok
make smoke        # run a durable workflow end to end
make demo         # watch the router survive a 429 mid-conversation (offline, no keys)
make check        # lint, strict types, tests
```

With a free provider key in `.env` (see [docs/learning/M1.md](docs/learning/M1.md#getting-free-keys)):

```bash
uv run devokdev models chat "Explain durable execution in two lines" --simulate-429
uv run devokdev models profile      # measure every model you have a key for
```

Temporal's Web UI is at <http://127.0.0.1:8233>.

## Tech stack

Python 3.12 (async) · Temporal · PostgreSQL 17 + pgvector · Redis (Lua scripts) · httpx ·
Typer · Pydantic · structlog · uv · ruff · mypy (strict) · pytest + Hypothesis · GitHub Actions. React mission
control arrives in M5. Decisions: [docs/adr/](docs/adr/).

## Repository

| Path | What it holds |
| --- | --- |
| `src/devokdev/` | The Python package |
| `config/models.yaml` | Every provider and model the router may use |
| `deploy/` | Docker Compose stack |
| `tests/` | Unit and integration tests |
| `docs/` | Design, architecture, decisions, status, learning notes |
| `AGENTS.md` | Instructions for coding agents |

## License

[Apache-2.0](LICENSE)
