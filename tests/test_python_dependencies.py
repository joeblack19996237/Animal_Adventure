import importlib

import pytest


@pytest.mark.parametrize(
    "package",
    [
        "fastapi",
        "uvicorn",
        "aiosqlite",
        "pytest",
        "pytest_asyncio",
        "httpx",
        "websockets",
    ],
)
def test_python_dependencies_import(package: str) -> None:
    importlib.import_module(package)
