import Phaser from 'phaser';
import { SessionState } from '../state/SessionState';
import { ApiClient } from '../net/ApiClient';
import { LoginController } from './LoginController';
import { LoginView } from './LoginView';
import { SCENE_KEYS } from './sceneKeys';

export class LoginScene extends Phaser.Scene {
  private controller!: LoginController;
  private view!: LoginView;

  constructor() {
    super({ key: SCENE_KEYS.LOGIN });
  }

  create(): void {
    this.view = new LoginView(
      () => void this.controller.submitName(this.view.getNameValue()),
      (charId) => void this.controller.selectCharacter(charId),
    );
    const session = new SessionState();
    const api = new ApiClient(window.location.origin);
    this.controller = new LoginController(session, api, (state) => {
      this.view.update(state);
      if (state.status === 'done') {
        this.view.unmount();
        this.scene.start(SCENE_KEYS.PRELOAD);
      }
    });
    this.view.mount();
  }

  shutdown(): void {
    this.view.unmount();
  }
}
