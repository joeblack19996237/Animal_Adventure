# TypeScript Standards

TypeScript-specific rules that apply in addition to `rules/common/coding-standards.md`.

---

## Style

- 2-space indentation. No tabs.
- Semicolons required.
- Single quotes for strings.
- Max line length: 100 characters.
- Two blank lines between top-level definitions; one between methods.
- camelCase for variables/functions; PascalCase for classes/interfaces/types/enums.
- No `var` — use `const` by default, `let` only when reassignment needed.

## Type Safety

- `tsconfig.json` must have `"strict": true` — never weaken it.
- No `any` — use `unknown` and narrow, or define a precise type. If unavoidable, add `// justified: <reason>`.
- No non-null assertion `value!` without a preceding guard.
- No `as Type` casts to silence errors — fix the type.
- All public functions must have explicit return type annotations.
- Use `X | Y` union syntax, not `Optional<X>` or `Union<X, Y>`.

## Async Patterns

- Every `async` function call must be `await`ed or have `.catch()`.
- Never `array.forEach(async fn)` — use `for...of` or `Promise.all(array.map(async fn))`.
- No floating promises in event handlers or constructors.
- `try/catch` around every `JSON.parse()` call.

## Immutability

- No mutable module-level variables — use constants or class instances.
- Use spread for state updates: `{ ...state, field: newValue }` not `state.field = newValue`.
- Prefer `readonly` on class fields that should not change after construction.

## Error Handling

- Never empty `catch` — log or re-throw.
- Always `throw new Error("message")`, not `throw "message"`.
- Wrap all WebSocket `send()` calls in try/catch — connection may drop.

## File I/O / Browser Patterns

- No `fs` module (browser environment) — use `fetch` for HTTP, `WebSocket` for WS.
- `import.meta.env` for environment variables (Vite), not `process.env`.
- All asset paths relative to `public/` directory.

## Phaser-Specific

- Scene classes are thin rendering layers — no business logic.
- `Scene.update(time, delta)` must only call entity/state methods; never contain `if/else` game logic.
- `Scene.create()` wires entities to Phaser game objects only.
- All game logic (state machines, physics calculations, rule evaluation) lives in `src/entities/`
  or `src/state/` — testable without Phaser via Vitest.

## Testing

- Unit/integration tests use Vitest (`*.test.ts` files in `tests/`).
- E2E tests use Playwright (`*.spec.ts` files in `tests/e2e/`).
- Test names: `it("returns empty list when no players", ...)` — behavior description, not method name.
- Playwright tests must register `page.on("pageerror")` and `page.on("console")` error listeners.
- No test-specific logic in production code.

## Import Additions (eslint post-edit hook)

A `prettier + eslint --fix` hook runs after every `Edit` and `Write`. If you add an import in one
`Edit` call and its first usage in a separate call, eslint may remove the import as unused
between the two calls.

**Rule: always combine a new import with at least one usage in the same `Edit` or `Write` call.**

## Patterns to Avoid

- No `eval()` or `new Function()` with user-controlled input.
- No `innerHTML` assignment from untrusted sources.
- No `document.write()`.
- No `==` — use `===` throughout.
- No `async` function inside `.forEach()`.
