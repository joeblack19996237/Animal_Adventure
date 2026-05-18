import Phaser from 'phaser';
import { SCENE_KEYS } from './sceneKeys';
import { buildMapTileLoadList } from '../assets/loader';
import type { MapTileManifest } from '../assets/loader';
import mapTilesJson from '../../config/map_tiles.json';

const MAP_TILE_MANIFEST: MapTileManifest = mapTilesJson;

export class GameScene extends Phaser.Scene {
  constructor() {
    super({ key: SCENE_KEYS.GAME });
  }

  preload(): void {
    for (const entry of buildMapTileLoadList(MAP_TILE_MANIFEST)) {
      this.load.image(entry.key, entry.url);
    }
  }

  create(): void {
    for (const tile of MAP_TILE_MANIFEST.tiles) {
      this.add.image(tile.x + tile.width / 2, tile.y + tile.height / 2, tile.id);
    }
    this.cameras.main.setBounds(
      0,
      0,
      MAP_TILE_MANIFEST.map_width,
      MAP_TILE_MANIFEST.map_height,
    );
  }
}
