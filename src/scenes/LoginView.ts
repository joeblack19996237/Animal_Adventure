import type { LoginControllerState } from './LoginController';

const MVP_CHARACTER_IDS = ['penguin', 'arctic_fox', 'cat_snowman'] as const;

export class LoginView {
  readonly overlay: HTMLDivElement;
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
      'position:fixed;top:0;left:0;width:100%;height:100%;' +
      'display:flex;flex-direction:column;align-items:center;justify-content:center;' +
      'background:rgba(10,10,30,0.9);z-index:1000;gap:12px;';

    const title = document.createElement('h1');
    title.textContent = 'Animal Adventure';
    title.style.color = '#fff';
    this.overlay.appendChild(title);

    const notice = document.createElement('p');
    notice.textContent = 'The same name always loads the same save (case-insensitive).';
    notice.style.color = '#aaa';
    this.overlay.appendChild(notice);

    this.nameInput = document.createElement('input');
    this.nameInput.type = 'text';
    this.nameInput.placeholder = 'Enter your name';
    this.nameInput.maxLength = 32;
    this.nameInput.style.cssText = 'padding:8px;font-size:1rem;width:240px;';
    this.nameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.onSubmitName();
    });
    this.overlay.appendChild(this.nameInput);

    this.submitBtn = document.createElement('button');
    this.submitBtn.textContent = 'Play';
    this.submitBtn.style.cssText = 'padding:10px 24px;font-size:1rem;cursor:pointer;';
    this.submitBtn.addEventListener('click', () => this.onSubmitName());
    this.overlay.appendChild(this.submitBtn);

    this.charSection = this.buildCharacterSection();
    this.charSection.style.display = 'none';
    this.overlay.appendChild(this.charSection);

    this.statusEl = document.createElement('p');
    this.statusEl.style.color = '#f88';
    this.overlay.appendChild(this.statusEl);
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
      btn.addEventListener('click', () => this.onSelectCharacter(charId));
      btnRow.appendChild(btn);
    }
    section.appendChild(btnRow);
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
    if (el?.parentElement) {
      el.parentElement.removeChild(el);
    }
  }

  update(state: LoginControllerState): void {
    this.statusEl.textContent = state.message;
    this.submitBtn.disabled = state.status === 'loading';

    const isCharSelect = state.status === 'character_select';
    this.nameInput.style.display = isCharSelect ? 'none' : '';
    this.submitBtn.style.display = isCharSelect ? 'none' : '';
    this.charSection.style.display = isCharSelect ? 'flex' : 'none';
  }
}
