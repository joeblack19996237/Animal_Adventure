# Common Coding Standards

Universal rules that apply to all languages and all agents.

---

## Naming

- Use descriptive names. Single-letter variables only in trivial loop indices.
- Functions: verb-noun pattern — `fetch_user()`, `validate_input()`, `calculate_total()`.
- Booleans: `is_`, `has_`, `can_` prefix — `is_valid`, `has_permission`.
- Constants: `UPPER_SNAKE_CASE`.
- No abbreviations unless universally understood (`url`, `id`, `db`).

## Error Handling

- Never use bare `except:` — always catch a specific exception type.
- Never swallow exceptions silently. Log or re-raise.
- Validate at system boundaries (user input, external APIs). Trust internal code.
- Do not expose internal error details to callers — wrap with a domain error or generic message.

## Code Quality

- Functions: max 50 lines. If longer, extract helpers.
- Nesting: max 4 levels. Use early returns to flatten.
- No magic numbers — extract named constants.
- No dead code (commented-out blocks, unused imports, unreachable branches).
- No `TODO` left in committed code — either fix it or open a tracked issue.

## Logging and Debug Output

- No `print()` statements in production code. Use the logging module or structured logging.
- No debug log statements left in committed code.
- Never log sensitive data (tokens, passwords, PII).

## Security

- No hardcoded secrets, API keys, passwords, or connection strings in source.
- Use environment variables or a secrets manager for credentials.
- Validate and sanitize all user input before use.
- No string concatenation for SQL queries — use parameterized queries.
- No path traversal — sanitize file paths derived from user input.

## Testing

- New logic requires tests. No new function without at least one test.
- Tests must be independent — no shared mutable state between test cases.
- Test names must describe behavior: `test_returns_empty_list_when_no_results`.
- No skipping tests without a documented reason.
- Tests must pass before code is committed.

## Comments

- Comments explain WHY, not WHAT. Code explains what; comments explain non-obvious constraints.
- No multi-paragraph docstrings for internal functions.
- No comments that restate the code: `# increment counter` above `count += 1`.
