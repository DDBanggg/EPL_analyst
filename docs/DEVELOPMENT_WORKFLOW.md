# Development Workflow

Starting with M7, the repository owner is the primary implementer. ChatGPT acts
as architect, technical tutor, design partner, debugging assistant, and reviewer.
Codex is an optional bounded assistant rather than the default milestone code
author. GitHub is the source of truth for repository state and review.

## Milestone cycle

Work proceeds one milestone at a time:

```text
Design
→ discuss architectural decisions
→ lock milestone scope
→ define acceptance criteria
→ owner implements incrementally
→ test and lint
→ owner commits and pushes
→ review the GitHub diff
→ PASS or focused fix
→ next milestone
```

Key architecture decisions should be understood before implementation begins.
Prefer learning and clear ownership of business logic over generated bulk code.
Keep changes small and reviewable, add tests with implementation, and do not begin
the next milestone until the current one passes review.

## Assistance and review

During implementation, ChatGPT can explain concepts, compare design alternatives,
review snippets, diagnose errors, help write and test SQL, help design schemas, and
review GitHub diffs against acceptance criteria. The repository owner remains
responsible for understanding and writing the production code.

Codex may be explicitly requested for mechanical edits, documentation
synchronization, or bounded refactors already chosen by the owner. Its use is not
an automatic milestone step, and future work does not require Codex prompt or
handoff files.
