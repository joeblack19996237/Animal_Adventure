# Integration Testing Guide

Build rules for integration and e2e phases. Read this guide when `phase_type` is `"integration"` or `"e2e"`.

---

## When to Use This Guide

This guide applies instead of standard TDD triplet rules. The phase title contains keywords like
"integration", "e2e", "end-to-end", or "verification".

---

## Task Classification

All tasks in this phase use:

```json
"tdd_mode": "exempt",
"tdd_skipped": "integration test — no TDD triplet required"
```

The Stop hook enforces that `tdd_skipped` is present and non-empty on every task.

---

## What Integration Tests Verify

- Cross-component interactions — two or more services calling each other
- Real service calls — no mocks for external dependencies
- Data flowing through the full stack — request in, response out, DB state updated
- NOT unit-level isolated logic (that belongs in development phases)

---

## Python Integration Test Patterns

- Use `@pytest.mark.integration` on every integration test function
- Register the marker in `pytest.ini`:
  ```ini
  [pytest]
  markers =
      integration: integration tests that require real services
  ```
- Use `conftest.py` fixtures for server startup, DB seed, and teardown
- Run with: `pytest -m integration --asyncio-mode=auto`
- No `unittest.mock` for external services — use real connections

Example fixture pattern:
```python
@pytest.fixture
def running_server():
    proc = start_server()
    yield proc
    proc.terminate()
```

---

## TypeScript Integration Test Patterns

- Name files `*.integration.test.ts`
- Use vitest with real service calls — no `vi.mock()` for external services
- Run with: `npx vitest run`
- Verify cleanup between test runs

---

## Test Isolation

- Each test starts with clean state
- Fixtures set up and tear down real services (start/stop server, seed/clear DB)
- No shared mutable state between tests

---

## File Scope

Integration tests may create or modify both `.py` and `.ts` files depending on the stack
being tested. Language tag on the phase is optional — write files in whatever language
the test requires.
