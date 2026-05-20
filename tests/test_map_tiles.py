"""Tests for map tile manifest validation.

Validates config/map_tiles.json records, image paths, coordinate coverage,
MVP edge dimensions, and image file dimensions against assets/images/MapTiles/.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).parent.parent
MAP_TILES_JSON = REPO_ROOT / "config" / "map_tiles.json"
ASSETS_IMAGES_DIR = REPO_ROOT / "assets" / "images"
MAP_TILES_DIR = ASSETS_IMAGES_DIR / "MapTiles"

MAP_WIDTH = 5430
MAP_HEIGHT = 7240
STANDARD_TILE_SIZE = 1024
LAST_COLUMN_WIDTH = 310
LAST_ROW_HEIGHT = 72
EXPECTED_COLUMNS = 6
EXPECTED_ROWS = 8
EXPECTED_TILE_COUNT = 48

TILE_REQUIRED_FIELDS = {"id", "path", "x", "y", "width", "height"}


def _read_png_dimensions(file_path: Path) -> tuple[int, int]:
    """Read width and height from a PNG file header without external libraries.

    PNG layout: signature(8) + chunk_length(4) + 'IHDR'(4) + width(4) + height(4).
    Width and height are big-endian unsigned 32-bit integers at bytes 16..24.
    """
    with file_path.open("rb") as f:
        header = f.read(24)
    if len(header) < 24:
        raise ValueError(f"File too short to be a valid PNG: {file_path}")
    png_signature = b"\x89PNG\r\n\x1a\n"
    if header[:8] != png_signature:
        raise ValueError(f"Not a valid PNG file: {file_path}")
    width, height = struct.unpack(">II", header[16:24])
    return width, height


@pytest.fixture
def map_tiles_manifest() -> dict[str, Any]:
    return json.loads(MAP_TILES_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def tiles(map_tiles_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return map_tiles_manifest["tiles"]


class TestMapTilesManifestStructure:
    def test_map_tiles_json_exists(self) -> None:
        assert MAP_TILES_JSON.exists(), "config/map_tiles.json must exist"

    def test_map_tiles_json_is_valid_json(self) -> None:
        content = MAP_TILES_JSON.read_text(encoding="utf-8")
        data = json.loads(content)
        assert isinstance(data, dict)

    def test_manifest_has_required_top_level_fields(
        self, map_tiles_manifest: dict[str, Any]
    ) -> None:
        required = {
            "tile_width",
            "tile_height",
            "map_width",
            "map_height",
            "columns",
            "rows",
            "tiles",
        }
        missing = required - set(map_tiles_manifest.keys())
        assert not missing, f"Missing top-level fields in map_tiles.json: {missing}"

    def test_manifest_map_dimensions(self, map_tiles_manifest: dict[str, Any]) -> None:
        assert map_tiles_manifest["map_width"] == MAP_WIDTH
        assert map_tiles_manifest["map_height"] == MAP_HEIGHT

    def test_manifest_default_tile_size(
        self, map_tiles_manifest: dict[str, Any]
    ) -> None:
        assert map_tiles_manifest["tile_width"] == STANDARD_TILE_SIZE
        assert map_tiles_manifest["tile_height"] == STANDARD_TILE_SIZE

    def test_manifest_columns_and_rows(
        self, map_tiles_manifest: dict[str, Any]
    ) -> None:
        assert map_tiles_manifest["columns"] == EXPECTED_COLUMNS
        assert map_tiles_manifest["rows"] == EXPECTED_ROWS

    def test_tile_count_matches_columns_times_rows(
        self, map_tiles_manifest: dict[str, Any]
    ) -> None:
        tile_list = map_tiles_manifest["tiles"]
        assert len(tile_list) == EXPECTED_TILE_COUNT, (
            f"Expected {EXPECTED_TILE_COUNT} tiles, got {len(tile_list)}"
        )

    def test_each_tile_has_required_fields(self, tiles: list[dict[str, Any]]) -> None:
        for tile in tiles:
            missing = TILE_REQUIRED_FIELDS - set(tile.keys())
            assert not missing, (
                f"Tile {tile.get('id', '?')!r} missing fields: {missing}"
            )

    def test_tile_ids_are_unique(self, tiles: list[dict[str, Any]]) -> None:
        ids = [tile["id"] for tile in tiles]
        assert len(ids) == len(set(ids)), "Tile ids must be unique"

    def test_tile_field_types(self, tiles: list[dict[str, Any]]) -> None:
        for tile in tiles:
            tile_id = tile.get("id", "?")
            assert isinstance(tile["id"], str), f"Tile {tile_id!r}: id must be str"
            assert isinstance(tile["path"], str), f"Tile {tile_id!r}: path must be str"
            assert isinstance(tile["x"], int), f"Tile {tile_id!r}: x must be int"
            assert isinstance(tile["y"], int), f"Tile {tile_id!r}: y must be int"
            assert isinstance(tile["width"], int), (
                f"Tile {tile_id!r}: width must be int"
            )
            assert isinstance(tile["height"], int), (
                f"Tile {tile_id!r}: height must be int"
            )


class TestMapTilePaths:
    def test_map_tiles_directory_exists(self) -> None:
        assert MAP_TILES_DIR.is_dir(), (
            f"MapTiles directory must exist at {MAP_TILES_DIR}"
        )

    def test_each_tile_path_has_no_traversal(self, tiles: list[dict[str, Any]]) -> None:
        for tile in tiles:
            assert ".." not in tile["path"], (
                f"Tile {tile['id']!r} path contains traversal: {tile['path']!r}"
            )

    def test_each_tile_path_resolves_within_images_dir(
        self, tiles: list[dict[str, Any]]
    ) -> None:
        images_root = ASSETS_IMAGES_DIR.resolve()
        for tile in tiles:
            resolved = (ASSETS_IMAGES_DIR / tile["path"]).resolve()
            assert resolved.is_relative_to(images_root), (
                f"Tile {tile['id']!r} path escapes images dir: {tile['path']!r}"
            )

    def test_each_tile_file_exists(self, tiles: list[dict[str, Any]]) -> None:
        missing: list[str] = []
        for tile in tiles:
            file_path = ASSETS_IMAGES_DIR / tile["path"]
            if not file_path.exists():
                missing.append(f"{tile['id']}: {tile['path']}")
        assert not missing, "Missing tile image files:\n" + "\n".join(missing)

    def test_no_unexpected_files_in_map_tiles_dir(
        self, tiles: list[dict[str, Any]]
    ) -> None:
        expected_names = {Path(tile["path"]).name for tile in tiles}
        actual_names = {f.name for f in MAP_TILES_DIR.iterdir() if f.is_file()}
        unexpected = actual_names - expected_names
        assert not unexpected, f"Unexpected files in MapTiles/: {sorted(unexpected)}"


class TestMapTileCoordinates:
    def test_all_tile_x_coordinates_non_negative(
        self, tiles: list[dict[str, Any]]
    ) -> None:
        for tile in tiles:
            assert tile["x"] >= 0, (
                f"Tile {tile['id']!r}: x must be >= 0, got {tile['x']}"
            )

    def test_all_tile_y_coordinates_non_negative(
        self, tiles: list[dict[str, Any]]
    ) -> None:
        for tile in tiles:
            assert tile["y"] >= 0, (
                f"Tile {tile['id']!r}: y must be >= 0, got {tile['y']}"
            )

    def test_no_tile_extends_beyond_map_width(
        self, tiles: list[dict[str, Any]]
    ) -> None:
        for tile in tiles:
            right_edge = tile["x"] + tile["width"]
            assert right_edge <= MAP_WIDTH, (
                f"Tile {tile['id']!r}: right edge {right_edge} exceeds map_width {MAP_WIDTH}"
            )

    def test_no_tile_extends_beyond_map_height(
        self, tiles: list[dict[str, Any]]
    ) -> None:
        for tile in tiles:
            bottom_edge = tile["y"] + tile["height"]
            assert bottom_edge <= MAP_HEIGHT, (
                f"Tile {tile['id']!r}: bottom edge {bottom_edge} exceeds map_height {MAP_HEIGHT}"
            )

    def test_tile_widths_are_positive(self, tiles: list[dict[str, Any]]) -> None:
        for tile in tiles:
            assert tile["width"] > 0, (
                f"Tile {tile['id']!r}: width must be positive, got {tile['width']}"
            )

    def test_tile_heights_are_positive(self, tiles: list[dict[str, Any]]) -> None:
        for tile in tiles:
            assert tile["height"] > 0, (
                f"Tile {tile['id']!r}: height must be positive, got {tile['height']}"
            )


def _check_row_horizontal_coverage(y: int, row_tiles: list[dict[str, Any]]) -> int:
    """Validate a row's tiles are contiguous from x=0 to MAP_WIDTH. Returns row height."""
    assert row_tiles[0]["x"] == 0, (
        f"Row at y={y}: first tile must start at x=0, got x={row_tiles[0]['x']}"
    )
    for i in range(len(row_tiles) - 1):
        current = row_tiles[i]
        nxt = row_tiles[i + 1]
        expected_next_x = current["x"] + current["width"]
        assert nxt["x"] == expected_next_x, (
            f"Row at y={y}: gap or overlap between "
            f"{current['id']!r} (x={current['x']}, w={current['width']}) "
            f"and {nxt['id']!r} (x={nxt['x']})"
        )
    last_tile = row_tiles[-1]
    row_right_edge = last_tile["x"] + last_tile["width"]
    assert row_right_edge == MAP_WIDTH, (
        f"Row at y={y}: ends at x={row_right_edge}, expected {MAP_WIDTH}"
    )
    return row_tiles[0]["height"]


