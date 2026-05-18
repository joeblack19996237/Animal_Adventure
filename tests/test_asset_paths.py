"""Tests for asset manifest structure and path existence.

Validates that config/assets.json is well-formed and every logical asset id
maps to an existing file under assets/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
ASSETS_JSON = REPO_ROOT / "config" / "assets.json"
ASSETS_DIR = REPO_ROOT / "assets"

MVP_REQUIRED_IDS = [
    "map_full",
    "npc_hopper",
    "npc_copper",
    "npc_elisa",
    "item_blanket",
    "item_bagpipe",
    "item_dance_shoes",
    "potion_l0",
    "accessory_sleepy_hat",
    "coin",
    "bgm_1",
    "bgm_2",
    "bgm_3",
    "bgm_4",
    "character_penguin_stand_front",
    "character_penguin_stand_back",
    "character_penguin_walk_front",
    "character_penguin_walk_side",
    "character_arctic_fox_stand_front",
    "character_arctic_fox_walk_front",
    "character_arctic_fox_walk_back",
    "character_arctic_fox_walk_side",
    "character_cat_snowman_stand_front",
    "character_cat_snowman_stand_back",
    "character_cat_snowman_walk_front",
    "character_cat_snowman_walk_side",
]


def _resolve_asset_url(url: str) -> Path:
    """Convert a /assets/... URL to an absolute local path.

    Raises ValueError for paths that don't start with /assets/ or contain
    path traversal sequences.
    """
    if not url.startswith("/assets/"):
        raise ValueError(f"Asset path must start with /assets/: {url!r}")
    if ".." in url:
        raise ValueError(f"Path traversal not allowed in asset path: {url!r}")
    relative = url[len("/assets/") :]
    resolved = (ASSETS_DIR / relative).resolve()
    if not resolved.is_relative_to(ASSETS_DIR.resolve()):
        raise ValueError(f"Resolved path escapes assets directory: {resolved}")
    return resolved


@pytest.fixture
def assets_manifest() -> dict[str, str]:
    return json.loads(ASSETS_JSON.read_text(encoding="utf-8"))


class TestManifestStructure:
    def test_assets_json_exists(self) -> None:
        assert ASSETS_JSON.exists(), "config/assets.json must exist"

    def test_assets_json_is_valid_json(self) -> None:
        content = ASSETS_JSON.read_text(encoding="utf-8")
        data = json.loads(content)
        assert isinstance(data, dict)

    def test_manifest_is_flat_dict_of_strings(
        self, assets_manifest: dict[str, str]
    ) -> None:
        for key, value in assets_manifest.items():
            assert isinstance(key, str), f"Key must be str: {key!r}"
            assert isinstance(value, str), (
                f"Value for {key!r} must be str, got {type(value).__name__}"
            )

    def test_manifest_is_not_empty(self, assets_manifest: dict[str, str]) -> None:
        assert len(assets_manifest) > 0, "config/assets.json must not be empty"

    def test_all_mvp_ids_present(self, assets_manifest: dict[str, str]) -> None:
        missing = [id_ for id_ in MVP_REQUIRED_IDS if id_ not in assets_manifest]
        assert not missing, f"Missing MVP asset ids in config/assets.json: {missing}"

    @pytest.mark.parametrize("asset_id", MVP_REQUIRED_IDS)
    def test_mvp_id_has_non_empty_path(
        self, asset_id: str, assets_manifest: dict[str, str]
    ) -> None:
        assert asset_id in assets_manifest, f"MVP asset id {asset_id!r} not in manifest"
        assert assets_manifest[asset_id].strip(), (
            f"Empty path for asset id {asset_id!r}"
        )


class TestAssetPathFormat:
    @pytest.mark.parametrize("asset_id", MVP_REQUIRED_IDS)
    def test_path_starts_with_assets_prefix(
        self, asset_id: str, assets_manifest: dict[str, str]
    ) -> None:
        url = assets_manifest[asset_id]
        assert url.startswith("/assets/"), (
            f"Asset {asset_id!r} path {url!r} must start with /assets/"
        )

    @pytest.mark.parametrize("asset_id", MVP_REQUIRED_IDS)
    def test_path_has_no_traversal(
        self, asset_id: str, assets_manifest: dict[str, str]
    ) -> None:
        url = assets_manifest[asset_id]
        assert ".." not in url, (
            f"Asset {asset_id!r} path {url!r} contains path traversal"
        )

    @pytest.mark.parametrize("asset_id", MVP_REQUIRED_IDS)
    def test_path_has_no_double_slashes(
        self, asset_id: str, assets_manifest: dict[str, str]
    ) -> None:
        url = assets_manifest[asset_id]
        assert "//" not in url, f"Asset {asset_id!r} path {url!r} contains double slash"

    @pytest.mark.parametrize(
        "bad_url",
        [
            "",
            "images/Items/foo.png",
            "assets/images/Items/foo.png",
            "/images/Items/foo.png",
            "/assets/../etc/passwd",
            "/other/path/file.png",
        ],
    )
    def test_invalid_url_raises(self, bad_url: str) -> None:
        with pytest.raises(ValueError):
            _resolve_asset_url(bad_url)


class TestAssetFilesExist:
    def test_assets_directory_exists(self) -> None:
        assert ASSETS_DIR.is_dir(), f"assets/ directory must exist at {ASSETS_DIR}"

    @pytest.mark.parametrize("asset_id", MVP_REQUIRED_IDS)
    def test_mvp_asset_file_exists(
        self, asset_id: str, assets_manifest: dict[str, str]
    ) -> None:
        url = assets_manifest[asset_id]
        file_path = _resolve_asset_url(url)
        assert file_path.exists(), (
            f"Asset {asset_id!r} -> {url!r} -> {file_path} does not exist on disk"
        )

    def test_all_manifest_paths_exist(self, assets_manifest: dict[str, str]) -> None:
        missing: list[str] = []
        for asset_id, url in assets_manifest.items():
            try:
                file_path = _resolve_asset_url(url)
            except ValueError as exc:
                missing.append(f"{asset_id}: invalid url — {exc}")
                continue
            if not file_path.exists():
                missing.append(f"{asset_id}: {url} -> {file_path}")
        assert not missing, "Missing or invalid asset paths:\n" + "\n".join(missing)

    def test_nonexistent_asset_is_detected(self) -> None:
        fake_url = "/assets/images/Items/nonexistent_xyz_asset_12345.png"
        file_path = _resolve_asset_url(fake_url)
        assert not file_path.exists(), (
            "Sanity check: known-nonexistent asset must not resolve to a real file"
        )
