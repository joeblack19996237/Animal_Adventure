import Phaser from 'phaser';
import { SessionState } from '../state/SessionState';
import { ApiClient } from '../net/ApiClient';
import { LoginController } from './LoginController';
import type { LoginControllerState } from './LoginController';
import { SCENE_KEYS } from './sceneKeys';

const MVP_CHARACTER_IDS = ['penguin', 'arctic_fox', 'cat_snowman'] as const;

export class LoginScene extends Phaser.Scene {
  private controller!: LoginController;
  private overlay!: HTMLDivElement;
  private nameInput!: HTMLInputElement;
  private submitBtn!: HTMLButtonElement;
  private statusEl!: HTMLParagraphElement;
  private charSection!: HTMLDivElement;

  constructor() {
    super({ key: SCENE_KEYS.LOGIN });
  }

  init(): void {
    const session = new SessionState();
    const api = new ApiClient(window.location.origin);
    this.controller = new LoginController(session, api, (state) => this.onStateChange(state));
  }

  create(): void {
    this.overlay = this.buildOverlay();
    document.body.appendChild(this.overlay);
  }

  private buildOverlay(): HTMLDivElement {
    const overlay = document.createElement('div');
    overlay.id = 'login-overlay';
    overlay.style.cssText =
      'position:fixed;top:0;left:0;width:100%;height:100%;' +
      'display:flex;flex-direction:column;align-items:center;justify-content:center;' +
      'background:rgba(10,10,30,0.9);z-index:1000;gap:12px;';

    const title = document.createElement('h1');
    title.textContent = 'Animal Adventure';
    title.style.color = '#fff';
    overlay.appendChild(title);

    const notice = document.createElement('p');
    notice.textContent = 'The same name always loads the same save (case-insensitive).';
    notice.style.color = '#aaa';
    overlay.appendChild(notice);

    this.nameInput = document.createElement('input');
    this.nameInput.type = 'text';
    this.nameInput.placeholder = 'Enter your name';
    this.nameInput.maxLength = 32;
    this.nameInput.style.cssText = 'padding:8px;font-size:1rem;width:240px;';
    this.nameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.onSubmitName();
    });
    overlay.appendChild(this.nameInput);

    this.submitBtn = document.createElement('button');
    this.submitBtn.textContent = 'Play';
    this.submitBtn.style.cssText = 'padding:10px 24px;font-size:1rem;cursor:pointer;';
    this.submitBtn.addEventListener('click', () => this.onSubmitName());
    overlay.appendChild(this.submitBtn);

    this.charSection = this.buildCharacterSection();
    this.charSection.style.display = 'none';
    overlay.appendChild(this.charSection);

    this.statusEl = document.createElement('p');
    this.statusEl.style.color = '#f88';
    overlay.appendChild(this.statusEl);

    return overlay;
  }

  private buildCharacterSection(): HTMLDivElement {
    const section = document.createElement('div');
    section.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:8px;';

    const label = document.createElement('p');
    label.textContent = 'Choose your character:';
    label.style.color = '#fff';
    section.appendChild(label);

    const btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex;gap:12px;';

    for (const charId of MVP_CHARACTER_IDS) {
      const btn = document.createElement('button');
      btn.textContent = charId.replace(/_/g, ' ');
      btn.dataset['characterId'] = charId;
      btn.style.cssText = 'padding:8px 16px;cursor:pointer;';
      btn.addEventListener('click', () => {
        void this.controller.selectCharacter(charId);
      });
      btnRow.appendChild(btn);
    }
    section.appendChild(btnRow);
    return section;
  }

  private onSubmitName(): void {
    void this.controller.submitName(this.nameInput.value);
  }

  private onStateChange(state: LoginControllerState): void {
    this.statusEl.textContent = state.message;
    this.submitBtn.disabled = state.status === 'loading';

    const isCharSelect = state.status === 'character_select';
    this.nameInput.style.display = isCharSelect ? 'none' : '';
    this.submitBtn.style.display = isCharSelect ? 'none' : '';
    this.charSection.style.display = isCharSelect ? 'flex' : 'none';

    if (state.status === 'done') {
      this.removeOverlay();
      this.scene.start(SCENE_KEYS.PRELOAD);
    }
  }

  private removeOverlay(): void {
    const el = document.getElementById('login-overlay');
    if (el?.parentElement) {
      el.parentElement.removeChild(el);
    }
  }

  shutdown(): void {
    this.removeOverlay();
  }
}
