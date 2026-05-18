from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def test_project_scaffold_required_dirs() -> None:
    required_dirs = [
        PROJECT_ROOT / "app",
        PROJECT_ROOT / "src",
        PROJECT_ROOT / "tests",
        PROJECT_ROOT / "config",
        PROJECT_ROOT / "docs",
        PROJECT_ROOT / "deploy" / "nginx",
        PROJECT_ROOT / "deploy" / "scripts",
        PROJECT_ROOT / "data",
        PROJECT_ROOT / "logs",
    ]
    for d in required_dirs:
        assert d.is_dir(), f"Required directory missing: {d.relative_to(PROJECT_ROOT)}"


def test_empty_scaffold_dirs_have_gitkeep() -> None:
    empty_dirs = [
        PROJECT_ROOT / "app",
        PROJECT_ROOT / "src",
        PROJECT_ROOT / "deploy" / "nginx",
        PROJECT_ROOT / "deploy" / "scripts",
        PROJECT_ROOT / "data",
        PROJECT_ROOT / "logs",
    ]
    for d in empty_dirs:
        gitkeep = d / ".gitkeep"
        assert gitkeep.exists(), f".gitkeep missing in {d.relative_to(PROJECT_ROOT)}"
