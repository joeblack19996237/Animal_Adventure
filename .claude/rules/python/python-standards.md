# Python Standards

Python-specific rules that apply in addition to `rules/common/coding-standards.md`.

---

## Style (PEP 8)

- 4-space indentation. No tabs.
- Max line length: 100 characters.
- Two blank lines between top-level definitions; one blank line between methods.
- Imports: stdlib → third-party → local, separated by blank lines.
- No wildcard imports (`from module import *`).

## Type Hints

- All functions must have type annotations on parameters and return type.
- Use `list`, `dict`, `tuple` (lowercase) for generics — not `List`, `Dict`, `Tuple` from `typing`.
- Use `X | Y` union syntax (Python 3.10+) — not `Optional[X]` or `Union[X, Y]`.
- Use `from __future__ import annotations` if forward references are needed.

```python
# GOOD
def find_user(user_id: int) -> dict | None:
    ...

# BAD
def find_user(user_id):
    ...
```

## String Formatting

- Use f-strings for all string interpolation — not `.format()` or `%` formatting.

```python
# GOOD
message = f"Phase {phase_id} complete"

# BAD
message = "Phase {} complete".format(phase_id)
message = "Phase %d complete" % phase_id
```

## Error Handling

- Never use bare `except:` — always `except SomeError as e:`.
- Do not use `except Exception:` unless re-raising or logging.
- Use context managers (`with`) for file I/O and resource management.

## File I/O

- Use `pathlib.Path` for path manipulation — not `os.path` string joining.
- Always specify `encoding="utf-8"` when opening text files.

```python
# GOOD
from pathlib import Path
content = Path("workspace/state.json").read_text(encoding="utf-8")

# BAD
with open("workspace/state.json") as f:
    content = f.read()
```

## Functions and Classes

- No mutable default arguments — use `None` and initialize inside the function.
- Prefer `dataclass` or `TypedDict` over bare dicts for structured data when the schema is stable.
- Keep functions focused: one responsibility per function.

```python
# BAD — mutable default
def append_item(item: str, items: list = []) -> list:
    items.append(item)
    return items

# GOOD
def append_item(item: str, items: list | None = None) -> list:
    if items is None:
        items = []
    items.append(item)
    return items
```

## Testing (pytest)

- All tests live in `tests/` at the project root.
- Test files: `test_<module>.py`. Test functions: `test_<behavior>`.
- Use `pytest` fixtures for shared setup — not `setUp`/`tearDown`.
- Use `pytest.raises(SomeError)` to assert exceptions.
- No mocking the database or file system when integration tests are feasible.
- Run the full test suite with `pytest` from the project root.

```python
# GOOD test name
def test_returns_none_when_user_not_found():
    ...

# BAD test name
def test_find_user():
    ...
```

## Import Additions (ruff post-edit hook)

A `ruff format + isort` hook runs after every `Edit` and `Write`. If you add an import in one
`Edit` call and its first usage in a separate call, ruff will remove the import as unused
between the two calls.

**Rule: always combine a new import with at least one usage in the same `Edit` or `Write` call.**

```python
# BAD — two separate edits; ruff strips the import after the first
# Edit 1: add  "import logging"
# Edit 2: add  "logger = logging.getLogger(__name__)"

# GOOD — single edit adds both
import logging
logger = logging.getLogger(__name__)
```

## Patterns to Avoid

- No `global` variables in application code (constants are fine).
- No `__import__()` or dynamic imports unless essential.
- No `eval()` or `exec()`.
- No `time.sleep()` in production logic — use proper async or retry mechanisms.
- Prefer `pathlib` over `os.path`, `sys.path` manipulation, or string path joining.
