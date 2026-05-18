---
name: tdd-workflow
description: >
  Trigger keywords: write test, test first, TDD, red-green-refactor, pytest, implement feature,
  add function, fix bug, unit test, integration test, test coverage, failing test.
  Enforces red→green→refactor cycle for Python/pytest. Covers test types, AAA pattern,
  fixtures, parametrize, coverage requirements, and common mistakes.
origin: ECC (adapted for Python/pytest)
---

# Test-Driven Development Workflow

## Core Principles

1. **Tests before code** — always write the failing test first
2. **Coverage** — minimum 80% for new modules; all edge cases, error paths, and boundary conditions
3. **Isolation** — each test sets up its own data; no shared mutable state between tests

## Test Types

| Type | What it covers | Location |
|------|---------------|----------|
| Unit | Individual functions, pure logic, helpers | `tests/test_<module>.py` |
| Integration | DB operations, service interactions, API endpoints end-to-end | `tests/test_<module>_integration.py` |

E2E browser tests are out of scope for this harness.

## Red → Green → Refactor

### 1. Red — write the failing test

```python
# tests/test_store.py
def test_add_returns_task_with_id():
    store = TaskStore(path=tmp_path / "tasks.json")
    task = store.add("Buy milk")
    assert task["id"] == 1
    assert task["title"] == "Buy milk"
    assert task["done"] is False
```

```bash
pytest tests/test_store.py::test_add_returns_task_with_id -v
# MUST fail — function not implemented yet
```

### 2. Green — minimal implementation

Write only enough code to make the test pass. No extra logic.

```bash
pytest tests/test_store.py::test_add_returns_task_with_id -v
# MUST pass
```

### 3. Refactor — clean up

- Extract helpers for functions exceeding 50 lines
- Remove duplication
- Improve naming

```bash
pytest tests/test_store.py -v
# All tests must still pass after refactor
```

### 4. Full suite

```bash
pytest
# No regressions across all tests
```

## pytest Patterns

### AAA structure (Arrange — Act — Assert)

```python
def test_complete_marks_task_done():
    # Arrange
    store = TaskStore(path=tmp_path / "tasks.json")
    store.add("Buy milk")

    # Act
    updated = store.complete(1)

    # Assert
    assert updated["done"] is True
```

### Fixtures for shared setup

```python
import pytest
from pathlib import Path
from task_manager.store import TaskStore

@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(path=tmp_path / "tasks.json")


def test_add_persists(store: TaskStore):
    store.add("Buy milk")
    assert len(store.list()) == 1


def test_list_empty_by_default(store: TaskStore):
    assert store.list() == []
```

### Parametrize for edge cases

```python
@pytest.mark.parametrize("title", ["", " ", "a" * 1000])
def test_add_rejects_invalid_title(store: TaskStore, title: str):
    with pytest.raises(ValueError):
        store.add(title)
```

### Asserting exceptions

```python
def test_complete_raises_when_not_found(store: TaskStore):
    with pytest.raises(TaskNotFoundError, match="Task 99 not found"):
        store.complete(99)
```

### Integration test — real file I/O (no mocks)

```python
def test_persistence_survives_reload(tmp_path: Path):
    store = TaskStore(path=tmp_path / "tasks.json")
    store.add("Buy milk")

    # Simulate process restart — new instance, same file
    reloaded = TaskStore(path=tmp_path / "tasks.json")
    assert len(reloaded.list()) == 1
    assert reloaded.list()[0]["title"] == "Buy milk"
```

## Coverage Check

```bash
pytest --cov=<package> --cov-report=term-missing
# Target: 80%+ on new modules
```

If coverage for any new module is below 80%, **do not signal complete**. Examine the missing lines
shown in `--cov-report=term-missing` output and write tests targeting each uncovered line.
Repeat until 80% is reached. The only acceptable exception is a line that is genuinely
untestable boilerplate (e.g., a trivial `__repr__`); justify each such exclusion with an inline
comment: `# pragma: no cover — trivial repr`.

## Common Mistakes to Avoid

| Wrong | Right |
|-------|-------|
| Tests share a module-level `store = TaskStore(...)` | Each test gets a fresh instance via fixture |
| `assert result != None` | `assert result is not None` |
| Testing internal implementation details | Test observable behavior only |
| Mocking the file system when `tmp_path` works | Use `tmp_path` fixture for real I/O |
| Vague test name: `test_store()` | Descriptive: `test_add_returns_task_with_incremented_id()` |
| Empty `except` block in test | Let exceptions propagate — pytest catches them |
