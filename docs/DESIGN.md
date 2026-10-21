<!-- Exported from the living design doc (rev 186). Re-export at the end of every session. -->

# Devo-K-Dev — Design Doc & Project Tracker

Oct 13, 2026 · @Ved

## How we work (read first)

This doc is the single source of truth for Devo-K-Dev: every chat starts by reading it and ends by updating it. If a chat and this doc disagree, the doc wins until we change it.

Why: language models recall the start and end of a long context better than the middle (the "lost in the middle" effect). Instead of fighting that inside one huge chat, we keep chats short and keep state here.

1. One chat per milestone, or per 2–3 hour session. Long chats are where details get lost.
2. Start of a chat: Ved pastes the resume block below. Claude reads Status, the Decision log and the current milestone before doing anything else.
3. During a chat: every decision gets a Decision log row the moment it is made. Code lives in the repo, not in chat history.
4. End of a chat: Claude adds a dated row to the Progress log saying what is done, what is next and what is broken.
5. The repo mirrors this doc in `docs/ARCHITECTURE.md`, `docs/adr/` and `docs/STATUS.md`, so the repo explains itself to recruiters too.

```markdown
Resume Devo-K-Dev
Doc: <link to this doc>
Milestone: M<n> — <name>
Since last session: <what I ran, what broke, error output>
Today's goal: <one sentence>
```

Devo-K-Dev itself uses the same technique: agents keep a structured task-state record instead of relying on long transcripts. Context engineering is a design goal of the project, not only of our workflow.

### How you learn while we build

Claude writes all of the code; Ved does not write any. After each stage, Claude explains how it works and every decision behind it, so Ved can describe and defend any part of the system.

Every stage ends with a walkthrough in five parts:

1. **What was built**, and where it lives in the repo.
2. **How it works**: the path a request takes through the new code, with a diagram when it helps.
3. **Decisions**: what was chosen, the alternatives, and why.
4. **How to check it**: the commands to run and what you should see.
5. **Interview questions** this stage prepares you for, with short answers.

Each walkthrough is saved as `docs/learning/M<n>.md`, so together they become revision notes. Ved runs each stage on his machine, or Claude runs it directly if this chat is linked to the Claude desktop app with the repo folder connected.

### Using this doc with other agents

Not as a link: this doc is a private claude.ai page, so GitHub Copilot or any other agent cannot open it. And a design doc explains *why*; an agent working in the repo also needs to know *how*: commands, conventions, and where things live.

