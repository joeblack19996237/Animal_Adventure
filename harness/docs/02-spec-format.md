# Spec Format Contract

## Input Modes

### Single file (`python harness/harness.py docs/spec.md`)

Phases defined by `## Phase N:` headers in one file.

### Directory (`python harness/harness.py docs/spec/`)

Multiple context files (e.g. `architecture.md`, `data-model.md`, `workflow.md`, `build-plan.md`). Harness reads ALL `.md` files in the directory and concatenates them into a single context block. Numbered phases are extracted from whichever file contains `## Phase N:` or `## Phase N —` headers (typically `build-plan.md`). All files provide context; phase ordering comes from the numbered headers.

```markdown
# build-plan.md example
## Phase 1: Data Layer
Build User, Post, and Comment models per data-model.md spec.

## Phase 2: API Layer
Implement REST endpoints per workflow.md.
```
# Phase 11 Fixture Specs

Harness E2E fixture specs live under `harness/tests/e2e/fixtures/`. They are intentionally minimal and exist to exercise harness behavior across CLI, mixed-stack, REVIEW timeout, and BLOCK/FIX scenarios. These tests validate the harness, not generated fixture app completeness.
