# Architecture decision records

One file per decision. A decision starts as **Proposed** in the design doc's Decision log; when Ved accepts it, its file here becomes the record. A changed decision gets a new ADR that supersedes the old one; old ADRs are never edited except for their status line.

| ADR | Date | Decision | Status |
| --- | --- | --- | --- |
| [ADR-001](ADR-001.md) | 2026-10-13 | Standalone Python system, not built on Copilot or Claude Code runtimes | Accepted |
| [ADR-002](ADR-002.md) | 2026-10-13 | Develop inside WSL2 with Docker Desktop | Accepted |
| ADR-003 | 2026-10-13 | LangGraph for the workflow graph; own agent loop in each node | Superseded by ADR-014 |
| ADR-004 | 2026-10-13 | Own gateway and router over OpenAI-compatible APIs instead of LiteLLM | Proposed |
| [ADR-005](ADR-005.md) | 2026-10-13 | PostgreSQL with pgvector for state; Redis for counters and events; Temporal keeps its own store | Accepted |
| ADR-006 | 2026-10-13 | Git, test runs, scanners and PR creation are plain code, not agents | Superseded by ADR-020 |
| [ADR-007](ADR-007.md) | 2026-10-13 | Hardened Docker sandbox, no network and no secrets by default | Accepted |
| ADR-008 | 2026-10-13 | Free and open-weight models only; no private or employer code to endpoints that train on prompts | Proposed |
| ADR-009 | 2026-10-13 | devokdev-bench plus SWE-bench Verified Mini against mini-SWE-agent | Proposed |
| ADR-010 | 2026-10-13 | OpenTelemetry GenAI conventions; Phoenix locally, Langfuse Cloud for demos | Proposed |
| ADR-011 | 2026-10-13 | Skills and router versions are promoted only through eval gates | Proposed |
| ADR-012 | 2026-10-13 | Dashboard built last | Superseded by ADR-021 |
| ADR-013 | 2026-10-13 | Working name Baton | Superseded by ADR-024 |
| ADR-014 | 2026-10-13 | Temporal for durable orchestration, replacing LangGraph | Proposed |
| ADR-015 | 2026-10-13 | The Orchestrator builds a task graph per job from playbooks; nothing runs before plan approval | Proposed |
| ADR-016 | 2026-10-13 | The Scribe is a separate agent; code captures every event and the Scribe curates the record | Proposed |
| ADR-017 | 2026-10-13 | The Liaison runs concurrently; changes reach the Orchestrator only as signals | Proposed |
| ADR-018 | 2026-10-13 | Ask about outcome-changing decisions; decide and log implementation-only ones; three autonomy levels | Proposed |
| ADR-019 | 2026-10-13 | Four memory tiers with learning triggers and anti-patterns enforced in code | Proposed |
| ADR-020 | 2026-10-13 | A Git and Release agent makes judgment calls; git mechanics stay deterministic tools; one worktree per parallel task | Proposed |
| ADR-021 | 2026-10-13 | Mission control is built alongside the backend, not last | Proposed |
| ADR-022 | 2026-10-13 | Security is one agent plus defaults, not a project theme | Proposed |
| ADR-023 | 2026-10-13 | Chaos tests in CI prove reliability | Proposed |
| ADR-024 | 2026-10-15 | Project name DEVAGANA | Superseded by ADR-033 |
| [ADR-025](ADR-025.md) | 2026-10-15 | Agent names follow the Hindu pantheon's order; goddesses in every tier; line icons, not images of deities | Accepted |
| ADR-026 | 2026-10-15 | Document RAG in v1: Docling, local embeddings, pgvector plus full-text search, reranking, citations | Proposed |
| ADR-027 | 2026-10-15 | Every task is a branch; forks merge back a distilled typed result | Proposed |
| ADR-028 | 2026-10-15 | Model fitness profiles and a pre-flight verdict before plan approval | Proposed |
| ADR-029 | 2026-10-15 | Adaptive execution modes, including single-model staged and a text-action fallback | Proposed |
| ADR-030 | 2026-10-15 | Learning method: I do, we do, you do | Superseded by ADR-034 |
| ADR-031 | 2026-10-15 | Feature backlog with Now, Next and Later; nothing joins Now unless something leaves | Proposed |
| ADR-032 | 2026-10-15 | The repo carries AGENTS.md, a Copilot pointer file and a Markdown export of the design doc | Proposed |
| [ADR-033](ADR-033.md) | 2026-10-15 | Project name Devo-K-Dev, from "Devon ke Dev", a title of MahaDev | Accepted |
| [ADR-034](ADR-034.md) | 2026-10-15 | Claude writes all code; after each stage, a walkthrough of how it works and every decision | Accepted |
| ADR-035 | 2026-10-15 | Code names: repo devo-k-dev; Python package and CLI devokdev | Proposed |
| [ADR-036](ADR-036.md) | 2026-10-22 | M0 runs Temporal's CLI development server (in-memory) in Docker Compose | Proposed |
| [ADR-037](ADR-037.md) | 2026-10-22 | Supply chain: Actions and pre-commit hooks pinned to commit SHAs, images to exact tags, gitleaks binary checksum-verified, uv.lock with hashes, pip-audit in CI | Proposed |
| [ADR-038](ADR-038.md) | 2026-10-22 | CI runs integration tests against the real Compose stack, plus `devokdev doctor`, on every pull request | Proposed |

Rows without a link are Proposed or Superseded and live only in the design doc until accepted. ADR-036 to ADR-038 have files already because M0 put them into effect; they become Accepted when Ved approves them.