def _check_vertical_coverage(
    sorted_y_values: list[int], row_heights: dict[int, int]
) -> None:
    """Validate rows are contiguous from y=0 to MAP_HEIGHT."""
    assert sorted_y_values[0] == 0, (
        f"First row must start at y=0, got y={sorted_y_values[0]}"
    )
    for i in range(len(sorted_y_values) - 1):
        y = sorted_y_values[i]
        next_y = sorted_y_values[i + 1]
        expected_next_y = y + row_heights[y]
        assert next_y == expected_next_y, (
            f"Gap or overlap between row y={y} (h={row_heights[y]}) "
            f"and next row y={next_y}"
        )
    last_y = sorted_y_values[-1]
    bottom_edge = last_y + row_heights[last_y]
    assert bottom_edge == MAP_HEIGHT, (
        f"Last row ends at y={bottom_edge}, expected {MAP_HEIGHT}"
    )


class TestMapTileCoverage:
    def test_total_tile_area_equals_map_area(self, tiles: list[dict[str, Any]]) -> None:
        total_area = sum(tile["width"] * tile["height"] for tile in tiles)
        map_area = MAP_WIDTH * MAP_HEIGHT
        assert total_area == map_area, (
            f"Total tile area {total_area} != map area {map_area}"
        )

    def test_full_map_coverage_without_gaps_or_overlap(
        self, tiles: list[dict[str, Any]]
    ) -> None:
        """Verify tiles cover 0..MAP_WIDTH by 0..MAP_HEIGHT with no gaps or overlaps."""
        rows: dict[int, list[dict[str, Any]]] = {}
        for tile in tiles:
            rows.setdefault(tile["y"], []).append(tile)

        sorted_y_values = sorted(rows.keys())
        row_heights: dict[int, int] = {}

        for y in sorted_y_values:
            row_tiles = sorted(rows[y], key=lambda t: t["x"])
            row_heights[y] = _check_row_horizontal_coverage(y, row_tiles)

        _check_vertical_coverage(sorted_y_values, row_heights)


