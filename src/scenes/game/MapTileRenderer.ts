import Phaser from 'phaser';
import mapJson from '../../../config/map.json';
import { resolveAssetImagePath, type MapTileManifest, type MapTile } from '../../assets/loader';

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
