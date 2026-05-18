import { describe, it, expect } from 'vitest';
import mapTilesConfig from '../../config/map_tiles.json';
import {
  resolveAssetImagePath,
  isValidAssetPath,
  isForbiddenSingleTexture,
  buildMapTileLoadList,
  FORBIDDEN_SINGLE_TEXTURE,
} from '../../src/assets/loader';
import type { MapTileManifest } from '../../src/assets/loader';

const manifest = mapTilesConfig as unknown as MapTileManifest;
const MAP_TILES_URL_PREFIX = '/assets/images/MapTiles/';

describe('asset_manifest_uses_map_tiles', () => {
  describe('resolveAssetImagePath', () => {
    it('returns URL under /assets/images/', () => {
      const url = resolveAssetImagePath('MapTiles/map_tile_0_0.png');
      expect(url).toBe('/assets/images/MapTiles/map_tile_0_0.png');
    });

    it('produced URL is a valid asset path', () => {
      const url = resolveAssetImagePath('MapTiles/map_tile_0_0.png');
      expect(isValidAssetPath(url)).toBe(true);
    });

    it('produced URL is not the forbidden single texture', () => {
      const url = resolveAssetImagePath('MapTiles/map_tile_0_0.png');
      expect(isForbiddenSingleTexture(url)).toBe(false);
    });
  });

  describe('isValidAssetPath', () => {
    it('accepts paths starting with /assets/', () => {
      expect(isValidAssetPath('/assets/images/foo.png')).toBe(true);
    });

    it('rejects paths not starting with /assets/', () => {
      expect(isValidAssetPath('/static/foo.png')).toBe(false);
    });

    it('rejects empty string', () => {
      expect(isValidAssetPath('')).toBe(false);
    });

    it('rejects relative paths without leading slash', () => {
      expect(isValidAssetPath('assets/foo.png')).toBe(false);
    });
  });

  describe('isForbiddenSingleTexture', () => {
    it('returns true for game_map_full.png path', () => {
      expect(isForbiddenSingleTexture(FORBIDDEN_SINGLE_TEXTURE)).toBe(true);
    });

    it('returns false for a map tile path', () => {
      expect(isForbiddenSingleTexture('/assets/images/MapTiles/map_tile_0_0.png')).toBe(false);
    });

    it('returns false for an unrelated asset path', () => {
      expect(isForbiddenSingleTexture('/assets/images/foo.png')).toBe(false);
    });
  });

  describe('buildMapTileLoadList from config/map_tiles.json', () => {
    it('returns one entry per tile in the manifest', () => {
      const entries = buildMapTileLoadList(manifest);
      expect(entries).toHaveLength(manifest.tiles.length);
    });

    it('returns 48 tiles for the 6x8 map grid', () => {
      const entries = buildMapTileLoadList(manifest);
      expect(entries).toHaveLength(48);
    });

    it('every tile URL starts with /assets/images/MapTiles/', () => {
      const entries = buildMapTileLoadList(manifest);
      for (const entry of entries) {
        expect(entry.url.startsWith(MAP_TILES_URL_PREFIX)).toBe(true);
      }
    });

    it('every tile URL is a valid asset path', () => {
      const entries = buildMapTileLoadList(manifest);
      for (const entry of entries) {
        expect(isValidAssetPath(entry.url)).toBe(true);
      }
    });

    it('no tile URL is the forbidden single texture', () => {
      const entries = buildMapTileLoadList(manifest);
      for (const entry of entries) {
        expect(isForbiddenSingleTexture(entry.url)).toBe(false);
      }
    });

    it('tile keys match manifest tile ids', () => {
      const entries = buildMapTileLoadList(manifest);
      entries.forEach((entry, i) => {
        expect(entry.key).toBe(manifest.tiles[i].id);
      });
    });

    it('first tile key is map_tile_0_0', () => {
      const entries = buildMapTileLoadList(manifest);
      expect(entries[0].key).toBe('map_tile_0_0');
    });

    it('first tile URL resolves to /assets/images/MapTiles/map_tile_0_0.png', () => {
      const entries = buildMapTileLoadList(manifest);
      expect(entries[0].url).toBe('/assets/images/MapTiles/map_tile_0_0.png');
    });
  });
});
