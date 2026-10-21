# Status

Mirrors the Status section of the design doc. Updated at the end of every session.

| Milestone | Status |
| --- | --- |
| M0 Setup: repo, local stack, CI | In progress |
| M1 Model gateway, router and fitness check | Not started |
| M2 Agent runtime, sandbox and branches | Not started |
| M3 Orchestrator, task graph and adaptive modes | Not started |
| M4 Human in the loop: questions, Liaison, pause and resume | Not started |
| M5 Mission control v1 | Not started |
| M6 Memory, document RAG and Scribe | Not started |
| M7 Full roster and integrations | Not started |
| M8 Quality: prompt, chaos and outcome tests | Not started |
| M9 Polish and launch | Not started |

## M0 done when

- [x] Repo skeleton, packaging with uv, strict typing and linting
- [x] Local stack: Temporal, PostgreSQL + pgvector, Redis
- [x] `devokdev doctor` and `devokdev smoke`
- [x] CI: lint, types, unit tests, integration tests on the real stack, secret scan, dependency audit
- [x] AGENTS.md, Copilot pointer, design export, ADRs, M0 walkthrough
- [ ] Ved runs it on his machine: `make doctor` all ok, `make smoke` succeeds
- [ ] `uv.lock` generated and committed; first pull request green on GitHub
