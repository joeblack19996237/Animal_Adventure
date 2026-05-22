import { describe, expect, it } from 'vitest';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import sharp from 'sharp';
import foregroundTilesConfig from '../../config/foreground_tiles.json';
import mapTilesConfig from '../../config/map_tiles.json';
import { resolveAssetImagePath } from '../../src/assets/loader';
import type { ForegroundTileManifest, MapTileManifest } from '../../src/assets/loader';

const mapManifest = mapTilesConfig as unknown as MapTileManifest;
const foregroundManifest = foregroundTilesConfig as unknown as ForegroundTileManifest;
const mapTilesById = new Map(mapManifest.tiles.map((tile) => [tile.id, tile]));

function localPathForAssetUrl(url: string): string {
  return join(process.cwd(), url.slice(1));
}

describe('foreground tile asset contract', () => {
  it('references only base map tiles that exist in the map manifest', () => {
    for (const tile of foregroundManifest.tiles) {
      expect(mapTilesById.has(tile.tile_id), `${tile.tile_id} should exist in map_tiles.json`).toBe(true);
    }
  });

  it('points every foreground tile entry at an existing PNG file', () => {
    for (const tile of foregroundManifest.tiles) {
      const url = resolveAssetImagePath(tile.path);
      expect(url.startsWith('/assets/images/ForegroundTiles/')).toBe(true);
      expect(existsSync(localPathForAssetUrl(url)), `${url} should exist`).toBe(true);
    }
  });

  it('keeps every foreground PNG the same size as its base map tile', async () => {
    for (const tile of foregroundManifest.tiles) {
      const baseTile = mapTilesById.get(tile.tile_id);
      expect(baseTile).toBeDefined();
      if (baseTile === undefined) continue;

      const metadata = await sharp(localPathForAssetUrl(resolveAssetImagePath(tile.path))).metadata();
      expect(metadata.width, `${tile.path} width`).toBe(baseTile.width);
      expect(metadata.height, `${tile.path} height`).toBe(baseTile.height);
    }
  });

  it('requires every foreground PNG to have an alpha channel', async () => {
    for (const tile of foregroundManifest.tiles) {
      const metadata = await sharp(localPathForAssetUrl(resolveAssetImagePath(tile.path))).metadata();
      expect(metadata.hasAlpha, `${tile.path} should have alpha`).toBe(true);
    }
  });

  it('keeps most foreground PNG pixels transparent', async () => {
    for (const tile of foregroundManifest.tiles) {
      const { data, info } = await sharp(localPathForAssetUrl(resolveAssetImagePath(tile.path)))
        .ensureAlpha()
        .raw()
        .toBuffer({ resolveWithObject: true });
      let transparentPixels = 0;
      for (let i = 3; i < data.length; i += 4) {
        if (data[i] === 0) transparentPixels++;
      }
      const transparentRatio = transparentPixels / (info.width * info.height);
      expect(transparentRatio, `${tile.path} transparent pixel ratio`).toBeGreaterThan(0.6);
    }
  });
});