class TestMapTileEdgeDimensions:
    def test_last_column_tiles_have_correct_width(
        self, tiles: list[dict[str, Any]], map_tiles_manifest: dict[str, Any]
    ) -> None:
        columns = map_tiles_manifest["columns"]
        last_column_x = (columns - 1) * STANDARD_TILE_SIZE
        last_col_tiles = [t for t in tiles if t["x"] == last_column_x]
        assert last_col_tiles, f"No tiles found for last column at x={last_column_x}"
        for tile in last_col_tiles:
            assert tile["width"] == LAST_COLUMN_WIDTH, (
                f"Last column tile {tile['id']!r}: width must be {LAST_COLUMN_WIDTH}, "
                f"got {tile['width']}"
            )

    def test_last_row_tiles_have_correct_height(
        self, tiles: list[dict[str, Any]], map_tiles_manifest: dict[str, Any]
    ) -> None:
        rows = map_tiles_manifest["rows"]
        last_row_y = (rows - 1) * STANDARD_TILE_SIZE
        last_row_tiles = [t for t in tiles if t["y"] == last_row_y]
        assert last_row_tiles, f"No tiles found for last row at y={last_row_y}"
        for tile in last_row_tiles:
            assert tile["height"] == LAST_ROW_HEIGHT, (
                f"Last row tile {tile['id']!r}: height must be {LAST_ROW_HEIGHT}, "
                f"got {tile['height']}"
            )

    def test_interior_tiles_have_standard_size(
        self, tiles: list[dict[str, Any]], map_tiles_manifest: dict[str, Any]
    ) -> None:
        columns = map_tiles_manifest["columns"]
        rows = map_tiles_manifest["rows"]
        last_column_x = (columns - 1) * STANDARD_TILE_SIZE
        last_row_y = (rows - 1) * STANDARD_TILE_SIZE
        interior_tiles = [
            t for t in tiles if t["x"] != last_column_x and t["y"] != last_row_y
        ]
        for tile in interior_tiles:
            assert tile["width"] == STANDARD_TILE_SIZE, (
                f"Interior tile {tile['id']!r}: width must be {STANDARD_TILE_SIZE}, "
                f"got {tile['width']}"
            )
            assert tile["height"] == STANDARD_TILE_SIZE, (
                f"Interior tile {tile['id']!r}: height must be {STANDARD_TILE_SIZE}, "
                f"got {tile['height']}"
            )

    def test_corner_tile_has_both_edge_dimensions(
        self, tiles: list[dict[str, Any]], map_tiles_manifest: dict[str, Any]
    ) -> None:
        columns = map_tiles_manifest["columns"]
        rows = map_tiles_manifest["rows"]
        corner_x = (columns - 1) * STANDARD_TILE_SIZE
        corner_y = (rows - 1) * STANDARD_TILE_SIZE
        corner_tiles = [t for t in tiles if t["x"] == corner_x and t["y"] == corner_y]
        assert len(corner_tiles) == 1, (
            f"Expected exactly one corner tile at ({corner_x}, {corner_y}), "
            f"found {len(corner_tiles)}"
        )
        corner = corner_tiles[0]
        assert corner["width"] == LAST_COLUMN_WIDTH, (
            f"Corner tile {corner['id']!r}: width must be {LAST_COLUMN_WIDTH}, "
            f"got {corner['width']}"
        )
        assert corner["height"] == LAST_ROW_HEIGHT, (
            f"Corner tile {corner['id']!r}: height must be {LAST_ROW_HEIGHT}, "
            f"got {corner['height']}"
        )


