from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import init_db
from subprocess_runner import cleanup_process_tree, resolve_missing_executable

REGISTRY_PATH = Path("workspace/eval_services.json")
EVAL_DIR = Path("workspace/eval-services")
EVAL_DB_PATH = EVAL_DIR / "eval.sqlite3"
EVAL_API_LOG = EVAL_DIR / "api.log"
EVAL_VITE_LOG = EVAL_DIR / "vite.log"
EVAL_NGINX_LOG = EVAL_DIR / "nginx.log"
NGINX_WRAPPER_PATH = EVAL_DIR / "nginx-wrapper.conf"


def register_pid(name: str, pid: int) -> None:
    REGISTRY_PATH.parent.mkdir(exist_ok=True)
    entries = _read_registry()
    entries = [entry for entry in entries if entry.get("pid") != pid]
    entries.append({"name": name, "pid": int(pid)})
    REGISTRY_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def start_service(
    name: str,
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    log_path: Path | None = None,
) -> int:
    existing = _running_entry(name)
    if existing:
        print(f"{name} already running with pid {existing['pid']}")
        return 0
    resolved = resolve_missing_executable(cmd)
    stdout_target = subprocess.DEVNULL
    stderr_target = subprocess.DEVNULL
    log_file = None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("ab")
        stdout_target = log_file
        stderr_target = subprocess.STDOUT
    popen_kwargs = {
        "stdout": stdout_target,
        "stderr": stderr_target,
    }
    if env is not None:
        popen_kwargs["env"] = env
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(resolved, **popen_kwargs)
    except FileNotFoundError:
        if log_file is not None:
            log_file.close()
        print(f"{resolved[0]} is not available", file=sys.stderr)
        return 1
    finally:
        if log_file is not None:
            log_file.close()
    register_pid(name, proc.pid)
    print(f"{name} started with pid {proc.pid}")
    return 0


def check_nginx() -> int:
    wrapper = write_nginx_wrapper()
    cmd = resolve_missing_executable(
        ["nginx", "-t", "-p", f"{EVAL_DIR.resolve()}\\", "-c", str(wrapper.resolve())]
    )
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print("nginx is not available", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print((result.stderr or result.stdout).strip(), file=sys.stderr)
    return result.returncode


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _is_pid_running_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_registered() -> None:
    entries = _read_registry()
    for entry in entries:
        pid = int(entry.get("pid", 0) or 0)
        if not is_pid_running(pid):
            continue
        cleanup_process_tree(pid, include_root=True)
    if REGISTRY_PATH.exists():
        REGISTRY_PATH.unlink()


def init_eval_database() -> Path:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    init_db(EVAL_DB_PATH)
    return EVAL_DB_PATH


def api_environment() -> dict[str, str]:
    db_path = init_eval_database()
    return {
        **os.environ,
        "DATABASE_PATH": str(db_path.resolve()),
    }


def write_nginx_wrapper() -> Path:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "logs").mkdir(parents=True, exist_ok=True)
    project_root = Path.cwd().resolve()
    ensure_project_nginx_config(project_root)
    nginx_root = _nginx_root()
    project = str(project_root).replace("\\", "/")
    nginx = str(nginx_root).replace("\\", "/")
    wrapper = f"""error_log {project}/workspace/eval-services/nginx-error.log;
pid {project}/workspace/eval-services/nginx.pid;

events {{}}

http {{
    include {nginx}/conf/mime.types;
    default_type application/octet-stream;
    access_log {project}/workspace/eval-services/nginx-access.log;
    client_body_temp_path {project}/workspace/eval-services/client_body_temp;
    proxy_temp_path {project}/workspace/eval-services/proxy_temp;
    fastcgi_temp_path {project}/workspace/eval-services/fastcgi_temp;
    uwsgi_temp_path {project}/workspace/eval-services/uwsgi_temp;
    scgi_temp_path {project}/workspace/eval-services/scgi_temp;
    include {project}/deploy/nginx/animal-adventure.nginx.conf;
}}
"""
    NGINX_WRAPPER_PATH.write_text(wrapper, encoding="ascii")
    return NGINX_WRAPPER_PATH


def ensure_project_nginx_config(project_root: Path) -> Path:
    template_path = project_root / "deploy" / "nginx" / "animal-adventure.nginx.conf.template"
    output_path = project_root / "deploy" / "nginx" / "animal-adventure.nginx.conf"
    if not template_path.exists():
        return output_path
    normalized_root = str(project_root).replace("\\", "/")
    content = template_path.read_text(encoding="utf-8")
    generated = content.replace("{{PROJECT_ROOT}}", normalized_root)
    output_path.write_text(generated, encoding="utf-8")
    return output_path


def start_api() -> int:
    return start_service(
        "api",
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        env=api_environment(),
        log_path=EVAL_API_LOG,
    )


def start_vite() -> int:
    return start_service(
        "vite",
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
        log_path=EVAL_VITE_LOG,
    )


def start_nginx() -> int:
    if check_nginx() != 0:
        return 1
    wrapper = write_nginx_wrapper()
    return start_service(
        "nginx",
        [
            "nginx",
            "-p",
            f"{EVAL_DIR.resolve()}\\",
            "-c",
            str(wrapper.resolve()),
            "-g",
            "daemon off;",
        ],
        log_path=EVAL_NGINX_LOG,
    )


def _running_entry(name: str) -> dict | None:
    for entry in _read_registry():
        if entry.get("name") == name and is_pid_running(int(entry.get("pid", 0) or 0)):
            return entry
    return None


def _read_registry() -> list[dict]:
    if not REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _nginx_root() -> Path:
    env_root = os.environ.get("NGINX_ROOT")
    if env_root:
        return Path(env_root)
    resolved = resolve_missing_executable(["nginx"])
    if resolved and resolved[0] != "nginx":
        return Path(resolved[0]).resolve().parent
    return Path(r"D:\nginx")


def _is_pid_running_windows(pid: int) -> bool:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    exit_code = wintypes.DWORD()
    try:
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "Usage: python harness/eval_services.py "
            "cleanup|start-api|start-vite|start-nginx|check-nginx",
            file=sys.stderr,
        )
        sys.exit(2)
    command = sys.argv[1]
    if command == "cleanup":
        stop_registered()
    elif command == "start-api":
        sys.exit(start_api())
    elif command == "start-vite":
        sys.exit(start_vite())
    elif command == "start-nginx":
        sys.exit(start_nginx())
    elif command == "check-nginx":
        sys.exit(check_nginx())
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(2)
