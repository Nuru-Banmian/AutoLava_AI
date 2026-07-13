# AutoLava AI Implementation Roadmap

> **For agentic workers:** Implement the linked plans in order. Each phase produces deployable, testable software and is a prerequisite for the next phase.

**Goal:** Deliver the AutoLava AI system in the four increments defined by the approved design, keeping manual operations usable before AI and automation are introduced.

**Source spec:** `docs/superpowers/specs/2026-07-10-autolava-ai-design.md`

## Plan order

1. [`2026-07-13-autolava-ai-phase-1-foundation.md`](2026-07-13-autolava-ai-phase-1-foundation.md) — authentication, store access, administration, ledger, audit/rollback, export, weather, dashboard, charts, responsive web UI, and deployment.
2. [`2026-07-13-autolava-ai-phase-2-workforce.md`](2026-07-13-autolava-ai-phase-2-workforce.md) — workers, integer-hour entry, wage calculation, payroll snapshots, reconciliation warnings, audit, export, and responsive UI.
3. [`2026-07-13-autolava-ai-phase-3-agent.md`](2026-07-13-autolava-ai-phase-3-agent.md) — model-provider fallback, conversations, permission-scoped query/analysis, ledger drafts, approval-gated mutations, audit, and AI UI.
4. [`2026-07-13-autolava-ai-phase-4-automation-memory.md`](2026-07-13-autolava-ai-phase-4-automation-memory.md) — store-local scheduling, weather compensation, memory extraction, memory-aware briefings, system alerts, and task-log administration.

## Branch sequence

- Establish `dev` from the current stable `main` before feature execution.
- Execute each plan on `feature/phase-1-foundation`, `feature/phase-2-workforce`, `feature/phase-3-agent`, and `feature/phase-4-automation-memory`, respectively.
- Merge a phase into `dev` only after its release gate passes; promote `dev` to `main` only for a stable deployment candidate.

## Dependency map

```text
Phase 1: manual operations and deployable foundation
    |
    +--> Phase 2: workforce and payroll
    |
    +--> Phase 3: AI assistant over stable business APIs
              |
              +--> Phase 4: automation and memory using stable AI/ledger data
```

## Release gates

- Phase 1 is complete only when a family user can log in, record and repair store data, export it, inspect charts, and continue recording when weather is unavailable.
- Phase 2 is complete only when a historical month can be entered, settled, changed, flagged as stale, regenerated, audited, and exported.
- Phase 3 is complete only when reads are permission-scoped and every AI mutation requires a server-issued approval token plus explicit confirmation.
- Phase 4 is complete only when scheduled jobs are idempotent per store-local day, failures are visible to administrators, and low-confidence memories never reach users.

## Spec coverage map

| Design sections | Owning plan/tasks |
|---|---|
| Roles, store access, enable/disable, Phase 1 database core | Phase 1 Tasks 2-5 |
| Login, home, ledger, database, charts, admin, responsive rules | Phase 1 Tasks 3-11 |
| Open-Meteo, geocoding, weather fallback boundary, manual preservation | Phase 1 Task 7; Phase 4 Task 4 |
| Audit and ledger rollback | Phase 1 Tasks 4-6 |
| Workers, time entry, wages, payroll snapshots, workforce export | Phase 2 Tasks 1-6 |
| Agent models, provider routing, queries/analysis, drafts, approvals, history | Phase 3 Tasks 1-6 |
| Memories, daily 04:00 workflow, compensation, alerts, task logs | Phase 4 Tasks 1-6 |
| Docker/GitHub release verification and host MySQL boundary | Phase 1 Task 11 and each later phase's release task |
