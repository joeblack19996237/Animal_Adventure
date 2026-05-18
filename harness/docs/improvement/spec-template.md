# Spec Template

This file shows the required format for a harness spec. Each phase uses the `## Phase N:` header.
The harness parses phase headers with: `## Phase N: Title` or `## Phase N — Title`.

Drop your `spec.md` into `docs/` and run:
```bash
python harness/harness.py docs/spec.md
```

> **Directory spec**: place multiple `.md` files in `docs/spec/` and pass the directory path.
> The harness reads all `.md` files in the directory and concatenates them for parsing.

---

# Example Spec: Task Manager CLI

A simple command-line task manager. Users can add, list, complete, and delete tasks. Tasks persist to a JSON file.

---

## Phase 1: Foundation & Storage

Build the project scaffold and task persistence layer.

**Requirements:**
- `task_manager/` package with `__init__.py`
- `TaskStore` class in `task_manager/store.py` that reads and writes tasks to `tasks.json`
- Task schema: `{"id": int, "title": str, "done": bool, "created_at": str}`
- `TaskStore.add(title: str) -> dict` — creates and persists a new task, returns it
- `TaskStore.list() -> list[dict]` — returns all tasks sorted by id ascending
- `TaskStore.get(task_id: int) -> dict | None` — returns one task or None
- `TaskStore.save(tasks: list[dict]) -> None` — writes tasks to `tasks.json` atomically (`.tmp` + rename)
- All storage operations raise `StorageError` (custom exception in `task_manager/exceptions.py`) on I/O failure
- Tests in `tests/test_store.py` covering add, list, get, and persistence

---

## Phase 2: Task Operations

Add complete and delete operations, then expose them via a CLI entry point.

**Requirements:**
- `TaskStore.complete(task_id: int) -> dict` — marks task done, persists, returns updated task; raises `TaskNotFoundError` if id missing
- `TaskStore.delete(task_id: int) -> None` — removes task, persists; raises `TaskNotFoundError` if id missing
- `TaskNotFoundError` in `task_manager/exceptions.py` (subclass of `StorageError`)
- CLI entry point `task_manager/cli.py` using `argparse`:
  - `python -m task_manager add "Buy milk"` — prints `Added: [1] Buy milk`
  - `python -m task_manager list` — prints all tasks, one per line: `[1] Buy milk (pending)`
  - `python -m task_manager done <id>` — prints `Done: [1] Buy milk`
  - `python -m task_manager delete <id>` — prints `Deleted: [1]`
  - `python -m task_manager list --done` — shows only completed tasks
- `task_manager/__main__.py` delegates to `cli.main()`
- Tests in `tests/test_cli.py` covering each subcommand via `subprocess` or `argparse` directly
- Full `pytest` suite passes with no regressions from Phase 1