class TestMapTileImageDimensions:
    def test_png_dimension_reader_rejects_non_png(self, tmp_path: Path) -> None:
        fake_file = tmp_path / "fake.png"
        fake_file.write_bytes(b"not a png file at all here!!!!!")
        with pytest.raises(ValueError):
            _read_png_dimensions(fake_file)

    def test_png_dimension_reader_rejects_truncated_file(self, tmp_path: Path) -> None:
        truncated = tmp_path / "truncated.png"
        truncated.write_bytes(b"\x89PNG\r\n\x1a\n")
        with pytest.raises(ValueError):
            _read_png_dimensions(truncated)

    def test_each_tile_image_dimensions_match_config(
        self, tiles: list[dict[str, Any]]
    ) -> None:
        mismatches: list[str] = []
        for tile in tiles:
            file_path = ASSETS_IMAGES_DIR / tile["path"]
            if not file_path.exists():
                mismatches.append(f"{tile['id']}: file not found at {file_path}")
                continue
            try:
                actual_w, actual_h = _read_png_dimensions(file_path)
            except ValueError as exc:
                mismatches.append(
                    f"{tile['id']}: could not read PNG dimensions — {exc}"
                )
                continue
            if actual_w != tile["width"] or actual_h != tile["height"]:
                mismatches.append(
                    f"{tile['id']}: config says {tile['width']}x{tile['height']}, "
                    f"file is {actual_w}x{actual_h}"
                )
        assert not mismatches, (
            "Tile image dimensions do not match config:\n" + "\n".join(mismatches)
        )
