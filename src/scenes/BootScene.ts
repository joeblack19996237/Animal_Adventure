import Phaser from 'phaser';
import { SCENE_KEYS } from './sceneKeys';

export class BootScene extends Phaser.Scene {
  constructor() {
    super({ key: SCENE_KEYS.BOOT });
  }

  create(): void {
    this.scene.start(SCENE_KEYS.LOGIN);
  }
}
