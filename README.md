# Devo-K-Dev

**An AI engineering team.** Give it any engineering job, from a bug fix to a full product, and it
assembles the roles the job needs, asks the questions a good team would ask, shows you a task
graph to approve, then designs, builds, tests, secures and documents the result while you watch
and steer.

> Status: **M0 — setup.** The foundation is in place: local stack, health checks, a durable
> Temporal workflow, CI. Agents arrive from M2. See [docs/STATUS.md](docs/STATUS.md).

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

The full design, with the reasoning and the alternatives, is in [docs/DESIGN.md](docs/DESIGN.md).

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
make check        # lint, strict types, tests
```

Temporal's Web UI is at <http://127.0.0.1:8233>.

## Tech stack

Python 3.12 (async) · Temporal · PostgreSQL 17 + pgvector · Redis · Typer · Pydantic ·
structlog · uv · ruff · mypy (strict) · pytest + Hypothesis · GitHub Actions. React mission
control arrives in M5. Choices and alternatives: [docs/DESIGN.md](docs/DESIGN.md#tech-stack).

## Repository

| Path | What it holds |
| --- | --- |
| `src/devokdev/` | The Python package |
| `deploy/` | Docker Compose stack |
| `tests/` | Unit and integration tests |
| `docs/` | Design, architecture, decisions, status, learning notes |
| `AGENTS.md` | Instructions for coding agents |

## License

[Apache-2.0](LICENSE)
