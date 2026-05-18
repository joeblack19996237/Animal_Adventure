import Phaser from 'phaser';
import { SCENE_KEYS } from './sceneKeys';
import { createHudState } from '../ui/hud';
import type { HudState } from '../ui/hud';

export class UIScene extends Phaser.Scene {
  private hudState: HudState;

  constructor() {
    super({ key: SCENE_KEYS.UI });
    this.hudState = createHudState();
  }

  create(): void {
    // HUD elements wired here
  }

  getHudState(): HudState {
    return this.hudState;
  }
}
