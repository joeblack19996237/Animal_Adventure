# Agent: code-reviewer

File: `.claude/agents/code-reviewer.md`

Adapted from `D:\AI\claude_code\everything-claude-code\agents\code-reviewer.md` (reuse security/quality/performance checklist).

## Output Contract

Add this block verbatim at the **top** of `.claude/agents/code-reviewer.md`, before all other sections:

```
## Output Contract
Your COMPLETE response must be the JSON signal below. Output ONLY the JSON object.
No prose, no status lines, no markdown fences before or after.
The Stop hook validates your output — any non-JSON content will trigger a correction prompt,
costing you an extra retry turn.
```

## Step 1 — Read the Spec (required before reviewing)

- Single-file spec: read `docs/spec.md`, locate the Phase N section
- Directory spec: read ALL `.md` files in the spec directory (architecture, data-model, workflow, build-plan)
- Extract: what was Phase N supposed to build? What were the explicit requirements?

## Step 2 — Scope the Diff

```
git diff {base_sha}..HEAD
```
Review ONLY files that appear in this diff. Do not review unchanged files.

## Step 3 — Review Across 4 Dimensions

| Order | Dimension | What to check | Source |
|-------|-----------|--------------|--------|
| 1st | **Functionality** | Does code implement ALL Phase N requirements from the spec? Missing features, wrong behavior, unmet requirements. Check each spec requirement explicitly. | spec + diff |
| 2nd | **Security** | Hardcoded secrets, injection, auth bypass, path traversal, insecure deps. These produce CRITICAL issues. | diff |
| 3rd | **Performance** | N+1 queries, O(n²) algorithms, unbounded queries, sync I/O in async context | diff |
| 4th | **Design/Quality** | Large functions (>50 lines), deep nesting, missing error handling, dead code, missing tests for new logic | diff |

Functionality is reviewed first because missing features are the most impactful finding. Security second because it produces CRITICAL-severity issues that block the phase. All four dimensions are checked in one `claude -p` call — sequential passes, not separate calls.

## Review Completion Self-check (before emitting signal)

- [ ] Read all spec files for Phase N requirements
- [ ] Ran `git diff {base_sha}..HEAD` and reviewed only those files
- [ ] All 4 dimensions checked in order: Functionality → Security → Performance → Design/Quality
- [ ] Every issue has: severity, file+line, dimension, description, suggested fix, `Status: open`
- [ ] Issues deduplicated (e.g., "5 functions missing error handling" → one consolidated issue)
- [ ] `review_report.md` ends with `## Summary` section showing severity counts and verdict

## Verdicts

- `APPROVE` — no CRITICAL, no HIGH → harness advances to next phase TASK_BUILD
- `WARN` — MEDIUM/LOW issues only → harness marks all issues `deferred` in state.json, appends them to tech_debt.jsonl, then advances to next phase TASK_BUILD
- `BLOCK` — any CRITICAL or HIGH → harness enters fix cycle; after all CRITICAL/HIGH fixed, advances to next phase TASK_BUILD (no re-review — fixes reviewed together with next phase tasks)

## review_report.md Lifecycle (kept clean per phase)

- Reviewer **overwrites** `review_report.md` at the start of each phase review (fresh slate per phase).
- `verify_fix()` **removes** the CRITICAL/HIGH entry after it is fixed and verified (WRITE 1: state.json → WRITE 2: review_report.md).
- After all CRITICAL/HIGH for a phase are fixed, harness reads MEDIUM/LOW issue IDs from state.json (already stored from the review signal) and appends each as a JSON line to `workspace/tech_debt.jsonl`. Harness then empties `review_report.md`.
- `review_report.md` is then **empty** and ready for the next phase's review.
- At any point: `review_report.md` = only active open CRITICAL/HIGH for the current phase.

## On `--resume` Entering FIXING State

Reconcile `review_report.md` before handing it to the fix agent:
- Read all issues from `state.json` for the current phase.
- Remove any entry from `review_report.md` whose `issue_id` maps to `status: "fixed"` in state.json.
- This handles the crash-between-writes case (state.json updated but `review_report.md` not yet cleaned) without re-attempting already-fixed issues.
- Source of truth is always state.json — `review_report.md` is derived from it on resume.

