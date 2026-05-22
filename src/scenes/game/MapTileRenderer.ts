import Phaser from 'phaser';
import mapJson from '../../../config/map.json';
import { resolveAssetImagePath, type MapTileManifest, type MapTile } from '../../assets/loader';
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

export class MapTileRenderer {
  private readonly renderedTiles = new Set<string>();
  private readonly loadingTiles = new Set<string>();
  private readonly lockedOverlays: Phaser.GameObjects.GameObject[] = [];
  private loaderActive = false;

  constructor(
    private readonly scene: Phaser.Scene,
    private readonly manifest: MapTileManifest,
  ) {}

  renderLoadedTiles(): void {
    for (const tile of this.manifest.tiles) {
      if (this.renderedTiles.has(tile.id) || !this.scene.textures.exists(tile.id)) continue;
      this.scene.add
        .image(tile.x + tile.width / 2, tile.y + tile.height / 2, tile.id)
        .setDepth(-1000);
      this.renderedTiles.add(tile.id);
    }
  }

  renderLockedRegions(playerLevel: number): void {
    for (const overlay of this.lockedOverlays) overlay.destroy();
    this.lockedOverlays.length = 0;
    for (const region of LOCKED_REGIONS) {
      if (playerLevel >= region.unlock_level) continue;
      const overlay = this.scene.add
        .rectangle(region.x + region.width / 2, region.y + region.height / 2, region.width, region.height, 0xe8f5ff, 0.62)
        .setDepth(9000);
      if (this.scene.textures.exists('ui_locked_region_overlay')) {
        overlay.setFillStyle(0xe8f5ff, 0.45);
        const texture = this.scene.add
          .image(region.x + region.width / 2, region.y + region.height / 2, 'ui_locked_region_overlay')
          .setDisplaySize(region.width, region.height)
          .setAlpha(0.72)
          .setDepth(9001);
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
    if (missing.length === 0 || this.loaderActive) return;

    for (const tile of missing) {
      this.loadingTiles.add(tile.id);
      this.scene.load.image(tile.id, resolveAssetImagePath(tile.path));
    }

    this.loaderActive = true;
    this.scene.load.once(Phaser.Loader.Events.COMPLETE, () => {
      this.loaderActive = false;
      this.loadingTiles.clear();
      this.renderLoadedTiles();
    });
    this.scene.load.start();
  }
}
