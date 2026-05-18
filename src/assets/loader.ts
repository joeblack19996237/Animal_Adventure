export interface MapTile {
  id: string;
  path: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MapTileManifest {
  tile_width: number;
  tile_height: number;
  map_width: number;
  map_height: number;
  columns: number;
  rows: number;
  tiles: MapTile[];
}

export interface TileLoadEntry {
  readonly key: string;
  readonly url: string;
}

export const ASSETS_BASE = '/assets';
export const ASSET_IMAGES_BASE = '/assets/images';
export const FORBIDDEN_SINGLE_TEXTURE = '/assets/images/Items/game_map_full.png';

export function resolveAssetImagePath(relativePath: string): string {
  return `${ASSET_IMAGES_BASE}/${relativePath}`;
}

export function isValidAssetPath(url: string): boolean {
  return url.startsWith(`${ASSETS_BASE}/`);
}

export function isForbiddenSingleTexture(url: string): boolean {
  return url === FORBIDDEN_SINGLE_TEXTURE;
}

export function buildMapTileLoadList(manifest: MapTileManifest): TileLoadEntry[] {
  return manifest.tiles.map((tile) => ({
    key: tile.id,
    url: resolveAssetImagePath(tile.path),
  }));
}
