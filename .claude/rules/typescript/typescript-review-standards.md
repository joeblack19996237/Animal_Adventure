# TypeScript Review Standards

Language-specific review checks for TypeScript phases.

---

## Compile Check

```bash
npx tsc --noEmit
npx eslint <file>
```

Run for every modified `.ts` / `.tsx` file in the diff.

## Security Checks (CRITICAL)

- XSS — `innerHTML` or `outerHTML` assignment from untrusted sources
- Code injection — `eval()` or `new Function()` with user-controlled input
- Prototype pollution — unvalidated keys passed to `Object.assign` or spread
- WebSocket / fetch — `JSON.parse` not wrapped in try/catch
- Hardcoded secrets — tokens or API keys in source; use `import.meta.env` only

## Performance Checks

- Allocations inside `Scene.update()` — creates GC pressure every frame (HIGH)
- Missing `destroy()` call on scene transitions — memory leak (HIGH)
- O(n²) algorithms inside the game loop (MEDIUM)

## Phaser Rules

- `Scene.update()` must only call entity/state methods — no inline `if/else` game logic (HIGH)
- `Scene.create()` must only wire entities to Phaser game objects (MEDIUM)

## Design/Quality Checks

- `any` type without `// justified:` comment (HIGH)
- Non-null assertion `!` without preceding guard (HIGH)
- `as Type` cast to silence type errors (HIGH)
- Missing tests for new logic (HIGH)

## Integration Test Review

When reviewing an integration/e2e phase:

- Verify `*.integration.test.ts` files test cross-component interactions
- Verify no `vi.mock()` for external service calls
- Verify test cleanup between runs — no shared mutable state
