export function createTextButton(text: string): HTMLButtonElement {
  const btn = document.createElement('button');
  btn.textContent = text;
  btn.style.cssText = 'padding:7px 14px;border:0;border-radius:999px;background:#ffd166;color:#5b3814;cursor:pointer;font-weight:700;';
  return btn;
}

export function createCloseButton(): HTMLButtonElement {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.ariaLabel = 'Close';
  btn.style.cssText =
    "position:absolute;right:24px;top:20px;width:34px;height:34px;border:0;background:transparent url('/assets/images/UI/ui_close_x_button.png') center/contain no-repeat;cursor:pointer;";
  return btn;
}

export function createGrid(): HTMLDivElement {
  const grid = document.createElement('div');
  grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(86px,1fr));gap:12px;align-items:start;';
  return grid;
}

export function createPopup(image: string, testId: string): HTMLDivElement {
  const popup = document.createElement('div');
  popup.dataset['testid'] = testId;
  popup.style.cssText =
    `display:none;position:fixed;top:22%;left:50%;transform:translateX(-50%);z-index:300;width:260px;height:112px;` +
    `background:url('${image}') center/contain no-repeat;color:#4c2d19;text-align:center;font-size:22px;font-weight:700;`;
  document.body.appendChild(popup);
  return popup;
}

export function createHudStat(image: string, stat: string): { el: HTMLDivElement; value: HTMLSpanElement } {
  const el = document.createElement('div');
  el.style.cssText = `position:relative;width:88px;height:58px;background:url('${image}') center/contain no-repeat;display:flex;align-items:center;justify-content:center;`;
  const value = document.createElement('span');
  value.id = stat === 'coins' ? 'hud-coins' : 'hud-level';
  value.dataset['stat'] = stat;
  value.textContent = '0';
  value.style.cssText = 'font-size:21px;font-weight:700;color:#fff;text-shadow:0 2px 3px rgba(0,0,0,.45);transform:translateY(2px);';
  el.appendChild(value);
  return { el, value };
}
