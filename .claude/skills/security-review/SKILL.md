---
name: security-review
description: >
  Trigger keywords: security, vulnerability, sanitize, validate input, injection, subprocess,
  shell command, path traversal, credentials, secret, API key, deserialize, pickle, yaml.load,
  untrusted data, file path, user-controlled, sensitive data.
  Provides Python-specific security checklist covering subprocess safety, deserialization,
  path traversal, secrets management, and sensitive data exposure.
origin: ECC (adapted for Python)
---

# Security Review Skill

## When to Activate

- Handling user input or external data
- Working with secrets or credentials
- Running subprocesses or shell commands
- Deserializing data (pickle, yaml, json from untrusted sources)
- Accessing the file system with user-controlled paths
- Making HTTP requests to external services

## Security Checklist

### 1. Secrets Management

#### FAIL: Never hardcode secrets
```python
api_key = "sk-proj-xxxxx"       # hardcoded secret
db_password = "password123"     # in source code
```

#### PASS: Load from environment
```python
import os

api_key = os.environ["OPENAI_API_KEY"]
db_url = os.environ["DATABASE_URL"]

if not api_key:
    raise RuntimeError("OPENAI_API_KEY not configured")
```

#### Verification Steps
- [ ] No hardcoded API keys, tokens, or passwords
- [ ] All secrets in environment variables or `.env` (gitignored)
- [ ] No secrets in git history
- [ ] `.env` in `.gitignore`

### 2. Input Validation

#### Validate at system boundaries
```python
def process_task(title: str) -> dict:
    if not title or not title.strip():
        raise ValueError("title must be a non-empty string")
    if len(title) > 500:
        raise ValueError("title must be 500 characters or fewer")
    return {"title": title.strip()}
```

#### Schema validation for external data
```python
import jsonschema

SCHEMA = {
    "type": "object",
    "required": ["title"],
    "properties": {
        "title": {"type": "string", "minLength": 1, "maxLength": 500}
    },
    "additionalProperties": False,
}

def load_config(data: dict) -> dict:
    jsonschema.validate(data, SCHEMA)
    return data
```

#### Verification Steps
- [ ] All external inputs validated before use
- [ ] Schema or type checks on JSON/config loaded from disk or network
- [ ] Error messages do not leak internal details

### 3. Subprocess Safety

#### FAIL: Never pass user input to shell=True
```python
import subprocess
subprocess.run(f"git log {branch}", shell=True)   # command injection
os.system(f"ls {user_path}")                       # command injection
```

#### PASS: Use argument lists, shell=False
```python
import subprocess
subprocess.run(["git", "log", branch], check=True)
subprocess.run(["ls", user_path], check=True)
```

#### Verification Steps
- [ ] `shell=True` never used with user-controlled values
- [ ] All subprocess calls use list form
- [ ] User-controlled strings never passed to `eval()` or `exec()`

### 4. Deserialization Safety

#### FAIL: Pickle and unsafe YAML on untrusted data
```python
import pickle, yaml
data = pickle.loads(user_bytes)         # arbitrary code execution
config = yaml.load(file)               # arbitrary code execution
```

#### PASS: Safe alternatives
```python
import json, yaml
data = json.loads(user_bytes)          # safe — no code execution
config = yaml.safe_load(file)         # safe loader
```

#### Verification Steps
- [ ] `pickle.loads` never used on untrusted data
- [ ] `yaml.load` replaced with `yaml.safe_load`
- [ ] JSON preferred over pickle for serialization

### 5. Path Traversal Prevention

#### FAIL: User-controlled paths used directly
```python
def read_file(filename: str) -> str:
    return open(f"data/{filename}").read()   # ../../etc/passwd
```

#### PASS: Resolve and validate within allowed directory
```python
from pathlib import Path

BASE = Path("data").resolve()

def read_file(filename: str) -> str:
    target = (BASE / filename).resolve()
    if not str(target).startswith(str(BASE)):
        raise PermissionError("path traversal detected")
    return target.read_text()
```

#### Verification Steps
- [ ] User-controlled filenames validated against an allowed base path
- [ ] `Path.resolve()` used before any path comparison
- [ ] Temp files created with `tempfile` module, not manual paths

