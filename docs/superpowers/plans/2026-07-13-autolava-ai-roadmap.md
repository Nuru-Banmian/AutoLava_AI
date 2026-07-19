# AutoLava AI Implementation Roadmap

> Phase 1 is the current product. Phase 3 and Phase 4 are future-only redesign reminders, not
> implementation-ready plans.

**Goal:** Keep the manual Phase 1 application deployable and preserve future AI and automation
directions without committing the constrained server to unvalidated services.

## Plan order

1. [`2026-07-13-autolava-ai-phase-1-foundation.md`](2026-07-13-autolava-ai-phase-1-foundation.md) — authentication, store access, administration, current-state ledger, historical business records, export, weather, dashboard, charts, responsive web UI, and deployment. Its original implementation details are superseded by the SQLite simplification plan where they differ.
3. [`2026-07-13-autolava-ai-phase-3-agent.md`](2026-07-13-autolava-ai-phase-3-agent.md) — future AI assistant direction; redesign is required before implementation.
4. [`2026-07-13-autolava-ai-phase-4-automation-memory.md`](2026-07-13-autolava-ai-phase-4-automation-memory.md) — future automation and memory direction; redesign is required before implementation.

## Dependency map

```text
Phase 1: current manual operations and two-service deployment
    |
    +--> Phase 3: future AI redesign
              |
              +--> Phase 4: future automation and memory redesign
```

## Release boundaries

- Phase 1 remains complete only when a family user can log in, record and repair store data, export
  it, inspect charts, and continue recording when weather is unavailable.
- Phase 3 and Phase 4 have no active release gate. Each must first be redesigned for SQLite, the
  2-GB server, external APIs, and measured remaining memory.
- The current production topology remains one API/Uvicorn worker plus Nginx Web with persistent
  SQLite `/data`.

## Future design boundary

Any future Agent process must be justified by idle and normal-workflow `docker stats` snapshots.
If isolation is justified, a future design may propose an optional `compose.agent.yaml`; this
repository does not provide that overlay today.
