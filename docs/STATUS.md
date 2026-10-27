# Status

Mirrors the Status section of the design doc. Updated at the end of every session.

| Milestone | Status |
| --- | --- |
| M0 Setup: repo, local stack, CI | Done (2026-10-22) |
| M1 Model gateway, router and fitness check | In progress (started 2026-10-26) |
| M2 Agent runtime, sandbox and branches | Not started |
| M3 Orchestrator, task graph and adaptive modes | Not started |
| M4 Human in the loop: questions, Liaison, pause and resume | Not started |
| M5 Mission control v1 | Not started |
| M6 Memory, document RAG and Scribe | Not started |
| M7 Full roster and integrations | Not started |
| M8 Quality: prompt, chaos and outcome tests | Not started |
| M9 Polish and launch | Not started |

## M1 done when

- [x] Canonical messages and one streaming adapter for every OpenAI-compatible provider
- [x] Model registry (`config/models.yaml`), strictly validated, with data policy and limits
- [x] Quota windows, cooldowns and circuit breakers, shared through Redis, with contract tests
- [x] Router: policy with reasons, sticky sessions, fallback, mid-task handoff, output repair,
      decision log; a 429 mid-conversation is survived (unit test and `make demo`)
- [x] Fitness check: discovery, five probes, hardened sandbox for the code fix, cached profiles
- [x] `devokdev models list / discover / profile / chat / demo`; registry check in `doctor`
- [x] Walkthrough `docs/learning/M1.md`; ADRs; architecture and agent guide updated
- [ ] Ved creates free keys and runs `models discover`, `models profile` and
      `models chat --simulate-429` on his machine
- [ ] The M1 pull request is green on GitHub (including Redis and sandbox integration tests)

## M0 done when (finished 2026-10-22)

- [x] Repo skeleton, packaging with uv, strict typing and linting
- [x] Local stack: Temporal, PostgreSQL + pgvector, Redis
- [x] `devokdev doctor` and `devokdev smoke`
- [x] CI: lint, types, unit tests, integration tests on the real stack, secret scan, dependency audit
- [x] AGENTS.md, Copilot pointer, design export, ADRs, M0 walkthrough
- [x] Ved runs it on his machine: `make doctor` all ok, `make smoke` succeeds
- [x] `uv.lock` generated and committed; first pull request green on GitHub
