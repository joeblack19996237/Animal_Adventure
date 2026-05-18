# Python Builder Guide

Language-specific build instructions for Python phases.

---

## Test Command

```bash
pytest --asyncio-mode=auto
```

## Integration Test Command

```bash
pytest -m integration --asyncio-mode=auto
```

## Compile Check

```bash
python -m py_compile <file>
```

Run this for every new `.py` file before signaling complete.

## TDD Patterns

- Use `pytest` fixtures for shared setup (not `setUp`/`tearDown`)
- `pytest.raises(SomeError)` for expected exceptions
- AAA structure: Arrange → Act → Assert
- Target coverage ≥ 80% per module (`pytest --cov=<module>`)
- Test files in `tests/`, named `test_<module>.py`
- Test functions: `test_<behavior>` (e.g. `test_returns_none_when_user_not_found`)
- Keep first-pass tests representative and compact. Prefer parametrized cases over
  repeated near-identical test functions, and keep each new test file under 250 lines
  unless the phase explicitly requires exhaustive coverage.

## Integration Testing Patterns

See `.claude/rules/common/integration-testing-guide.md` when phase_type is `integration` or `e2e`.

- Mark integration tests with `@pytest.mark.integration`
- Register marker in `pytest.ini` or `conftest.py`
- Use `conftest.py` fixtures for server startup, DB seed/teardown
- No `unittest.mock` for external services in integration tests
