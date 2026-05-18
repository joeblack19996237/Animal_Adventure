import Phaser from 'phaser';
import { SCENE_KEYS } from './sceneKeys';

export class PreloadScene extends Phaser.Scene {
  constructor() {
    super({ key: SCENE_KEYS.PRELOAD });
  }

  preload(): void {}

  create(): void {
    this.scene.start(SCENE_KEYS.GAME);
  }
}
