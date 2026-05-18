---
name: tdd-workflow-ts
description: >
  Trigger keywords: write test, test first, TDD, red-green-refactor, vitest, implement feature,
  add function, fix bug, unit test, integration test, test coverage, failing test.
  Enforces red→green→refactor cycle for TypeScript/vitest. Covers test types, AAA pattern,
  coverage requirements, Phaser-specific patterns, and common mistakes.
origin: ECC (adapted for TypeScript/vitest)
---

# Test-Driven Development Workflow (TypeScript)

## Core Principles

1. **Tests before code** — always write the failing test first
2. **Coverage** — minimum 80% for new modules; all edge cases, error paths, and boundary conditions
3. **Isolation** — each test sets up its own data; no shared mutable state between tests

## Test Types

| Type | What it covers | Location |
|------|---------------|----------|
| Unit | Individual functions, pure logic, entities, helpers | `tests/*.test.ts` |
| Integration | WebSocket interactions, service calls, multi-component flows | `tests/*.integration.test.ts` |

E2E browser tests use Playwright (`tests/e2e/*.spec.ts`) and are separate from this workflow.

## Red → Green → Refactor

### 1. Red — write the failing test

```typescript
// tests/entity.test.ts
import { describe, it, expect } from 'vitest';
import { PlayerEntity } from '../src/entities/PlayerEntity';

describe('PlayerEntity', () => {
  it('starts with full health', () => {
    const player = new PlayerEntity({ x: 0, y: 0 });
    expect(player.health).toBe(100);
  });
});
```

```bash
npx vitest run tests/entity.test.ts
# MUST fail — class not implemented yet
```

### 2. Green — minimal implementation

Write only enough code to make the test pass. No extra logic.

```bash
npx vitest run tests/entity.test.ts
# MUST pass
```

### 3. Refactor — clean up

- Extract helpers for functions exceeding 50 lines
- Remove duplication
- Improve naming
- Ensure strict TypeScript — no `any`

```bash
npx vitest run
# All tests must still pass after refactor
```

### 4. Full suite

```bash
npx vitest run
# No regressions across all tests
```

## vitest Patterns

### AAA structure (Arrange — Act — Assert)

```typescript
it('advances player position on move', () => {
  // Arrange
  const player = new PlayerEntity({ x: 0, y: 0 });

  // Act
  player.move('right', 10);

  // Assert
  expect(player.x).toBe(10);
  expect(player.y).toBe(0);
});
```

### describe / it blocks for grouping

```typescript
describe('GameStore', () => {
  describe('addPlayer', () => {
    it('returns player with assigned id', () => {
      const store = new GameStore();
      const player = store.addPlayer('Alice');
      expect(player.id).toBeDefined();
      expect(player.name).toBe('Alice');
    });

    it('increments player count', () => {
      const store = new GameStore();
      store.addPlayer('Alice');
      store.addPlayer('Bob');
      expect(store.playerCount).toBe(2);
    });
  });
});
```

### Asserting errors

```typescript
it('throws when player not found', () => {
  const store = new GameStore();
  expect(() => store.getPlayer('missing-id')).toThrow('Player not found');
});
```

### Type-safe mocks (use sparingly — prefer real implementations)

```typescript
import { vi } from 'vitest';

it('calls onScoreChange callback', () => {
  const onScoreChange = vi.fn();
  const scorer = new Scorer({ onScoreChange });
  scorer.add(10);
  expect(onScoreChange).toHaveBeenCalledWith(10);
});
```

## Phaser-Specific Rules

- **Never test Scene classes directly** — Phaser requires a running renderer; Scene classes are thin layers with no logic to test.
- **Test entities and state** — all game logic lives in `src/entities/` and `src/state/`, testable without Phaser.
- Entities must be constructible without a Phaser scene: no `this.scene.add.*` calls in entity constructors.

```typescript
// GOOD — pure entity, testable without Phaser
export class BallEntity {
  x: number;
  y: number;
  vx: number = 0;
  vy: number = 0;

  constructor(x: number, y: number) {
    this.x = x;
    this.y = y;
  }

  update(delta: number): void {
    this.x += this.vx * delta;
    this.y += this.vy * delta;
  }
}

// tests/ball.test.ts
it('moves horizontally by velocity * delta', () => {
  const ball = new BallEntity(0, 0);
  ball.vx = 5;
  ball.update(2);
  expect(ball.x).toBe(10);
});
```

## Coverage Check

```bash
npx vitest run --coverage
# Target: 80%+ on new modules
```

If coverage for any new module is below 80%, examine uncovered lines and write tests targeting each.
The only acceptable exception is untestable boilerplate; justify with `// istanbul ignore next`.

## Common Mistakes to Avoid

| Wrong | Right |
|-------|-------|
| Game logic in `Scene.update()` | Move logic to entity/state classes, test those |
| `expect(result).not.toBe(null)` | `expect(result).toBeDefined()` or `expect(result).not.toBeNull()` |
| Testing implementation internals | Test observable behaviour only |
| `vi.mock()` for external services in integration tests | Use real connections; see integration-testing-guide.md |
| Vague test name: `it('works')` | Descriptive: `it('returns empty list when no players connected')` |
| Shared mutable state between `it` blocks | Use fresh instances in each `it` block |