1. **Export** the doc to Markdown (click the doc's name, then Export) and commit it as `docs/DESIGN.md`. Re-exporting becomes the last step of every session.
2. **Add `AGENTS.md`** at the repo root: what the project is, setup and test commands, code conventions, where things live, what not to do, and a pointer to `docs/DESIGN.md`. Copilot in VS Code reads `AGENTS.md` or `.github/copilot-instructions.md` ([VS Code docs](https://code.visualstudio.com/docs/agent-customization/custom-instructions)), and Copilot's coding agent supports `AGENTS.md` alongside `CLAUDE.md` and `GEMINI.md` ([GitHub changelog](https://github.blog/changelog/2025-08-28-copilot-coding-agent-now-supports-agents-md-custom-instructions)).
3. **Add a short `.github/copilot-instructions.md`** that points to `AGENTS.md`, as a fallback for any Copilot surface that reads only that file.
4. **Use a personal Copilot account** for this project, not a work one.

M0 creates all three files.

## Vision

Devo-K-Dev is an AI engineering team. Give it any engineering job, from a bug fix to a full product, and it assembles the roles that job needs, asks the questions a good team would ask, shows you a task graph to approve, then designs, builds, tests, secures and documents the result while you watch and steer.

- **Right-sized team.** The Orchestrator brings in only the roles a job needs: two or three for a bug fix, ten or more for a new product.
- **Plan before work.** Clarifying questions first, then a task graph showing who does what and why. Nothing runs until you approve it.
- **Steer at any time.** A Liaison agent answers questions mid-run and turns change requests into plan updates. Pause, edit and resume whenever you like.
- **Does not die.** Durable execution, loop detection and an escalation ladder keep runs moving or hand them to you with full context.
- **Remembers and learns.** Working, episodic, knowledge and procedural memory; a Scribe agent records every decision, mistake and result.
- **Visible.** A live mission-control UI shows every agent, task and model switch as it happens.
- **Free to run.** A router spreads work across free and open-weight model providers.

The 3-minute demo the project is built around:

1. Ask for "a habit-tracker web app with login". Devo-K-Dev asks five questions (users, sign-in method, data, visual style, where it runs), each with a recommended default.
2. Devo-K-Dev shows the task graph with roles and reasons. You drop one task and approve.
3. Mission control lights up: design, then backend and frontend in parallel, then tests.
4. Mid-run you type "dark theme, and add a streak counter". The Liaison confirms, the Orchestrator replans, and the graph shows the change.
5. A provider runs out of quota and the router hands the conversation to another model; a stuck test loop is caught and escalated.
6. The Security agent finds a missing rate limit and fixes it. The PR arrives with the Scribe's project report.

Resume line: *Built Devo-K-Dev, an AI engineering team that plans with the user, runs a dynamic multi-agent task graph on durable execution, accepts live change requests mid-run, and routes across free LLM providers with mid-task handoff.*

## How Devo-K-Dev differs from CrewAI, MetaGPT and ChatDev

Multi-role agent teams are not new, and any interviewer will know it. Devo-K-Dev's case rests on product decisions and engineering depth around the roles, not on the roles themselves.

| Capability | CrewAI today ([docs](https://docs.crewai.com/en/concepts/flows)) | Devo-K-Dev |
| --- | --- | --- |
| Who designs the workflow | You do, in code: Crews (sequential, or hierarchical with a manager agent) and event-driven Flows | The Orchestrator generates a task graph for each job; you approve or edit it, and it is replanned while running |
| Human input | `@human_feedback` pauses a Flow at points you place in code | Clarifying questions, plan approval, explicit decision rules, live change requests, pause and resume at any time |
| Surviving a crash | `@persist` saves Flow state to SQLite so a run can resume or fork | Durable execution on Temporal: every model and tool call has timeouts and retries, and a crashed worker resumes without losing steps |
| Memory | One unified memory with LLM-inferred scopes and consolidation of near-duplicates ([memory docs](https://docs.crewai.com/concepts/memory)) | Four tiers: working, episodic, knowledge, procedural; skills are written only when a learning trigger fires and kept only if evals hold |
| Seeing the run | `flow.plot()` draws the Flow's structure as HTML | Live mission control: agents, task graph, model switches and decisions as they happen |
| Models | Any provider through its LLM configuration | Quota-aware routing across free providers with mid-task handoff |

MetaGPT and ChatDev are closer to Devo-K-Dev's idea than CrewAI. [MetaGPT](https://github.com/FoundationAgents/MetaGPT) models a software company with product manager, architect, project manager and engineer roles following fixed procedures, summed up as Code = SOP(Team), and launched the MGX product in February 2025. [ChatDev](https://github.com/OpenBMB/ChatDev) began as a virtual software company; ChatDev 2.0, released in January 2026, is a zero-code platform with a visual workflow canvas and human feedback during runs.

What Devo-K-Dev adds to that lineage: a plan generated per job and approved before work starts, live steering of a running job, durable execution that is tested against injected failures, free multi-provider routing, and results measured against baselines.

How to say it in an interview: "Role-based agent teams are a known pattern. I built a production-style system around the pattern and can show where it breaks and how it recovers." Devo-K-Dev could run its agents on CrewAI; it does not, because it needs to own the agent loop for model handoff, budgets and permissions, and it wants Temporal's durability underneath.

## Your requirements, one by one

Every request from the 13 October review maps to a decision and a section, so nothing gets lost between chats.

| # | What you asked | Decision | Where |
| --- | --- | --- | --- |
| 1 | Skill areas were examples, not the brief | Design starts from the product; the security theme, red-team suite and learned router are no longer centrepieces | Vision, Safety basics |
| 2 | CrewAI already does this; what is different? | Honest comparison; the difference is per-job planning, live steering, durability, routing and measured results | How Devo-K-Dev differs |
| 3 | Any job, many roles, like a real engineering team | A role registry; the Orchestrator classifies the job and staffs only the roles it needs | Agent roster, Orchestration |
| 4 | Not a cybersecurity project | One Security agent at the right steps, plus basic sandboxing | Safety basics |
| 5 | All steps from starting to finishing a project | A twelve-step lifecycle with the roles active at each step | Project lifecycle |
| 6 | An agent that records every decision, mistake, feature and who did what | A separate Scribe agent; code captures every event, the Scribe curates them | Agent roster, Memory |
| 7 | An always-present agent for questions and changes mid-run | The Liaison: answers from live state, sends change requests to the Orchestrator | Working with you |
| 8 | Excellent specialist prompts, tested | One prompt anatomy for all roles, informed by open-source projects, tested per role on several models | Prompts, Quality |
| 9 | Never die in loops or failures | Durable execution, loop and no-progress detection, an escalation ladder, chaos tests | Reliability |
| 10 | Stop, change, resume | Pause at safe points, edit the plan, resume from a checkpoint | Working with you |
| 11 | Show the task graph and the agents chosen, with reasons, before starting | A plan gate: nothing runs until you approve the graph | Orchestration |
| 12 | Good questions; design decisions approved by you; equivalent choices decided silently | Decision rules: outcome-changing choices are asked, implementation-only choices are decided and logged | Working with you |
| 13 | Live observability that looks amazing | Mission control UI, built by Claude | Mission control |
| 14 | Working, episodic, knowledge and procedural memory | Four memory tiers behind one memory manager | Memory |
| 15 | Context window handling | Token budgets, compaction, offloading, isolated sub-agent contexts | Context window management |
| 16 | RAG for documents later | Brought forward to M6 at Ved's request; see row 21 | Document RAG |
| 17 | A frontend agent for attractive UI | UI Designer and Frontend Engineer roles with screenshot-based visual review | Agent roster |
| 18 | Agent names come later | Names now proposed; see row 29 | Names and theme |
| 19 | Learning triggers and anti-patterns | Enforced in code by the memory manager | Memory |
| 20 | Integration specialist and Git master | Intake agent for task sources; Git and Release agent | Agent roster, Integrations |
| 21 | RAG for documents, now | Document RAG with Docling, hybrid search, reranking and citations, in M6 | Document RAG |
| 22 | Branches so contexts never get too long | Every task is a branch; forks merge back a distilled result | Context branches |
| 23 | Many more useful features | A ranked backlog: five Now items, the rest Next or Later | Feature backlog |
| 24 | Can other agents such as GitHub Copilot use this doc? | Not as a link: export to docs/DESIGN.md, plus AGENTS.md and a Copilot pointer file | How we work |
| 25 | Why Temporal and not LangGraph? | Side-by-side comparison | Orchestration |
| 26 | Is the build-and-learn plan still the same? | Replaced by row 35: Claude writes all code and explains each stage | How we work |
| 27 | Work with whichever models the user has; one model works in stages | Adaptive modes, including single-model staged execution | Adapting to the models you have |
| 28 | Make sure the models can handle the project before starting | Fitness profiles and a pre-flight verdict at plan approval | Adapting to the models you have |
| 29 | Project name DEVAGANA; agent names from Hindu mythology | Renamed again in row 33; names set in rows 30 to 32 | Names and theme |
| 30 | Names must follow the real hierarchy: Ganesha and Hanuman rank above Indra, and Indra below Shiva and Vishnu; Claude assigns them | MahaDev directs, with Durga and Saraswati at the top; no agent takes direction from a lower-ranked figure | Names and theme |
| 31 | Where are the women, especially Durga? | Seven goddesses and women sages across all three tiers; Durga at the top beside MahaDev | Names and theme |
| 32 | Hanuman belongs to the Ramayana, not Shiva's circle | Moved out of MahaDev's circle; now the Researcher, after his search for Sita | Names and theme |
| 33 | Rename to Devo-K-Dev; Shiva as MahaDev; Ganesha as Ganesh | Renamed throughout; code name devokdev | Names and theme, Repo structure |
| 34 | No optional component names | Components keep plain names | Names and theme |
| 35 | I won't write code; explain each stage to me | Claude writes all code and, after each stage, walks through how it works and every decision | How we work |

## Architecture

&#91;embedded content: Baton architecture · 18 agents, 1 durable workflow, 4 shared services\]

A job arrives from you or a tracker. The Orchestrator plans it inside a durable Temporal workflow and staffs it with specialists, who share the router, sandbox, memory and context managers. Every step becomes an event that reaches mission control and the Scribe.

## Project lifecycle

&#91;embedded content: Project lifecycle · 12 steps, 4 approvals, 1 rework loop\]

A bug fix might run only steps 1, 2, 6, 8, 9, 10, 11 and 12; a new product runs all twelve. The Orchestrator decides which steps a job needs, and the plan you approve at step 6 shows that choice.

## Agent roster

Three agents are always present: the Orchestrator, the Scribe and the Liaison. The Orchestrator brings in specialists only when a job needs them. All names are temporary until you choose your own.

| Agent | What it does | When it is used | Model tier |
| --- | --- | --- | --- |
| Orchestrator | Classifies the job, builds and replans the task graph, assigns roles, watches progress; never writes code | Always | Strongest reasoning model |
| Scribe | Turns the event stream into the project record: decisions, mistakes and fixes, features, who did what and how, tech stack, progress | Always, in the background | Small, cheap model |
| Liaison | Answers your questions from live state; turns change and stop requests into signals for the Orchestrator | Always, on the side | Fast mid-tier model |
| Intake | Pulls jobs from GitHub Issues, Jira or Linear, normalises them, posts status back | When a job comes from a tracker | Small model |
| Analyst | Asks the clarifying questions, writes the brief and acceptance criteria | Every job except trivial fixes | Strong reasoning model |
| Researcher | Compares libraries and approaches; maps an existing codebase | New technology or an existing repo | Mid-tier, long context |
| Architect | System design, tech stack, data model, API contracts, decision records | New projects and large features | Strongest reasoning model |
| UI Designer | User flows, layout, design tokens, component choices | Anything with a UI | Mid-tier, vision-capable |
| Frontend Engineer | Builds the UI and checks it with screenshots | Anything with a UI | Best coding model |
| Backend Engineer | APIs, business logic, data layer | Most jobs | Best coding model |
| Data and ML Engineer | Data pipelines, models, data processing | Jobs with data or ML work | Best coding model |
| DevOps Engineer | Scaffolding, CI/CD, Docker, environments, deployment | New projects and infrastructure changes | Mid-tier coding model |
| QA Engineer | Test strategy, writes and runs tests, sends bugs back to engineers | Every job that changes code | Mid-tier coding model |
| Code Reviewer | Reviews each diff for correctness, design and maintainability | Every job that changes code | A different model family from the author |
| Security Engineer | Reviews the design, scans the code, fixes vulnerabilities | After design and after implementation | Mid-tier, different family |
| Technical Writer | README, API docs, user guide | New projects and user-facing changes | Small or mid-tier model |
| Git and Release | Branches and worktrees, commits, merge conflicts, PRs, changelog, versions | Every job that changes a repo | Mid-tier model |
| Troubleshooter | Fresh-eyes rescue when an agent is stuck; proposes a different approach | Only on escalation | Strongest available model |

**Why the record keeper is its own agent.** The Orchestrator's context has to stay small and focused on control, and the project record must never depend on an agent remembering to write it. So code captures every event automatically (task started, decision made, tool called, error, model switched), and the Scribe turns that stream into readable documents. The Liaison reads those documents to answer you quickly.

**Roles are files.** Each role is a versioned card: capability tags, allowed tools, model policy, budgets, output schema and prompt. The Orchestrator staffs a job by matching its needs to capability tags, so adding a role means adding a file.

**Git work is split.** Commands and pushes run as deterministic tools; the Git and Release agent handles the judgment calls, such as resolving a merge conflict or writing a PR description. Parallel agents each get their own git worktree, and the Git and Release agent merges them through a queue. This replaces the earlier "git is plain code" decision.

**The frontend pair can see its work.** The Frontend Engineer renders pages with Playwright at desktop and mobile sizes, runs axe-core accessibility checks, and has a vision-capable model compare screenshots against the UI Designer's brief, for at most three rounds.

## Names and theme

Devo-K-Dev comes from "Devon ke Dev", god of the gods, a title of MahaDev himself. The team follows a real pantheon: every agent is named after a figure who ranks below, or level with, the one directing it, and goddesses and women sages appear in every tier. MahaDev directs, with Durga and Saraswati beside him at the top. Nandi, Ganesh, Hanuman, Ganga and Aditi come next, above the devas. The devas and sages, with Indra first among the devas, do the specialist work.

&#91;embedded content: Devo-K-Dev hierarchy · 3 tiers, 18 agents\]

| Role | Name | देवनागरी | Why the name fits | UI symbol |
| --- | --- | --- | --- | --- |
| Orchestrator | MahaDev | महादेव | God of the gods; as Nataraja he sets the rhythm every other part moves to, directing and never building | Damaru |
| Troubleshooter | Durga | दुर्गा | When the gods could not defeat Mahishasura, they combined their powers into Durga, and she won; she is called when every other agent has failed | Lion |
| Technical Writer | Saraswati | सरस्वती | Goddess of knowledge, speech and writing | Veena |
| Liaison | Nandi | नन्दी | MahaDev's gatekeeper; devotees whisper their wishes in his ear and he carries them to MahaDev | Bull |
| Scribe | Ganesh | गणेश | Wrote down the Mahabharata as Vyasa dictated, without a pause, as the Scribe follows the event stream | Tusk pen |
| Researcher | Hanuman | हनुमान | Leapt the ocean and found Sita in Lanka after the other search parties came back empty-handed | Mace |
| Intake | Ganga | गंगा | MahaDev caught her torrent in his hair so she reached the earth as a steady river, as Intake turns a flood of requests into a steady stream | River |
| Code Reviewer | Aditi | अदिति | Mother of the devas, including Surya, Varuna, Indra and Pushan: she reviews her children's work | Lotus |
| Analyst | Gargi | गार्गी | The philosopher who questioned the sage Yajnavalkya in King Janaka's court | Scroll |
| Architect | Vishwakarma | विश्वकर्मा | Architect and craftsman of the gods | Compass and square |
| UI Designer | Ushas | उषस् | Goddess of the dawn: the first light and colour people see | Dawn horizon |
| Frontend Engineer | Surya | सूर्य | The sun that makes everything visible | Sun disc |
| Backend Engineer | Prithvi | पृथ्वी | The earth goddess everything stands on | Mountain |
| Data and ML Engineer | Varuna | वरुण | Lord of the waters and of cosmic order | Waves |
| DevOps Engineer | Vayu | वायु | The wind that moves everything and keeps the system breathing | Wind swirl |
| Git and Release | Pushan | पूषन् | Knower of paths and god of meetings ([Pushan](https://en.wikipedia.org/wiki/Pushan)): branches and merges | Forked road |
| Security Engineer | Indra | इन्द्र | King of the devas and defender of heaven against the asuras | Vajra |
| QA Engineer | Agni | अग्नि | Agni pariksha, the trial by fire that every change must pass | Flame |

**Notes on the choices.** Durga's story is the Troubleshooter's job: the gods pooled their powers into her when none of them could win alone, so her agent works in a fresh context with the strongest model available. Hanuman now sits outside MahaDev's circle. Some Shaiva texts do call him a form of Rudra, but his story is the Ramayana, and the search for Sita makes him the Researcher. Seven of the eighteen are goddesses or women sages: Durga, Saraswati, Ganga, Aditi, Gargi, Ushas and Prithvi. Traditions differ on rank, so this follows the common popular order: MahaDev and the great goddesses, then figures such as Ganesh and Hanuman, then Indra and the devas.

**Visual theme.** A night-sky indigo base with snow white and ash grey, and saffron and gold accents. Each agent appears as its symbol in its element's colour: fire orange for Agni, deep blue for Varuna, sky blue for Vayu, earth green for Prithvi, gold for Surya, river teal for Ganga. Names show in English with Devanagari beneath. Symbols are simple line icons rather than images of the deities, which keeps the theme respectful and free of artwork licensing problems; the README and UI describe each name's meaning respectfully. Technical sections keep role names so recruiters can follow them, written as "MahaDev (Orchestrator)" where both help, and components such as mission control and the memory manager keep plain names.

## Orchestration

The Orchestrator is the brain and Temporal is the engine: the Orchestrator decides what should happen, and a Temporal workflow makes sure it happens in order, exactly once, and survives crashes.

### How a task graph is made

1. **Classify the job:** new project, feature, bug fix, refactor, UI redesign, migration, docs, or research spike, plus a size estimate.
2. **Start from a playbook.** Each job type has a template graph, which the Orchestrator adapts to the brief. Playbooks give consistency; adaptation gives flexibility.
3. **Describe every task:** title, role, why that role, inputs, outputs, acceptance criteria, dependencies, estimate and risk.
4. **Validate in code:** the graph has no cycles, every role exists in the registry, every input is produced upstream, and the plan fits the budgets.
5. **Plan gate.** Mission control shows the graph and the team with reasons. You approve, edit (add or drop tasks, reassign roles) or ask the Liaison. Nothing runs before approval.

### How it runs

- A **project workflow** holds the graph and schedules it: a task whose dependencies are done becomes ready and starts as a child **task workflow**, in parallel up to a concurrency limit that respects provider quotas.
- Inside a task workflow, every model call and tool call is a Temporal activity with a timeout, a retry policy and a heartbeat.
- Outputs flow back as typed artifacts. The Orchestrator reviews them at checkpoints (end of a phase, or a failed task) and can replan.
- **Replanning is a graph diff.** A diff that changes the outcome needs your approval; an implementation-only diff is applied and logged.
- **Gates:** design approval, plan approval and release approval (before a PR is merged), each switchable by autonomy level.

| Devo-K-Dev concept | Temporal primitive |
| --- | --- |
| A project run | Workflow |
| A task in the graph | Child workflow |
| A model call or tool call | Activity with timeout, retries and heartbeat |
| Pause, resume, change request | Signal, or Update when the sender needs an acknowledgement |
| The Liaison reading live state | Query |
| Waiting days for your approval | The workflow waits on a signal without holding resources |
| A very long run | Continue-as-new, which keeps the event history small |

Temporal markets exactly this for AI: workflows that resume after a crash, a network timeout or a multi-day wait for human approval, with an approval pattern built on signals ([Temporal Durable AI](https://docs.temporal.io/ai)). The trade-off is a learning curve: workflow code must be deterministic, so every model call lives in an activity. Learning that rule is part of the point.

### Why Temporal, not LangGraph

LangGraph is an agent-graph framework that saves graph state at each step; Temporal is a durable-execution engine for any code. Devo-K-Dev's run is a task graph generated per job, edited by the user mid-run and kept alive for hours, which is Temporal's home ground.

| What Devo-K-Dev needs | LangGraph | Temporal |
| --- | --- | --- |
| A plan that changes shape mid-run | A graph defined in code, with dynamic fan-out inside a fixed topology | Ordinary code: the scheduler walks a task graph it can rebuild at any time |
| Steering a running job from outside | Interrupts pause at points coded into the graph; the run resumes with input | Signals, queries and updates reach a running workflow at any moment, from any process |
| Per-step failure handling | Checkpoint after each step, retry policies on nodes | Timeouts, retries with backoff and heartbeats on every activity, so hung calls are caught |
| Crash recovery | Resume the thread from its last checkpoint ([persistence docs](https://docs.langchain.com/oss/python/langgraph/persistence)) | Another worker picks the run up automatically and replays history to the exact step |
| Scaling out | Your own process, or LangChain's hosted Agent Server | Task queues; add workers on any machine |
| Inspecting a run | Checkpoint history and LangSmith tracing | Temporal Web UI shows every event of every run, locally |
| AI conveniences | Built in: messages, tools, prebuilt agents | None; Devo-K-Dev writes its own agent loop |

The honest costs of Temporal: one more server to run (a single binary in development), determinism rules for workflow code, and more boilerplate. They are not mutually exclusive either: Temporal publishes an integration that runs LangGraph graphs as durable workflows ([Temporal Durable AI](https://docs.temporal.io/ai)). If one agent's internal reasoning ever suits a fixed graph, it can use LangGraph inside a Temporal activity.

## Working with you

You decide anything that changes the outcome; Devo-K-Dev decides anything that only changes the implementation, and logs it so you can review it later.

### Questions before work

- The Analyst asks only questions whose answers change the plan. Anything with a safe default gets that default instead of a question.
- About eight questions at most, grouped by topic, each with options, a recommended default and one line on why it matters. For example: "Sign-in: email and password (recommended, simplest), Google, or none? This changes the backend tasks and the security review."
- An unanswered question takes its recommended default, marked as an assumption in the brief.

### Decision rules

Ask you first:

- Scope, features, and anything a user of the result would notice
- Visual style and user flows
- Language or framework, when you have a preference or it affects you
- Data storage, privacy, paid external services
- Irreversible steps: deleting data, publishing, merging to main

Decide and log:

- Internal structure, naming, file layout
- Choosing between libraries that give the same result
- Test framework, linting, CI details
- Refactors that keep behaviour the same
- Retries, model choices, agent assignments

Agents can propose a better method at any point. If it changes the outcome, the proposal comes to you with a recommendation; otherwise it is applied and logged. An autonomy setting (ask often, balanced, autonomous) shifts these lines; balanced is the default.

### The Liaison

The Liaison runs beside the job and never blocks it. It reads the task graph, the event log, the Scribe's documents and each agent's current activity, then sorts every message you send:

- **Question:** answered from live state, with a pointer to the task concerned.
- **Change request:** turned into a structured change (what, why, priority), confirmed with you, then signalled to the Orchestrator.
- **Control:** pause, stop or resume, signalled straight away.
- **Approval or feedback:** routed to the gate that is waiting for it.

For a change, the Orchestrator works out the impact. Tasks not yet started are edited, running tasks finish or stop at the next safe point, and finished tasks get follow-up rework tasks. You see the graph diff, and approve it when it changes the outcome.

### Pause, change, resume

- **Pause:** agents stop at the next safe point, after the current model or tool call, and state is checkpointed.
- **Stop now:** cancels calls in flight; completed work is kept.
- **While paused:** edit the plan, reassign roles, add instructions to specific tasks, change the autonomy level.
- **Resume:** continues from the checkpoint. Changed tasks restart; unaffected tasks carry on.

Buttons in mission control send these signals directly; typing "pause" to the Liaison does the same.

## Reliability: no dead loops, no lost work

A run either makes progress, escalates, or hands the problem to you with full context. It never spins forever or dies silently, and each mechanism below is tested by causing the failure on purpose.

### Safeguards

- **Durable execution.** A crashed worker's workflow resumes from its history. Side effects such as pushes and PR creation carry idempotency keys, so a retry never repeats them.
- **Hard limits.** Steps per agent run, tokens, wall time, rework loops per task (three), replans per project and total budget. Hitting a limit triggers escalation, not a crash.
- **Timeouts and heartbeats** on every model and tool call. A hung call is detected, retried or replaced.
- **Loop detection.** The same action with the same arguments three times, or oscillation between two states, flags a loop.
- **No-progress detection.** If files changed, tests passing, criteria met and plan steps done all stay flat for several steps, the agent is marked stuck.
- **Output validation.** Structured outputs are schema-checked, with one repair attempt before switching model.
- **Model failures** are handled by the router's fallback and handoff.

### Escalation ladder

1. Retry with the error in context.
2. Switch to another model.
3. The Troubleshooter reviews with a fresh context and proposes a different approach.
4. The Orchestrator replans: splits the task, changes the approach or the role.
5. The Liaison asks you, with a summary and options.
6. The task is parked as blocked and the rest of the graph carries on. One stuck task never stops the project.

### Proving it: chaos tests

A fault-injection suite runs in CI: forced rate limits and quota exhaustion, timeouts, malformed model output, a worker killed mid-task, a dead sandbox, and a scripted agent that loops on purpose. Each test asserts that the run recovers or escalates correctly within budget. "Never dies" becomes a tested property rather than a promise.

## Model layer: gateway and router

Every LLM call goes through Devo-K-Dev's own router, which picks a model by role and difficulty, steers around quota limits, and moves a half-finished conversation to another model when one fails. This is the core component, and we build it ourselves.

The design separates **signals** from **policy**, an idea taken from [vLLM Semantic Router](https://arxiv.org/html/2603.04444v1): measurements about the request and the providers are collected first, then a policy turns them into a decision.

1. **One adapter, many providers.** Almost every free provider speaks the OpenAI-compatible chat API (OpenRouter, Groq, Cerebras, NVIDIA NIM, Mistral, Cloudflare, Gemini's compatibility endpoint, Ollama). Devo-K-Dev keeps conversations in one canonical Pydantic format and converts per provider, handling quirks such as tool-call formats.
2. **Model registry.** A YAML file lists each model's provider, context window, tool-calling support, quality tier per role, rate limits and data policy (whether the provider trains on prompts).
3. **Quota and health tracker.** Redis token buckets per model for requests and tokens per minute and per day, updated passively from rate-limit response headers. A circuit breaker per model opens after repeated errors and half-opens after a cooldown.
4. **Signals.** Agent role, triage difficulty, required context length, tool-calling need, data sensitivity, earlier failures in this task, remaining quota, recent latency.
5. **Policy.** Version 1 is rules: candidates for the role, filtered by capability, context, data policy, health and quota, ranked by role quality then headroom. A learned router that predicts which model will succeed is a later option, once enough runs are logged.
6. **Mid-task handoff.** Because the conversation is stored in the canonical format, a failed call is replayed to the next model. If the new model's context window is smaller, older turns are compacted by a small model while the task-state record and the latest tool results stay verbatim.
7. **Sticky by default.** An agent session keeps its model unless something breaks, and switches back after a cooldown only at a step boundary. Switching mid-session costs consistency and prompt-cache hits.

| Failure | How it is detected | What the router does |
| --- | --- | --- |
| Rate limit | HTTP 429 and the retry-after header | Cool down that model, switch, retry |
| Daily quota used up | 429 body or local counters | Mark the model exhausted until its reset time |
| Credits or access gone | HTTP 402 or 403 | Treat as quota exhausted |
| Server or network error | 5xx, connection reset | Retry with jitter, count toward the circuit breaker, then switch |
| Hung stream | No first token before a deadline (configurable) | Abort and switch |
| Context too long | Context-length error | Compact, or choose a larger-context model |
| Broken tool calls | Schema validation fails twice | One repair prompt, then switch model |
| Every model exhausted | No candidate left | Use a local Ollama model, or park the task until the earliest quota reset |

How Devo-K-Dev uses several models well, not just one at a time:

- **By role:** strong reasoning for planning, the best coder for edits, small models for triage and summaries.
- **Cascade:** start mid-tier and escalate only after a failure, the FrugalGPT pattern.
- **Best-of-N:** for hard tasks, two or three engineer agents on different models work in parallel; the test suite picks the winner, which beats asking models to vote.
- **Cross-family review:** the Code Reviewer comes from a different model family than the author, to reduce models favouring their own output.
- **Local guards:** classifiers such as Prompt Guard 2 run locally and use no API quota.

Every routing decision is a traced span with a reason code, for example `quota_exhausted → switched to cerebras/gpt-oss-120b`, and the dashboard shows the decision log. Using several providers each within its free tier is fine; rotating many accounts on one provider breaks terms of service, so Devo-K-Dev does not do it. Fallback chains, cooldowns and hung-stream deadlines already exist in coding-agent plugins; Devo-K-Dev's additions are quota prediction, learned routing and measured savings.

## Free model strategy

No single free tier is enough, but eight of them together are, which is exactly why the router matters. Limits below are from the [free-llm-api-resources list](https://github.com/cheahjs/free-llm-api-resources) as of October 2026 and change often; the model registry is the place to update them.

| Provider | Free limit | Models worth using | Watch out for |
| --- | --- | --- | --- |
| Groq | 1,000 requests/day and 8,000 tokens/min per model | gpt-oss-120b, qwen3.6-27b, Llama Prompt Guard 2 | Low tokens/min chokes long prompts |
| Cerebras | 5 requests/min, 1M tokens/day per model | gpt-oss-120b, GLM-4.7, Gemma 4 31B | Very fast, very few requests |
| OpenRouter | 20 requests/min, 50/day shared; 1,000/day after a one-time $10 top-up | Nemotron 3 Super and Ultra, Poolside Laguna, Gemma 4 | Quota is shared across all free models |
| Mistral | Codestral: 30 requests/min, 2,000/day | Codestral, Devstral | Free plan requires opting into training; phone verification |
| Cloudflare Workers AI | 10,000 neurons/day | Kimi K2.7 Code, GLM-5.2, gpt-oss-120b | Small daily budget |
| NVIDIA NIM | 40 requests/min | Various open models | Phone verification; reduced context windows |
| Google AI Studio | Gemini 3.5 Flash: 20/day; Flash-Lite: 500/day; Gemma 4: 14,400/day | Gemini Flash, Gemma 4 | Prompts are used for training outside the UK and EU, which includes India |
| Kilo Gateway | 200 requests/hour per IP, no account | Free auto-router, Nemotron, Laguna | Free models may train on prompts |
| Ollama (local) | Your hardware | Picked once we know your GPU | Slower, but private and unlimited |

Starting model per role (the eval harness replaces these guesses with measured winners):

- **Orchestrator, Architect, Analyst:** GLM-5.2 or Nemotron 3 Ultra; gpt-oss-120b as fallback.
- **Frontend, Backend, Data and ML engineers:** Kimi K2.7 Code, Qwen3.6-27B, GLM-4.7, Codestral.
- **QA and DevOps:** gpt-oss-120b, Qwen3.6-27B.
- **Code Reviewer and Security Engineer:** a family different from the author's, for example Nemotron or Gemini Flash.
- **UI Designer and visual review:** a vision-capable model such as Gemini Flash.
- **Scribe, Liaison, Intake and summaries:** Gemini Flash-Lite, Gemma 4, gpt-oss-20b.
- **Guards:** Prompt Guard 2 running locally.

Public leaderboards are a weak guide: one aggregator alone reports DeepSeek V4 Pro anywhere from about 55% to 76% on SWE-bench Pro ([agentpedia](https://agentpedia.codes/blog/cheapest-ai-coding-models-2026)). Devo-K-Dev picks models from its own measurements.

Data rules, enforced by the registry's `trains_on_prompts` flag:

1. Only public or personal repos ever reach free endpoints. Never employer code.
2. A repo marked private routes only to local models or providers that do not train on prompts.
3. API keys live in `.env`, loaded through pydantic-settings, never committed; a pre-commit secret scan blocks accidents.

Rough capacity check: a 50-task eval run needs an estimated 1,500 to 3,000 model calls, so one configuration fits in about a day of combined free quota. The optional $10 OpenRouter top-up is the best-value spend if a budget appears.

## Adapting to the models you have

Devo-K-Dev works with whatever models a user connects, from one local model to ten providers. It measures each model first, checks the job against them before asking for approval, and changes how it runs to fit.

1. **Discover.** List every model from the configured providers and local runtimes such as Ollama, with context window, tool calling, JSON output and vision support.
2. **Profile.** A fitness probe of a few minutes per model, cached and re-run when a model changes: tool-call accuracy, schema-valid output, instruction following, a tiny code fix that must pass its test, recall at growing context lengths, and speed.
3. **Pre-flight check.** The draft plan's needs (roles, context sizes, vision for UI review, coding difficulty) are compared with the profiles. The verdict is green, amber or red, with reasons, the adaptations it will use, and estimated calls, time and quota. It appears at plan approval; on red, Devo-K-Dev suggests adding a model, cutting scope or splitting the job.
4. **Pick an execution mode** automatically:

| Mode | When | What changes |
| --- | --- | --- |
| Multi-model | Several capable models | Roles go to their best-fit models; tasks run in parallel; reviews use a different model family |
| Single-model staged | Only one usable model | The same model plays each role in turn, each in a fresh context with its own role prompt; tasks run one at a time in smaller steps with more checkpoints; review happens in a fresh context, and tests, linters and scanners weigh more because there is no second model family |
| Weak-model | Tool calling is unreliable | Actions are written as plain-text commands that code parses; steps get even smaller; approvals come more often |
| Small-context | Short context windows | Aggressive compaction, smaller files per task, more branching |

5. **Degrade gracefully.** A missing capability switches a feature to a fallback with a notice: no vision model means UI review uses accessibility and layout checks only; no embedding model means keyword search only.

The check predicts; it does not guarantee. Tests during the run are the real proof, and a model that starts failing mid-run is demoted by the router.

## Sandbox and code intelligence

All model-written code runs in a hardened, disposable Docker container that holds no secrets, and agents see the repo through a compact symbol map instead of whole files.

### Sandbox

- **Interface first.** A `Sandbox` protocol (create, exec, read, write, diff, destroy) with a Docker implementation built on the Docker SDK for Python. E2B or Daytona adapters can be added later without touching agents.
- **Hardened defaults.** Non-root user, all Linux capabilities dropped, `no-new-privileges`, read-only root filesystem with a writable workspace, CPU, memory and process limits, per-command timeouts and output size caps.
- **No network by default.** Dependency installs go through an allow-list proxy that reaches only package registries.
- **No secrets inside.** The GitHub token never enters the container; the host-side integrator pushes branches and opens PRs.
- **Isolation tiers.** Containers share the host kernel; gVisor adds a user-space kernel and Firecracker a full microVM ([tier comparison](https://github.com/lightbearco/tupper/wiki)). On Windows, Docker runs inside the WSL2 virtual machine, which adds a VM boundary between agent code and Windows. Running gVisor inside WSL2 is a stretch goal.

### Code intelligence

- **Repo map.** tree-sitter parses the repo into definitions and references, a graph ranks symbols by importance, and the top of that ranking is fitted into a token budget. This is the approach Aider made popular.
- **Search tools.** ripgrep search, line-range file reads and symbol lookup, all executed in the sandbox.
- **Semantic search as an experiment.** Function-level chunks embedded on CPU with a small code model such as jina-embeddings-v2-base-code, stored in pgvector and fused with keyword search. Several strong coding tools use structural maps with no embeddings at all ([survey](https://github.com/codecoradev/cora-code/issues/544)), so we keep it only if the evals show a gain.
- **AGENTS.md.** If the target repo has an AGENTS.md file, the open convention now under the Agentic AI Foundation, its guidance is loaded for every agent working on that repo, after the same injection screening as any repo text.

## Memory

Four memory tiers, following the working, episodic, semantic and procedural split of the [CoALA framework](https://arxiv.org/abs/2309.02427), sit behind one memory manager that decides what is written, when, and what each agent sees.

| Tier | Holds | Stored in | Written when | Read when |
| --- | --- | --- | --- | --- |
| Working | The current task: brief, plan, notes, recent tool results | The agent's context plus a task-state record | Continuously during the task | Every step of that task |
| Episodic | What happened: events, task summaries, mistakes and fixes, your feedback | Event log in PostgreSQL, plus episode summaries with embeddings | By code for every event; a summary at task end | Before planning and when stuck: "have we hit this before?" |
| Knowledge | Facts: stack, architecture, conventions, API contracts, decisions, your preferences; and your documents | PostgreSQL tables and pgvector | When a decision is made or a fact is confirmed | At task start, by relevance, under a token cap |
| Procedural | How to do things: skills with a trigger, steps, pitfalls and a check, plus the role prompts | Versioned markdown files | Only when a learning trigger fires | When a task matches a skill's trigger |

### Learning triggers

The memory API refuses a procedural write unless it names one of these triggers and links the evidence:

- **Dead end resolved:** a blocked path that was later navigated successfully.
- **User correction:** an agent was wrong and the right approach was identified.
- **Non-obvious workflow:** a pattern that could not be guessed from context alone.
- **Recurring pattern:** the same solution needed across several tasks.

### Anti-patterns, enforced in code

- **Duplicate skills:** a similarity search runs before any new skill; above the threshold, the existing skill is patched instead.
- **Vague descriptions:** a validator requires a short, specific trigger description.
- **Spurious writes:** no trigger and evidence, no write.
- **Lifecycle steps inside skills:** a linter rejects skill bodies that contain workflow steps; skills hold domain knowledge only.

The triggers and anti-patterns come from the internal framework you shared. The ideas are general, but Devo-K-Dev's repo states them in its own words.

CoALA warns that writing procedural memory is riskier than writing the other tiers, because it changes behaviour directly. So a new skill starts as a candidate and is promoted only if the eval suite does not get worse with it. A background consolidation job merges repeated episodes into knowledge or skill candidates and lets stale episodes fade.

Documents you provide enter the knowledge tier through the Document RAG pipeline below.

## Document RAG

Agents can search the documents you give a project (specs, PDFs, API references, notes, slides) and must cite what they used. The Researcher can add web pages it fetches to the same store.

1. **Ingest.** Upload in mission control or drop files into the project's docs folder. [Docling](https://www.respan.ai/market-map/docling/alternatives), IBM Research's open-source document converter, turns PDF, DOCX, PPTX, HTML and images into structured text that keeps headings and tables.
2. **Chunk by structure.** Sections and headings decide the cuts. Small chunks are used for search; their parent section is what the agent reads.
3. **Embed locally** on the CPU with a small open model, picked by a retrieval test on our own documents. BGE-M3 and Qwen3-Embedding-0.6B are the first candidates.
4. **Store** in PostgreSQL: pgvector for meaning, built-in full-text search for exact terms.
5. **Retrieve in two passes.** Vector and keyword results are fused, then a cross-encoder reranker picks the best few passages. Docling, pgvector, keyword search and a cross-encoder is a common open-source pattern ([example](https://github.com/RoodyCode/rag)).
6. **Use on demand.** Agents call a `search_docs` tool when they need something, rather than having documents stuffed into every prompt, and their outputs cite document and section. Nandi can answer your questions about your documents too.
7. **Keep it fresh and safe.** Changed files are re-indexed. Each project has its own scope. Document text is treated as untrusted data in prompts.
8. **Measure it.** Each project can hold a few questions with known answer passages; recall at k and citation accuracy are tracked in CI.

Code is searched differently: the repo map and code search in the sandbox section handle source files, and Document RAG handles everything written for people.

## Context window management

Every model call gets a token budget, and a context manager builds the smallest high-signal context that fits it, following Anthropic's [context engineering guidance](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).

- **Budgets.** Each model's window comes from the registry, minus reserved output tokens, split into slices: role prompt, task brief, retrieved memory, working set, tool results.
- **Just-in-time loading.** Agents hold references (file paths, artifact IDs, queries) and load content with tools when they need it, instead of being pre-stuffed.
- **Offloading.** A long log or listing is saved to the workspace; the agent gets a summary and the path.
- **Tool-result clearing.** Raw tool output is dropped from history once it has been used.
- **Compaction.** Past a configurable share of the window (default 70%), a small model summarises older turns, keeping decisions, unresolved bugs, file paths and open to-dos, while the latest tool results stay verbatim. Compaction prompts are tuned for recall first, then precision, as the guidance recommends.
- **Structured notes.** Each task keeps a notes record (progress, decisions, next steps) outside the context. It is the working-memory record, so it survives compaction and model handoff.
- **Isolated specialists.** Each specialist works in a fresh context and returns a short structured result, so the Orchestrator's own context stays small.
- **Handoff-aware.** When the router moves a conversation to a model with a smaller window, the manager recompacts before replaying.
- **Visible.** Token use per agent is counted with each model family's tokenizer and shown live in mission control.

## Context branches

Long work is split into branches, each with its own short context, so no agent ever has to remember the middle of a long conversation. It is the same idea as keeping one chat per milestone, applied inside Devo-K-Dev.

- **Every task is a branch.** It starts from a compact brief and the task-state record, never from its parent's full transcript.
- **Fork for side work.** An agent, or you, can fork a branch for a research spike, a debugging hypothesis, an alternative design or a side question to Nandi. The fork gets a fresh context and its own budget.
- **Merge a distilled result.** A finished branch returns a short typed result to its parent: summary, decisions, artifact links. The full transcript stays in episodic memory, retrievable if ever needed.
- **Limits.** Depth and budget caps stop branching from exploding; abandoned branches are pruned and logged by Ganesh.
- **Your chats branch too.** Each topic with Nandi is its own thread, and a long thread gets a thread brief instead of an ever-growing history.
- **Time travel, later.** Fork from any earlier checkpoint to try a different decision ("what if we had picked a different database?"), built on checkpoints Devo-K-Dev already stores.
- **Visible.** Mission control draws the branch tree like a git graph; click any branch to read it or ask Nandi about it.

Under the hood a branch is a Temporal child workflow with its own working memory, and a merge is a typed result object, so branching inherits the same durability as everything else.

## Prompts

Every role prompt follows one anatomy, is written by us after studying openly licensed prompts, and must pass its own test suite on several models before it ships.

### Anatomy of a role prompt

- **Identity and mission:** who the agent is and what "done" means for it.
- **Context slots:** brief, task, inputs and relevant memory, filled in by the context manager.
- **Procedure:** the steps a strong engineer in that role would follow.
- **Output contract:** a typed schema the runtime validates.
- **Quality bar:** a checklist the agent applies before submitting.
- **Boundaries:** what it must not do, and how to use its tools.
- **Escalation:** when to ask, when to stop.
- **Examples:** two or three canonical examples rather than a long list of edge cases, as Anthropic's context guidance advises.

### Where the ideas come from

Openly licensed projects: MetaGPT's role prompts and structured documents, the BMAD Method's agent personas, OpenHands and mini-SWE-agent for coding agents, Cline's system prompt, and the vendor prompting guides from Anthropic and OpenAI. They are studied for ideas, never copied. Leaked proprietary system prompts that circulate on GitHub are off limits: they are not ours to use.

### How prompts are tested

- **Golden cases per role,** about ten each: an input plus assertions. Deterministic checks come first (valid schema, required sections, tests passing for coding roles), then a rubric scored by a judge from a different model family.
- **Cross-model robustness.** The router can switch models mid-task, so every prompt runs on at least three free models. A prompt that works on only one model fails.
- **Regression in CI** with promptfoo. Prompt versions are tracked, and every trace records which version ran.
- **Real failures become test cases,** so the suite grows with use.
- **A/B before shipping:** a new version runs against the current one on its role suite and the outcome evals, and ships only if it is not worse.

## Safety basics and the Security agent

Security is one specialist plus a few sensible defaults, not the theme of the project.

### The Security Engineer

- **After design:** a short review of the architecture (sign-in, secret handling, data exposure, chosen dependencies). Findings become tasks in the graph.
- **After implementation:** Semgrep, gitleaks and a dependency audit run on the diff. The agent triages the findings, fixes high-severity issues itself or sends them back to the author agent, and re-scans until clean or escalated.
- **Before release:** a final scan, summarised in the PR.

### Defaults, because agents run code

- Agent-written code runs in a disposable Docker container: non-root, no secrets inside, and no network unless a task needs package installs, which go through an allow-listed proxy.
- Untrusted text (issue bodies, web pages, repo files) is marked as data in prompts, and a small local classifier (Prompt Guard 2) flags obvious injection attempts for you to see.
- Dependencies are hash-pinned and GitHub Actions are pinned by commit SHA, a lesson from the March 2026 LiteLLM compromise (ADR-004).
- Tokens are scoped to one repo, and pushes happen outside the sandbox.

## Mission control

Mission control is a dark, live web app where you watch the team work, steer it and inspect anything. Claude builds it; you only need to know what each panel shows.

| Panel | What you see | Built with |
| --- | --- | --- |
| Plan review | The proposed task graph with roles and reasons; edit, then approve | React Flow in edit mode |
| Task graph | The live graph: running nodes glow, finished ones turn green or red, edges animate as artifacts flow; click any node for detail | React Flow, ELK auto-layout, Framer Motion |
| Team roster | Each agent's current activity in one line, its model and its token use | React, Tailwind, shadcn/ui |
| Activity stream | Streaming reasoning, tool calls and diffs, terminal-style, filterable by agent | WebSocket stream, Monaco diff viewer |
| Timeline | Tasks over time, with waits, retries and escalations marked | A Gantt-style chart |
| Router panel | Quota gauges per provider and every model switch with its reason | Recharts |
| Project chronicle | The Scribe's decisions, features, mistakes and fixes, and tech stack | Markdown rendering |
| Liaison dock | Chat with the Liaison, pause, stop and resume buttons, an approvals inbox | WebSocket |

Events travel from agents to an event bus (Redis Streams), then through a FastAPI WebSocket gateway to the browser, so the UI never polls the database. Every event follows one typed schema, which the Scribe also consumes.

For debugging there are engineering views behind the showcase: the Temporal Web UI for workflow history, traces in Langfuse or Phoenix through OpenTelemetry's GenAI conventions, and Prometheus with Grafana for metrics.

Devo-K-Dev reviews its own UI the way it reviews any frontend work: Playwright screenshots at desktop and mobile sizes, accessibility checks, and a visual critique against the design brief.

## Quality: evals, prompt tests and chaos tests

Six kinds of test answer four questions: does the deterministic core behave, does each agent do its job, does the system deliver working software, and does it survive failure.

| Layer | What it checks | When it runs |
| --- | --- | --- |
| Unit tests | Graph validator, scheduler, state transitions, router policy, memory rules, context budgets; recorded model responses, so no API calls | Every PR |
| Prompt tests | Each role's golden cases on at least three models (see Prompts) | PRs that touch prompts or roles |
| Chaos tests | Recovery from injected failures (see Reliability) | Every PR |
| devokdev-bench | About 30 small jobs of mixed types (bug fix, feature, small app, UI change) in toy repos with hidden acceptance tests: pass rate, cost, time, and how often a human had to step in | Nightly subset; full run on demand |
| Plan quality | Task graphs for a set of briefs, scored against reference plans for missing steps and wrong roles | On demand |
| SWE-bench Verified Mini | 50 real bug-fix tasks needing about 5 GB of images ([EvalScope](https://evalscope.readthedocs.io/en/latest/benchmarks/swe_bench_verified_mini.html)), against mini-SWE-agent with the same model, the agent the official bash-only leaderboard uses ([SWE-bench](https://swebench.com/verified)) | By hand, for headline numbers |

Every eval run records its configuration, models and prompt versions. Small samples get bootstrap confidence intervals, and configurations are compared on the same tasks, so the README numbers can be defended in an interview.

## Integrations and interfaces

Jobs arrive from mission control, the CLI, a tracker issue or an MCP client; results leave as branches, pull requests and status updates.

| Interface | Purpose | Built with |
| --- | --- | --- |
| Mission control and Liaison chat | Start jobs, answer questions, approve plans, steer runs | React app over FastAPI |
| CLI | `devokdev new`, `devokdev status`, `devokdev pause`, `devokdev resume`, `devokdev replay` | Typer |
| REST and WebSocket API | Everything the UI does, documented with OpenAPI | FastAPI |
| Task sources | The Intake agent reads GitHub Issues first, Jira and Linear later, and posts status and comments back | MCP servers where approved, REST otherwise |
| Git hosting | The Git and Release agent opens branches and PRs with evidence and writes release notes | Git CLI; a GitHub App with short-lived, per-repo tokens |
| MCP server | Other agents and IDEs submit jobs and read status: `submit_job`, `job_status`, `approve`, `pause` | Official MCP Python SDK, Streamable HTTP and stdio, following the [July 2026 spec](https://www.danilchenko.dev/posts/ai-agent-protocols/) |
| MCP client | Agents use approved external MCP servers; tool definitions are screened and pinned once approved | Official MCP Python SDK |

## Feature backlog

Good ideas go here first, so the project still ships. The five Now items are already in the roadmap and move v0.1 from week 7 to week 8 and v1.0 from week 11 to week 12. From here on, nothing joins Now unless something else leaves it.

| Feature | What it gives you | Priority | When |
| --- | --- | --- | --- |
| Model fitness check and pre-flight verdict | Know before approving whether your models can do the job | Now | M1, M3 |
| Adaptive modes, including single-model staged | Works with one model or many | Now | M3 |
| Context branches | Short contexts, so nothing in the middle is forgotten | Now | M2, M5 |
| Document RAG with citations | Agents use your specs and docs and show where each fact came from | Now | M6 |
| Plan preview with estimates | Calls, time and quota per provider, shown before you approve | Now | M3 |
| Notifications | A Telegram, Discord or email message when a run needs approval, finishes or is blocked | Next | After v0.1 |
| Run replay | Step through any finished run in mission control, for demos and debugging | Next | After v0.1 |
| "Why is this here?" | Click any file line or decision to see which agent, task and reason produced it | Next | After v0.1 |
| Time travel | Fork a run from an earlier checkpoint to try another decision | Next | After v0.1 |
| Codebase onboarding | Brihaspati maps an existing repo and writes a guide before work starts | Next | After v0.1 |
| Voice to Nandi | Speak instead of type, transcribed with Whisper on Groq's free tier | Later | After v1.0 |
| Multi-project workspace | Several projects sharing one job queue | Later | After v1.0 |
| Playbook editor | Edit job templates in the UI | Later | After v1.0 |
| Project report export | Ganesh's record as a PDF | Later | After v1.0 |
| Learned router | A model trained on Devo-K-Dev's run logs to pick models | Later | After v1.0 |
| A2A agent card | Other agents can hire Devo-K-Dev for a job | Later | After v1.0 |

## Tech stack

Well-known tools where they are the industry standard, our own code where the component is the point of the project.

| Layer | Choice | Alternatives considered | Why |
| --- | --- | --- | --- |
| Language | Python 3.12, async | TypeScript | AI ecosystem; Ved's strongest language |
| Dev environment | WSL2 Ubuntu, Docker Desktop on the WSL2 backend, VS Code Remote-WSL | Native Windows | Sandboxes are Linux containers; matches production Linux |
| Packaging and quality | uv with a hash-pinned lockfile; ruff, mypy strict, pytest, Hypothesis, pre-commit | pip, Poetry | Fast, reproducible, supply-chain safe |
| Durable execution | Temporal (Python SDK), local dev server, Temporal Web UI | LangGraph, CrewAI Flows, own engine | Signals, queries, retries, timeouts and resume after crash are built in |
| Agent loop | Our own, running as Temporal activities | A framework's prebuilt agent | Needed for handoff, budgets, permissions and context control |
| LLM access | Our own gateway over the official `openai` SDK and httpx | LiteLLM, Portkey | Routing is a core feature; the key-holding layer stays small |
| Data | PostgreSQL 17 with pgvector | Qdrant plus SQLite | One store for state, events, memory and vectors |
| Events and quotas | Redis Streams and counters | Kafka, NATS | Light enough for a laptop; live events and atomic quota buckets |
| Sandbox | Docker SDK for Python, hardened; one git worktree per parallel task | E2B, Daytona | Free, local, safe parallel edits |
| Code intelligence | tree-sitter, ripgrep | LSP servers | Language-agnostic and fast |
| Visual QA | Playwright, axe-core, a vision-capable model | Manual review | Agents can see and check their UI |
| Security tooling | Semgrep, gitleaks, osv-scanner, Prompt Guard 2 | Commercial scanners | Open source and recognised |
| Observability | OpenTelemetry GenAI conventions, Langfuse or Phoenix, Prometheus, Grafana | LangSmith, Datadog | Vendor-neutral and free |
| Prompt testing | promptfoo and pytest | Hand-run checks | Repeatable regression gates in CI |
| Frontend | React, Vite, TypeScript, Tailwind, shadcn/ui, React Flow, Framer Motion | Streamlit | Looks professional; built for live graphs |
| API and CLI | FastAPI with WebSockets, Typer | Flask, Click | Async, typed, documented |
| CI/CD | GitHub Actions pinned by commit SHA, Docker Compose, images on GHCR | GitLab CI | Free for public repos; standard |
| Protocols | Official MCP Python SDK | — | Open standard under the Agentic AI Foundation |

## Decision log

Each decision is proposed until Ved accepts it; a changed decision gets a new row that supersedes the old one, never an edit. The repo copies each accepted row to `docs/adr/` as a short architecture decision record.

| ID | Date | Decision | Why | Revisit if | Status |
| --- | --- | --- | --- | --- | --- |
| ADR-001 | 2026-10-13 | Standalone Python system, not built on Copilot or Claude Code runtimes | The portfolio must show engineering, not configuration | Never for the core | Accepted |
| ADR-002 | 2026-10-13 | Develop inside WSL2 with Docker Desktop | Sandboxes are Linux containers; parity with production | WSL2 file or memory performance hurts | Accepted |
| ADR-003 | 2026-10-13 | LangGraph for the workflow graph; our own agent loop inside each node (superseded by ADR-014) | Standard durability and approval interrupts | — | Superseded |
| ADR-004 | 2026-10-13 | Our own gateway and router over OpenAI-compatible APIs instead of LiteLLM | Routing is a core feature; the key-holding layer stays dependency-light after the March 2026 LiteLLM compromise | Many needed providers lack OpenAI-compatible APIs | Proposed |
| ADR-005 | 2026-10-13 | PostgreSQL with pgvector for Devo-K-Dev's state; Redis for counters and events; Temporal keeps its own store | Few moving parts | Throughput becomes a bottleneck | Accepted |
| ADR-006 | 2026-10-13 | Git, test runs, scanners and PR creation are plain code, not agents (superseded by ADR-020) | Reliability, cost and security | — | Superseded |
| ADR-007 | 2026-10-13 | Hardened Docker sandbox, no network and no secrets by default | Strong isolation without paid services | Devo-K-Dev ever runs untrusted users' jobs | Accepted |
| ADR-008 | 2026-10-13 | Free and open-weight models only; no private or employer code to endpoints that train on prompts | Zero cost; data protection | A paid budget appears | Proposed |
| ADR-009 | 2026-10-13 | devokdev-bench plus SWE-bench Verified Mini against mini-SWE-agent | Cheap regression gate plus a credible public number | Quota cannot support the runs | Proposed |
| ADR-010 | 2026-10-13 | OpenTelemetry GenAI conventions; Phoenix locally, Langfuse Cloud for demos | Vendor-neutral; free | Langfuse free units run out | Proposed |
| ADR-011 | 2026-10-13 | Skills and router versions are promoted only through eval gates | Learning that is measured, not assumed | Never | Proposed |
| ADR-012 | 2026-10-13 | Dashboard built last (superseded by ADR-021) | Frontend was not the skill on show | — | Superseded |
| ADR-013 | 2026-10-13 | Working name Baton (superseded by ADR-024) | Short, and the handoff metaphor fits | — | Superseded |
| ADR-014 | 2026-10-13 | Temporal for durable orchestration, replacing LangGraph | Live changes, pause and resume, and crash recovery map onto signals, queries and durable activities; comparison under Orchestration | Temporal's determinism rules slow development badly | Proposed |
| ADR-015 | 2026-10-13 | The Orchestrator builds a task graph per job from playbooks; nothing runs before plan approval | Right-sized teams and user control | Plans from free models are poor | Proposed |
| ADR-016 | 2026-10-13 | The Scribe is a separate agent; code captures every event and the Scribe curates the record | Small Orchestrator context; the record never depends on memory | Never | Proposed |
| ADR-017 | 2026-10-13 | The Liaison runs concurrently; changes reach the Orchestrator only as signals | Steering without blocking or racing the plan | Never | Proposed |
| ADR-018 | 2026-10-13 | Ask about outcome-changing decisions; decide and log implementation-only ones; three autonomy levels | Fewer interruptions without losing control | Users want more or less control | Proposed |
| ADR-019 | 2026-10-13 | Four memory tiers with learning triggers and anti-patterns enforced in code | Learning without memory bloat | Memory quality drops | Proposed |
| ADR-020 | 2026-10-13 | A Git and Release agent makes judgment calls; git mechanics stay deterministic tools; one worktree per parallel task | Conflicts and PR writing need judgment; parallel agents need isolation | Never | Proposed |
| ADR-021 | 2026-10-13 | Mission control is built alongside the backend from the team milestone, not last | The live view is part of the product | Frontend work crowds out the core | Proposed |
| ADR-022 | 2026-10-13 | Security is one agent plus defaults, not a project theme | Matches the project's purpose | A security role becomes the target | Proposed |
| ADR-023 | 2026-10-13 | Chaos tests in CI prove reliability | "Never dies" has to be tested | Never | Proposed |
| ADR-024 | 2026-10-15 | Project name DEVAGANA (superseded by ADR-033) | Ved's choice; the agents are named after devas | — | Superseded |
| ADR-025 | 2026-10-15 | Agent names follow the Hindu pantheon's order: MahaDev, Durga and Saraswati at the top, then figures above the devas, then the devas and sages; goddesses in every tier; line icons, not images of deities | A memorable, coherent theme that stays respectful | Ved changes any name | Accepted |
| ADR-026 | 2026-10-15 | Document RAG in v1: Docling, local embeddings, pgvector plus full-text search, cross-encoder reranking, citations | Agents must use the user's documents and show sources | Retrieval evals fail on real documents | Proposed |
| ADR-027 | 2026-10-15 | Every task is a branch; forks merge back a distilled typed result | Short contexts; nothing lost in the middle | Merged summaries drop facts that matter | Proposed |
| ADR-028 | 2026-10-15 | Model fitness profiles and a pre-flight verdict before plan approval | Know before starting whether the models can do the job | Probes stop predicting run outcomes | Proposed |
| ADR-029 | 2026-10-15 | Adaptive execution modes, including single-model staged and a text-action fallback | Works with whatever models the user has | Single-model results are unusable | Proposed |
| ADR-030 | 2026-10-15 | Learning method: I do, we do, you do (superseded by ADR-034) | Ved must be able to rebuild every part | — | Superseded |
| ADR-031 | 2026-10-15 | Feature backlog with Now, Next and Later; nothing joins Now unless something leaves | Protects the ship date | Never | Proposed |
| ADR-032 | 2026-10-15 | The repo carries AGENTS.md, a Copilot pointer file and a Markdown export of this doc | Other agents get the same context | Agents adopt another standard | Proposed |
| ADR-033 | 2026-10-15 | Project name Devo-K-Dev, from "Devon ke Dev", a title of MahaDev | Ved's choice; it names the agent at the top | Ved renames it | Accepted |
| ADR-034 | 2026-10-15 | Claude writes all code; after each stage, a walkthrough of how it works and every decision | Ved's choice; he must be able to explain and defend every part | Ved wants to write code himself | Accepted |
| ADR-035 | 2026-10-15 | Code names: repo devo-k-dev; Python package and CLI devokdev | Python package names cannot contain hyphens; one short name everywhere | The name is taken on PyPI or GitHub | Proposed |

## Roadmap

&#91;embedded content: Roadmap · 4 phases, 10 milestones, 4 gates\]

Gate B is the first point where the repo is worth putting on a resume; every later gate adds depth and measured numbers. The week counts are estimates and get resized once Ved shares his weekly hours.

## Repo structure and standards

One Python package with clear module boundaries, plus playbooks, skills, evals, the mission control app and docs as siblings.

```text
devo-k-dev/
├── src/devokdev/
│   ├── workflows/      Temporal workflows: project, task, branches, signals, queries
│   ├── activities/     model calls, tool calls, sandbox commands
│   ├── orchestrator/   job classification, playbooks, task graph, replanning
│   ├── agents/         agent loop, role cards, versioned prompts
│   ├── liaison/        message sorting, change requests, live answers
│   ├── scribe/         event consumers, project chronicle
│   ├── memory/         memory manager, four tiers, triggers, linters
│   ├── rag/            document ingestion, hybrid search, reranking
│   ├── context/        budgets, compaction, offloading, token counts
│   ├── llm/            canonical messages, provider adapters, registry
│   ├── fitness/        model discovery, probes, pre-flight check
│   ├── router/         signals, policy, quotas, circuit breakers, handoff
│   ├── sandbox/        Docker sandbox, worktrees, policies
│   ├── tools/          tool schemas and implementations
│   ├── integrations/   GitHub, Jira, Linear, MCP server and client
│   ├── events/         typed event schema, Redis Streams bus
│   ├── api/            FastAPI app and WebSocket gateway
│   ├── telemetry/      OpenTelemetry, metrics, logging
│   └── cli.py          Typer CLI
├── playbooks/          task-graph templates per job type
├── skills/             procedural memory files
├── evals/              devokdev_bench/, swebench/, plans/, prompts/, rag/, fitness/, chaos/
├── web/                mission control (React)
├── config/             models.yaml, roles/*.yaml, policies
├── deploy/             docker-compose.yml, Dockerfiles, Grafana dashboards
├── docs/               DESIGN.md, ARCHITECTURE.md, adr/, STATUS.md, learning/
├── tests/              unit and integration tests
├── .github/            workflows/ (ci, evals, chaos), copilot-instructions.md
├── AGENTS.md
├── pyproject.toml
└── uv.lock
```

Standards:

- Every change lands through a pull request into `main`, even working solo, with conventional commit messages. That history is part of what recruiters read.
- CI must pass before merge: ruff, mypy in strict mode, pytest with coverage reported, secret scan and dependency audit.
- Secrets only in `.env`; the repo ships `.env.example`.
- License: Apache-2.0, proposed for its explicit patent grant.
- **Stage walkthroughs.** After each stage Claude writes `docs/learning/M<n>.md`: what each new file does, how it works, why it is designed that way, and the interview questions it prepares Ved for. Ved reads it and asks about anything unclear.

## Status and progress log

Current milestone: M0 (setup), not started. The design was proposed on 13 October 2026, reworked the same day after Ved's review, extended on 15 October with his additions, renamed Devo-K-Dev the same day, and approved on 15 October. M0 starts in a new chat, where the remaining open questions get answered.

| Milestone | Status | Started | Finished |
| --- | --- | --- | --- |
| M0 Setup | Not started |  |  |
| M1 Model gateway, router and fitness check | Not started |  |  |
| M2 Agent runtime, sandbox and branches | Not started |  |  |
| M3 Orchestrator, task graph and adaptive modes | Not started |  |  |
| M4 Human in the loop: questions, Liaison, pause and resume | Not started |  |  |
| M5 Mission control v1 | Not started |  |  |
| M6 Memory, document RAG and Scribe | Not started |  |  |
| M7 Full roster and integrations | Not started |  |  |
| M8 Quality: prompt, chaos and outcome tests | Not started |  |  |
| M9 Polish and launch | Not started |  |  |
| Later: backlog items and learned router | Not started |  |  |

Progress log, newest first. Claude adds a row at the end of every session.

| Date | Session | What happened | Next |
| --- | --- | --- | --- |
| 2026-10-15 | Design approved | Ved approved the names and the design; implementation moves to a new chat, one chat per milestone | M0 in a new chat: repo, local stack, CI |
| 2026-10-15 | Names | Renamed to Devo-K-Dev; MahaDev-led hierarchy with Durga and Saraswati at the top and seven goddesses and women sages; Hanuman moved to his Ramayana role as Researcher; learning method changed so Claude writes all code and explains each stage; 3 new decisions | Ved approves the names and answers the open questions; then M0 |
| 2026-10-15 | Additions | Renamed to DEVAGANA; agent names set as a Shiva-led hierarchy at Ved's request; added document RAG, context branches, model fitness check and adaptive modes, feature backlog, learning method, guidance for other agents, Temporal vs LangGraph; 9 new decisions; v0.1 moves to week 8 | Ved approves the names and answers the open questions; then M0 |
| 2026-10-13 | Redesign | Reworked the design around Ved's 20 requirements: per-job task graphs with plan approval, Liaison, Scribe, four-tier memory, Temporal, mission control; 10 new decisions | Ved answers the open questions; then M0 |
| 2026-10-13 | Design | Researched free models, routers, frameworks, evals and security tooling; wrote this doc; proposed 13 decisions | Superseded by the redesign the same day |

## Open questions for Ved

These answers unblock M0; the first two change concrete choices in this doc.

- [ ] Laptop specs: CPU, RAM, GPU and VRAM, free disk. My estimate is that Temporal, PostgreSQL, Redis and a few sandboxes together want about 16 GB of RAM; less works with fewer parallel agents.
- [ ] Hours per week, and any deadline such as placement season, so the roadmap can be sized honestly.
- [ ] Check your internship agreement's clause on personal projects and intellectual property. Build Devo-K-Dev on personal time and hardware, and never use employer code, data or credentials.
- [ ] Install WSL2 with the current Ubuntu LTS and Docker Desktop on the WSL2 backend; confirm `docker run hello-world` works inside Ubuntu.
- [ ] Create free API keys: Groq, Cerebras, OpenRouter, Google AI Studio, Mistral, Cloudflare Workers AI, NVIDIA NIM. Keep them in a password manager and never paste them into a chat.
- [ ] Create a public GitHub repo for Devo-K-Dev and a second demo repo for test jobs.
- [ ] Review the Decision log and mark each row Accepted, or comment on what to change.
- [ ] First demo job: a small new web app, a feature in an existing repo, or a bug fix? I suggest the small web app, because it uses the most roles.
- [ ] Code names: the repo is devo-k-dev and the Python package and CLI are devokdev (ADR-035); say if you want different ones.
- [ ] Optional: the $10 OpenRouter top-up, and opening the M0 chat in the Claude desktop app with the repo folder connected.

## Sources

Pages opened while writing this design, as of 13 October 2026.

- [CrewAI Flows](https://docs.crewai.com/en/concepts/flows) and [CrewAI Memory](https://docs.crewai.com/concepts/memory): Flows, `@persist`, `@human_feedback`, unified memory
- [MetaGPT](https://github.com/FoundationAgents/MetaGPT) and [ChatDev](https://github.com/OpenBMB/ChatDev): role-based software teams, MGX, ChatDev 2.0
- [Temporal Durable AI](https://docs.temporal.io/ai): durable execution, approval pattern, agent integrations
- [Cognitive Architectures for Language Agents (CoALA)](https://arxiv.org/abs/2309.02427): working, episodic, semantic and procedural memory
- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents): compaction, note-taking, sub-agents, just-in-time retrieval
- [free-llm-api-resources](https://github.com/cheahjs/free-llm-api-resources): free tiers and limits per provider
- [Cheapest AI coding models in 2026](https://agentpedia.codes/blog/cheapest-ai-coding-models-2026): open-weight model scores and why benchmark figures disagree
- [vLLM Semantic Router paper](https://arxiv.org/abs/2603.04444): routing signals composed by decision rules
- [LiteLLM security issue #24518](https://github.com/BerriAI/litellm/issues/24518) and [attack timeline](https://lmmarketcap.com/zh/litellm-supply-chain-attack): the March 2026 supply-chain compromise
- [Tupper](https://github.com/lightbearco/tupper): sandbox isolation tiers compared
- [Code embeddings survey, cora-code #544](https://github.com/codecoradev/cora-code/issues/544): which code tools use embeddings and which use repo maps
- [SWE-bench Verified](https://swebench.com/verified) and [SWE-bench Verified Mini on EvalScope](https://evalscope.readthedocs.io/en/latest/benchmarks/swe_bench_verified_mini.html): the mini-SWE-agent baseline and the 50-task subset
- [AI agent protocols in 2026](https://www.danilchenko.dev/posts/ai-agent-protocols/): the July 2026 MCP spec, A2A v1.0, the Agentic AI Foundation
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence): checkpointers, stores, time travel and fault tolerance
- [VS Code custom instructions](https://code.visualstudio.com/docs/agent-customization/custom-instructions) and [Copilot coding agent supports AGENTS.md](https://github.blog/changelog/2025-08-28-copilot-coding-agent-now-supports-agents-md-custom-instructions): which instruction files Copilot reads
- [Docling and its alternatives](https://www.respan.ai/market-map/docling/alternatives) and [an open-source RAG example](https://github.com/RoodyCode/rag): document parsing, hybrid search and reranking
- [Pushan](https://en.wikipedia.org/wiki/Pushan): god of journeys, roads and meetings
