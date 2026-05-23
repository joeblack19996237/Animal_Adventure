import Phaser from 'phaser';
import mapJson from '../../../config/map.json';
import {
  buildForegroundTileLookup,
  foregroundTileKey,
  resolveAssetImagePath,
  type ForegroundTile,
  type ForegroundTileManifest,
  type MapTileManifest,
  type MapTile,
} from '../../assets/loader';
import { LOCKED_REGIONS } from './WorldCollision';

const INITIAL_RADIUS = 1100;
const STREAM_RADIUS = 1250;

interface SpawnConfig {
  map?: {
    spawn?: {
      x?: number;
      y?: number;
    };
  };
}

const MAP_CONFIG = mapJson as SpawnConfig;

function spawnPoint(): { x: number; y: number } {
  return {
    x: MAP_CONFIG.map?.spawn?.x ?? 2715,
    y: MAP_CONFIG.map?.spawn?.y ?? 3620,
  };
}

function isNear(tile: MapTile, x: number, y: number, radius: number): boolean {
  const closestX = Math.max(tile.x, Math.min(x, tile.x + tile.width));
  const closestY = Math.max(tile.y, Math.min(y, tile.y + tile.height));
  return Math.hypot(closestX - x, closestY - y) <= radius;
}

export function preloadInitialMapTiles(scene: Phaser.Scene, manifest: MapTileManifest): void {
  const spawn = spawnPoint();
  for (const tile of manifest.tiles) {
    if (isNear(tile, spawn.x, spawn.y, INITIAL_RADIUS)) {
      scene.load.image(tile.id, resolveAssetImagePath(tile.path));
    }
  }
}

export function preloadInitialForegroundTiles(
  scene: Phaser.Scene,
  mapManifest: MapTileManifest,
  foregroundManifest: ForegroundTileManifest,
): void {
  const spawn = spawnPoint();
  const foregroundTiles = buildForegroundTileLookup(foregroundManifest);
  for (const tile of mapManifest.tiles) {
    const foreground = foregroundTiles.get(tile.id);
    if (foreground === undefined) continue;
    const key = foregroundTileKey(tile.id);
    if (scene.textures.exists(key)) continue;
    if (isNear(tile, spawn.x, spawn.y, INITIAL_RADIUS)) {
      scene.load.image(key, resolveAssetImagePath(foreground.path));
    }
  }
}

export function foregroundDepthForTile(tile: MapTile): number {
  return tile.y + tile.height + 10;
}

export class MapTileRenderer {
  private readonly renderedTiles = new Set<string>();
  private readonly renderedForegroundTiles = new Set<string>();
  private readonly loadingTiles = new Set<string>();
  private readonly loadingForegroundTiles = new Set<string>();
  private readonly foregroundTiles: Map<string, ForegroundTile>;
  private readonly lockedOverlays: Phaser.GameObjects.GameObject[] = [];
  private readonly lockedOverlayDepth: number;
  private loaderActive = false;

  constructor(
    private readonly scene: Phaser.Scene,
    private readonly manifest: MapTileManifest,
    foregroundManifest: ForegroundTileManifest,
  ) {
    this.foregroundTiles = buildForegroundTileLookup(foregroundManifest);
    this.lockedOverlayDepth = this.manifest.map_height + 1000;
  }

  renderLoadedTiles(): void {
    for (const tile of this.manifest.tiles) {
      if (!this.renderedTiles.has(tile.id) && this.scene.textures.exists(tile.id)) {
        this.scene.add
          .image(tile.x + tile.width / 2, tile.y + tile.height / 2, tile.id)
          .setDepth(-1000);
        this.renderedTiles.add(tile.id);
      }
      this.renderLoadedForegroundTile(tile);
    }
  }

  renderLockedRegions(playerLevel: number): void {
    for (const overlay of this.lockedOverlays) overlay.destroy();
    this.lockedOverlays.length = 0;
    for (const region of LOCKED_REGIONS) {
      if (playerLevel >= region.unlock_level) continue;
      const overlay = this.scene.add
        .rectangle(region.x + region.width / 2, region.y + region.height / 2, region.width, region.height, 0xe8f5ff, 0.62)
        .setDepth(this.lockedOverlayDepth);
      if (this.scene.textures.exists('ui_locked_region_overlay')) {
        overlay.setFillStyle(0xe8f5ff, 0.45);
        const texture = this.scene.add
          .image(region.x + region.width / 2, region.y + region.height / 2, 'ui_locked_region_overlay')
          .setDisplaySize(region.width, region.height)
          .setAlpha(0.72)
          .setDepth(this.lockedOverlayDepth + 1);
        this.lockedOverlays.push(texture);
      }
      this.lockedOverlays.push(overlay);
    }
  }

  ensureTilesAround(x: number, y: number): void {
    const missing = this.manifest.tiles.filter(
      (tile) =>
        isNear(tile, x, y, STREAM_RADIUS) &&
        !this.scene.textures.exists(tile.id) &&
        !this.loadingTiles.has(tile.id),
    );
    const missingForeground = this.manifest.tiles.filter((tile) => {
      const foreground = this.foregroundTiles.get(tile.id);
      if (foreground === undefined) return false;
      const key = foregroundTileKey(tile.id);
      return isNear(tile, x, y, STREAM_RADIUS) &&
        !this.scene.textures.exists(key) &&
        !this.loadingForegroundTiles.has(key);
    });
    if ((missing.length === 0 && missingForeground.length === 0) || this.loaderActive) return;

    for (const tile of missing) {
      this.loadingTiles.add(tile.id);
      this.scene.load.image(tile.id, resolveAssetImagePath(tile.path));
    }

    for (const tile of missingForeground) {
      const foreground = this.foregroundTiles.get(tile.id);
      if (foreground === undefined) continue;
      const key = foregroundTileKey(tile.id);
      this.loadingForegroundTiles.add(key);
      this.scene.load.image(key, resolveAssetImagePath(foreground.path));
    }

    if (missing.length > 0 || missingForeground.length > 0) {
      this.loaderActive = true;
      this.scene.load.once(Phaser.Loader.Events.COMPLETE, () => {
        this.loaderActive = false;
        this.loadingTiles.clear();
        this.loadingForegroundTiles.clear();
        this.renderLoadedTiles();
      });
      this.scene.load.start();
    }
  }

  private renderLoadedForegroundTile(tile: MapTile): void {
    if (!this.renderedTiles.has(tile.id)) return;
    if (!this.foregroundTiles.has(tile.id)) return;
    const key = foregroundTileKey(tile.id);
    if (this.renderedForegroundTiles.has(key) || !this.scene.textures.exists(key)) return;
    this.scene.add
      .image(tile.x + tile.width / 2, tile.y + tile.height / 2, key)
      .setDepth(foregroundDepthForTile(tile));
    this.renderedForegroundTiles.add(key);
  }
}
