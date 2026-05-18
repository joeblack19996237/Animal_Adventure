# TypeScript Builder Guide

Language-specific build instructions for TypeScript phases.

---

## Test Command

```bash
npx vitest run
```

## Integration Test Command

```bash
npx vitest run
```

(Playwright E2E is deferred to the next iteration — vitest covers unit and integration tests.)

## Compile Check

```bash
npx tsc --noEmit
```

Run this for every new `.ts` / `.tsx` file before signaling complete.

## TDD Patterns

- Use vitest `describe` / `it` blocks with `expect()` assertions
- Test files: `*.test.ts` in `tests/`
- Test names describe behaviour: `it("returns empty list when no players", ...)`
- TypeScript strict mode required in test files — no `any`
- Target coverage ≥ 80% per module
- Keep first-pass tests representative and compact. Prefer table-driven cases over
  repeated near-identical `it()` blocks, and keep each new test file under 250 lines
  unless the phase explicitly requires exhaustive coverage.

## Integration Testing Patterns

See `.claude/rules/common/integration-testing-guide.md` when phase_type is `integration` or `e2e`.

- Name integration test files `*.integration.test.ts`
- Use vitest with real service calls — no `vi.mock()` for external services
- Verify test cleanup between runs

## Phaser-Specific Rules

- Scene classes are thin rendering layers — no business logic
- `Scene.update(time, delta)` must only call entity/state methods; never contain `if/else` game logic
- `Scene.create()` wires entities to Phaser game objects only
- All game logic (state machines, physics calculations, rule evaluation) lives in `src/entities/`
  or `src/state/` — testable without Phaser via vitest
