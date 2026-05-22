import type { LoginControllerState } from './LoginController';

const CHARACTER_OPTIONS = [
  {
    id: 'cat_snowman',
    image: '/assets/images/cat_snowman_sprite_sheet/cat-front-stand.png',
  },
  {
    id: 'arctic_fox',
    image: '/assets/images/arctic_fox_sprite_sheet/arctic_fox_stand_front.png',
  },
  {
    id: 'penguin',
    image: '/assets/images/penguin_sprite_sheet/penguin_stand_front.png',
  },
] as const;

const LOCK_IMAGE = '/assets/images/UI/lock.png';

export class LoginView {
  readonly overlay: HTMLDivElement;
  private readonly namePanel: HTMLDivElement;
  private readonly nameInput: HTMLInputElement;
  private readonly submitBtn: HTMLButtonElement;
  private readonly statusEl: HTMLParagraphElement;
  private readonly charSection: HTMLDivElement;

  constructor(
    private readonly onSubmitName: () => void,
    private readonly onSelectCharacter: (charId: string) => void,
  ) {
    this.overlay = document.createElement('div');
    this.overlay.id = 'login-overlay';
    this.overlay.style.cssText =
      "position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;" +
      "background:url('/assets/images/UI/ui_main_menu_bg.png') center/cover no-repeat;color:#fff;";

    this.namePanel = document.createElement('div');
    this.namePanel.style.cssText =
      'display:flex;flex-direction:column;align-items:center;gap:14px;' +
      'background:rgba(31,45,74,0.28);padding:24px;border-radius:16px;';

    const title = document.createElement('h1');
    title.textContent = 'Animal Adventure';
    title.style.cssText = 'margin:0;color:#fff;font-size:44px;font-weight:700;text-shadow:0 3px 8px rgba(0,0,0,.35);';
    this.namePanel.appendChild(title);

    this.nameInput = document.createElement('input');
    this.nameInput.type = 'text';
    this.nameInput.placeholder = 'Enter your name';
    this.nameInput.maxLength = 32;
    this.nameInput.style.cssText =
      'width:260px;padding:12px 16px;border:0;border-radius:999px;font-size:20px;' +
      'background:rgba(255,255,255,.92);color:#21324d;text-align:center;outline:none;';
    this.nameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.onSubmitName();
    });
    this.namePanel.appendChild(this.nameInput);

    this.submitBtn = document.createElement('button');
    this.submitBtn.textContent = 'Play';
    this.submitBtn.style.cssText =
      'min-width:150px;padding:12px 28px;border:0;border-radius:999px;cursor:pointer;' +
      'background:#ffd166;color:#5b3814;font-size:22px;font-weight:700;box-shadow:0 6px 0 #d99b3d;';
    this.submitBtn.addEventListener('click', () => this.onSubmitName());
    this.namePanel.appendChild(this.submitBtn);

    this.statusEl = document.createElement('p');
    this.statusEl.style.cssText = 'min-height:24px;margin:0;color:#ffefef;font-size:18px;text-shadow:0 2px 4px rgba(0,0,0,.4);';
    this.namePanel.appendChild(this.statusEl);

    this.charSection = this.buildCharacterSection();
    this.charSection.style.display = 'none';

    this.overlay.appendChild(this.namePanel);
    this.overlay.appendChild(this.charSection);
  }

  private buildCharacterSection(): HTMLDivElement {
    const section = document.createElement('div');
    section.style.cssText = 'position:fixed;inset:0;display:flex;align-items:center;justify-content:center;';

    const logo = document.createElement('img');
    logo.src = '/assets/images/logo.png';
    logo.alt = 'Animal Adventure';
    logo.style.cssText = 'position:fixed;top:22px;right:28px;width:min(28vw,280px);height:auto;';
    section.appendChild(logo);

    const grid = document.createElement('div');
    grid.style.cssText =
      'display:grid;grid-template-columns:repeat(5,minmax(96px,150px));grid-template-rows:repeat(2,minmax(96px,150px));' +
      'gap:20px;align-items:center;justify-items:center;';

    for (let i = 0; i < 10; i++) {
      const character = CHARACTER_OPTIONS[i];
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.style.cssText =
        'width:clamp(96px,13vw,150px);height:clamp(96px,13vw,150px);border:0;background:transparent;' +
        'display:flex;align-items:center;justify-content:center;padding:0;';

      const img = document.createElement('img');
      img.style.cssText = 'max-width:100%;max-height:100%;object-fit:contain;filter:drop-shadow(0 8px 8px rgba(0,0,0,.25));';
      if (character !== undefined) {
        btn.ariaLabel = character.id;
        btn.style.cursor = 'pointer';
        btn.dataset['characterId'] = character.id;
        img.src = character.image;
        img.alt = character.id;
        btn.addEventListener('click', () => this.onSelectCharacter(character.id));
      } else {
        btn.ariaLabel = 'locked';
        btn.disabled = true;
        img.src = LOCK_IMAGE;
        img.alt = 'locked';
      }
      btn.appendChild(img);
      grid.appendChild(btn);
    }

    section.appendChild(grid);
    return section;
  }

  getNameValue(): string {
    return this.nameInput.value;
  }

  mount(): void {
    document.body.appendChild(this.overlay);
  }

  unmount(): void {
    const el = document.getElementById('login-overlay');
    if (el?.parentElement) el.parentElement.removeChild(el);
  }

  update(state: LoginControllerState): void {
    const isCharSelect = state.status === 'character_select';
    this.statusEl.textContent = isCharSelect ? '' : state.message;
    this.submitBtn.disabled = state.status === 'loading';
    this.namePanel.style.display = isCharSelect ? 'none' : 'flex';
    this.charSection.style.display = isCharSelect ? 'flex' : 'none';
  }
}