## workspace/tech_debt.jsonl — Deferred Issues Accumulator

- Collects all MEDIUM/LOW issues from every phase as newline-delimited JSON (one object per line).
- Harness appends entries from state.json issue data — never parsed from Markdown.
- Used exclusively by the CLEANUP pass after all phases complete; not read during normal phase work.
- On resume mid-CLEANUP: harness re-derives the active issue list from state.json (`status: "deferred"`) — file is secondary, state.json is authoritative.

## review_report.md Format

```markdown
# Phase 2 Review

## Issue 1 [HIGH] — Security
File: src/api/posts.py:23
Issue: No rate limiting on POST /posts endpoint
Fix: Add Flask-Limiter decorator

## Issue 2 [CRITICAL] — Functionality
File: src/api/users.py:41
Issue: POST /users does not return 409 on duplicate email — spec requirement 2.3
Fix: Query for existing email before insert, return 409 if found

## Summary
| Severity    | Open |
|-------------|------|
| CRITICAL    | 1    |
| HIGH        | 1    |
| MEDIUM      | 2    |
| LOW         | 0    |

Verdict: BLOCK — fix CRITICAL and HIGH before proceeding.
```

## tech_debt.jsonl Format

One JSON object per line, accumulated across phases:

```jsonl
{"id": "1.3", "phase_id": 1, "severity": "MEDIUM", "dimension": "Design/Quality", "file": "src/routes/users.py:55", "title": "Function exceeds 50 lines", "description": "Handles both validation and DB write", "fix": "Extract validate_user_input() helper", "status": "deferred"}
{"id": "1.4", "phase_id": 1, "severity": "LOW",    "dimension": "Design/Quality", "file": "src/models/user.py:12",   "title": "Magic number 8 for min password length", "description": "Literal value, no named constant", "fix": "Extract MIN_PASSWORD_LENGTH constant", "status": "deferred"}
{"id": "2.3", "phase_id": 2, "severity": "MEDIUM", "dimension": "Performance",    "file": "src/api/posts.py:77",     "title": "Loading all posts before filtering", "description": "Use SQL WHERE clause instead", "fix": "Pass filter to query directly", "status": "deferred"}
```

Harness appends entries directly from state.json issue data after each phase's fix cycle. The fix agent reads this file via its Read tool — JSON is readable. Harness removes a fixed entry by rewriting the file excluding lines where `id` matches a `status: "fixed"` issue in state.json.

## JSON Completion Signals

**REVIEW signal:**
```json
{
  "status": "complete",
  "mode": "REVIEW",
  "phase_id": 1,
  "verdict": "BLOCK",
  "sha_at_review": "abc1234",
  "issues": [
    {"id": "1.1", "severity": "CRITICAL", "dimension": "Functionality", "file": "src/api/users.py:41",    "title": "POST /users does not return 409 on duplicate email"},
    {"id": "1.2", "severity": "HIGH",     "dimension": "Security",      "file": "src/api/posts.py:23",    "title": "No rate limiting on POST /posts endpoint"},
    {"id": "1.3", "severity": "MEDIUM",   "dimension": "Design/Quality", "file": "src/routes/users.py:55", "title": "Function exceeds 50 lines"}
  ]
}
```

The reviewer writes `review_report.md` and emits this signal inside the subprocess. When the subprocess exits, harness parses the signal and writes the full issue list into `state.json`. As the fix cycle proceeds, CRITICAL/HIGH entries are removed from `review_report.md` one by one — `state.json` remains the complete audit trail for every issue across its full lifecycle.
# Phase 11 Targeted Re-Review

After CRITICAL/HIGH fixes pass harness verification, the reviewer can be called in targeted mode through `agents.review_fix()`. That prompt is scoped to the fixed issue IDs and safe diff range so the harness does not advance a blocked phase until targeted re-review returns no blocking issue.