### 6. Sensitive Data Exposure

#### FAIL: Logging secrets or stack traces
```python
print(f"Connecting with password: {password}")
except Exception as e:
    return {"error": str(e), "trace": traceback.format_exc()}
```

#### PASS: Redact and log generically
```python
import logging
logger = logging.getLogger(__name__)

logger.info("Connecting to database (credentials redacted)")
except Exception:
    logger.exception("Internal error during DB connect")
    raise RuntimeError("Database connection failed") from None
```

#### Verification Steps
- [ ] No passwords, tokens, or secrets in log output
- [ ] Error messages returned to callers are generic
- [ ] Stack traces logged server-side only, not returned to callers
- [ ] No `print()` debug statements in production paths

### 7. Dependency Security

```bash
# Check for known vulnerabilities
pip-audit

# Review direct dependencies
pip list --outdated
```

#### Verification Steps
- [ ] `requirements.txt` pinned or constrained versions
- [ ] `pip-audit` clean (no known CVEs)
- [ ] No unnecessary dependencies added

## Pre-Completion Security Checklist

Before signaling `status: complete` on any task involving the above triggers:

- [ ] **Secrets**: No hardcoded secrets, all in env vars
- [ ] **Input Validation**: All external inputs validated
- [ ] **Subprocess**: `shell=True` never used with user data
- [ ] **Deserialization**: `yaml.safe_load`, no `pickle` on untrusted data
- [ ] **Path Traversal**: User paths resolved and validated
- [ ] **Error Handling**: No sensitive data in error messages or logs
- [ ] **Debug Output**: No `print()` statements left in production paths

## Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python.org/dev/security/)
- [CWE/SANS Top 25](https://cwe.mitre.org/top25/)

---

## TypeScript / Browser

### XSS Prevention

#### FAIL: innerHTML from untrusted sources
```typescript
element.innerHTML = userContent;       // XSS vector
element.outerHTML = apiResponse.html;  // XSS vector
```

#### PASS: Safe alternatives
```typescript
element.textContent = userContent;                // safe — no HTML parsing
element.innerHTML = DOMPurify.sanitize(html);     // safe — sanitized
```

#### Verification Steps
- [ ] No `innerHTML` / `outerHTML` assigned from external data
- [ ] HTML from APIs passed through DOMPurify before injection

### Code Injection

#### FAIL
```typescript
eval(userInput);
new Function(apiResponse.code)();
```

#### PASS: Never evaluate external strings as code
```typescript
// Parse JSON with try/catch, never eval
const data = JSON.parse(responseText);
```

#### Verification Steps
- [ ] No `eval()` or `new Function()` with external input
- [ ] `JSON.parse()` always inside `try/catch`

### Prototype Pollution

#### FAIL
```typescript
Object.assign(target, userObject);    // if userObject contains __proto__
```

#### PASS: Validate keys before merging
```typescript
const safe = Object.fromEntries(
    Object.entries(userObject).filter(([k]) => !["__proto__", "constructor", "prototype"].includes(k))
);
Object.assign(target, safe);
```

#### Verification Steps
- [ ] Keys validated before `Object.assign` or spread with user-controlled objects

### WebSocket / Fetch

#### FAIL
```typescript
const data = JSON.parse(event.data);  // unguarded
```

#### PASS
```typescript
try {
    const data = JSON.parse(event.data) as unknown;
    if (!isValidMessage(data)) throw new Error("invalid shape");
} catch (e) {
    logger.error("Bad WebSocket message", e);
}
```

#### Verification Steps
- [ ] All `JSON.parse()` in try/catch
- [ ] Type guards applied before using parsed data

### Secrets

#### FAIL
```typescript
const API_KEY = "sk-proj-xxxxx";         // hardcoded
console.log(`token: ${authToken}`);      // logged
```

#### PASS
```typescript
const apiKey = import.meta.env.VITE_API_KEY;
```

#### Verification Steps
- [ ] No tokens or API keys in source — use `import.meta.env` only
- [ ] No sensitive values in `console.log`

### Dependencies

```bash
npm audit
```

#### Verification Steps
- [ ] `npm audit` reports no critical or high vulnerabilities
- [ ] No unnecessary packages added
