# Python Review Standards

Language-specific review checks for Python phases.

---

## Compile Check

```bash
python -m py_compile <file>
```

Run for every modified `.py` file in the diff.

## Security Checks (CRITICAL)

- Hardcoded secrets, API keys, tokens, or passwords in source
- `pickle.loads()` on untrusted data — arbitrary code execution
- `yaml.load()` without `safe_load` — arbitrary code execution
- `subprocess(shell=True)` with user-controlled values — command injection
- SQL string concatenation — use parameterized queries
- Path traversal — user-controlled paths not resolved and boundary-checked

## Performance Checks (MEDIUM)

- N+1 queries — fetching related objects in a loop instead of a join/batch
- O(n²) algorithms where O(n log n) or O(n) is achievable
- Unbounded DB fetches — `SELECT *` without LIMIT on user-facing endpoints

## Design/Quality Checks

- Bare `except:` — always catch a specific exception type (HIGH)
- Functions >50 lines (HIGH for API/public surface, MEDIUM for private helpers)
- Missing tests for new logic (HIGH)

## Integration Test Review

When reviewing an integration/e2e phase:

- Verify `@pytest.mark.integration` is used on integration tests
- Verify marker is registered in `pytest.ini` or `conftest.py`
- Verify no `unittest.mock` for external dependencies in integration tests
- Verify fixture cleanup — each test starts and ends with clean state
- Verify cross-component paths are covered (not just happy-path unit coverage)
