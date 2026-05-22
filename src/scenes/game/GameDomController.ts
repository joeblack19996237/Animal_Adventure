const NOTIFICATION_AUTO_HIDE_MS = 5000;
const QUEST_DECISION_DELAY_MS = 10_000;

export interface QuestOfferView {
  questId: string;
  npcId: string;
  title: string;
  rewards: unknown[];
}

export interface ShopItemView {
  item_id: string;
  price: number;
}

export interface InventoryItemView {
  item_id: string;
  quantity: number;
}

export interface GameDomCallbacks {
  onAcceptQuest: () => void;
  onBuyItem: (itemId: string) => void;
  onUseItem: (itemId: string) => void;
  onTurnInQuest: () => void;
  onBootstrapRetry: () => void;
}

type PanelName = 'friends' | 'shop' | 'inventory' | 'map';

export class GameDomController {
  private questDialogEl: HTMLDivElement | null = null;
  private questDialogTitleEl: HTMLHeadingElement | null = null;
  private questDialogRewardsEl: HTMLParagraphElement | null = null;
  private questDecisionEl: HTMLDivElement | null = null;
  private questDecisionTimer: ReturnType<typeof setTimeout> | null = null;
  private questTimerEl: HTMLDivElement | null = null;
  private questTimerFillEl: HTMLDivElement | null = null;
  private questTimerTextEl: HTMLSpanElement | null = null;
  private turnInBtn: HTMLButtonElement | null = null;
  private questCompleteEl: HTMLDivElement | null = null;
  private questCooldownEl: HTMLDivElement | null = null;
  private levelUpEl: HTMLDivElement | null = null;
  private bootstrapErrorEl: HTMLDivElement | null = null;
  private shopPanelItems: HTMLDivElement | null = null;
  private inventoryPanelItems: HTMLDivElement | null = null;
  private coinsEl: HTMLSpanElement | null = null;
  private levelEl: HTMLSpanElement | null = null;
  private readonly panels = new Map<PanelName, HTMLDivElement>();

  constructor(private readonly callbacks: GameDomCallbacks) {}

  create(): void {
    this.createHudEl();
    this.createMenuEl();
    this.createQuestDialogEl();
    this.createQuestTimerEl();
    this.createPanels();
    this.createNotificationEls();
  }

  showBootstrapError(message: string): void {
    if (this.bootstrapErrorEl === null) {
      const overlay = document.createElement('div');
      overlay.id = 'bootstrap-error';
      overlay.dataset['testid'] = 'bootstrap-error';
      overlay.style.cssText =
        'position:fixed;inset:0;z-index:2000;display:flex;flex-direction:column;align-items:center;justify-content:center;' +
        'gap:12px;background:rgba(8,12,24,0.94);color:#fff;text-align:center;padding:24px;font-family:Fredoka,system-ui,sans-serif;';

      const title = document.createElement('h2');
      title.textContent = 'Configuration failed to load';
      title.style.cssText = 'margin:0;color:#ffe066;font-size:1.5rem;';
      overlay.appendChild(title);

      const detail = document.createElement('p');
      detail.textContent = message;
      detail.style.cssText = 'margin:0;max-width:520px;color:#d8e6ff;';
      overlay.appendChild(detail);

      const retry = document.createElement('button');
      retry.textContent = 'Retry';
      retry.style.cssText = 'padding:8px 18px;cursor:pointer;font-size:1rem;border-radius:999px;border:0;';
      retry.addEventListener('click', () => {
        overlay.style.display = 'none';
        this.callbacks.onBootstrapRetry();
      });
      overlay.appendChild(retry);

      document.body.appendChild(overlay);
      this.bootstrapErrorEl = overlay;
    }
    this.bootstrapErrorEl.style.display = 'flex';
  }

  hideBootstrapError(): void {
    if (this.bootstrapErrorEl !== null) this.bootstrapErrorEl.style.display = 'none';
  }

  updateCoinsDisplay(coins: number): void {
    if (this.coinsEl !== null) this.coinsEl.textContent = String(coins);
  }

  updateLevelDisplay(level: number): void {
    if (this.levelEl !== null) this.levelEl.textContent = String(level);
  }

  updateShopPanel(items: readonly ShopItemView[]): void {
    if (this.shopPanelItems === null) return;
    this.shopPanelItems.innerHTML = '';
    for (const item of items) {
      const row = this.createPanelRow(`${item.item_id}  $${item.price}`);
      const buyBtn = this.createTextButton('Buy');
      buyBtn.dataset['buyItem'] = item.item_id;
      buyBtn.addEventListener('click', () => this.callbacks.onBuyItem(item.item_id));
      row.appendChild(buyBtn);
      this.shopPanelItems.appendChild(row);
    }
  }

  updateInventoryPanel(
    inventory: readonly InventoryItemView[],
    equipment: readonly InventoryItemView[],
    consumableItemIds: ReadonlySet<string>,
  ): void {
    if (this.inventoryPanelItems === null) return;
    this.inventoryPanelItems.innerHTML = '';
    const allItems = [...inventory, ...equipment];
    const seen = new Set<string>();
    for (const item of allItems) {
      if (seen.has(item.item_id)) continue;
      seen.add(item.item_id);
      const row = this.createPanelRow(`${item.item_id} x${item.quantity}`);
      row.dataset['itemId'] = item.item_id;
      row.dataset['inventoryItem'] = item.item_id;
      if (consumableItemIds.has(item.item_id) && item.quantity > 0) {
        const useBtn = this.createTextButton('Use');
        useBtn.dataset['useItem'] = item.item_id;
        useBtn.addEventListener('click', () => this.callbacks.onUseItem(item.item_id));
        row.appendChild(useBtn);
      }
      this.inventoryPanelItems.appendChild(row);
    }
  }

  showQuestDialog(offer: QuestOfferView): void {
    this.clearQuestDecisionTimer();
    if (this.questDialogTitleEl !== null) this.questDialogTitleEl.textContent = offer.title;
    if (this.questDialogRewardsEl !== null) {
      this.questDialogRewardsEl.textContent = `Rewards: ${this.formatRewards(offer.rewards)}`;
    }
    if (this.questDecisionEl !== null) this.questDecisionEl.style.display = 'none';
    if (this.questDialogEl !== null) this.questDialogEl.style.display = 'block';
    this.questDecisionTimer = setTimeout(() => {
      if (this.questDecisionEl !== null) this.questDecisionEl.style.display = 'flex';
    }, QUEST_DECISION_DELAY_MS);
  }

  hideQuestDialog(): void {
    this.clearQuestDecisionTimer();
    if (this.questDialogEl !== null) this.questDialogEl.style.display = 'none';
  }

  showQuestTimer(text: string, ratio = 1): void {
    if (this.questTimerFillEl !== null) {
      const clamped = Math.max(0, Math.min(1, ratio));
      this.questTimerFillEl.style.width = `${Math.round(clamped * 100)}%`;
      this.questTimerFillEl.style.backgroundImage =
        clamped <= 0.1
          ? "url('/assets/images/UI/ui_task_timer_bar_red.png')"
          : "url('/assets/images/UI/ui_task_timer_bar_green.png')";
      this.questTimerFillEl.dataset['remaining'] = text;
    }
    if (this.questTimerTextEl !== null) this.questTimerTextEl.textContent = text;
    if (this.questTimerEl !== null) this.questTimerEl.style.display = 'flex';
  }

  hideQuestTimer(): void {
    if (this.questTimerEl !== null) this.questTimerEl.style.display = 'none';
  }

  setTurnInQuest(questId: string | null): void {
    if (this.turnInBtn === null) return;
    if (questId === null) {
      this.turnInBtn.style.display = 'none';
      delete this.turnInBtn.dataset['questId'];
      return;
    }
    this.turnInBtn.dataset['questId'] = questId;
    this.turnInBtn.style.display = 'inline-block';
  }

  showQuestComplete(coinsAwarded: number): void {
    if (this.questCompleteEl === null) return;
    this.questCompleteEl.textContent = `Quest complete! +$${coinsAwarded}`;
    this.questCompleteEl.style.display = 'block';
    setTimeout(() => {
      if (this.questCompleteEl !== null) this.questCompleteEl.style.display = 'none';
    }, NOTIFICATION_AUTO_HIDE_MS);
  }

  showQuestCooldown(cooldownUntil: string): void {
    if (this.questCooldownEl === null) return;
    this.questCooldownEl.textContent = `Quest failed - available after ${cooldownUntil}`;
    this.questCooldownEl.style.display = 'block';
  }

  hideQuestCooldown(): void {
    if (this.questCooldownEl !== null) this.questCooldownEl.style.display = 'none';
  }

  showLevelUp(level: number): void {
    if (this.levelUpEl === null) return;
    this.levelUpEl.textContent = `Level ${level}!`;
    this.levelUpEl.style.display = 'block';
  }

  destroy(): void {
    this.clearQuestDecisionTimer();
    for (const id of ['hud', 'game-menu', 'quest-dialog', 'quest-timer', 'bootstrap-error']) {
      document.getElementById(id)?.remove();
    }
    for (const panel of this.panels.values()) panel.remove();
    this.questCompleteEl?.remove();
    this.questCooldownEl?.remove();
    this.levelUpEl?.remove();
  }

  private createHudEl(): void {
    const hud = document.createElement('div');
    hud.id = 'hud';
    hud.style.cssText =
      'position:fixed;top:12px;right:12px;display:flex;align-items:center;gap:10px;z-index:80;font-family:Fredoka,system-ui,sans-serif;';

    const coins = this.createHudStat('/assets/images/UI/ui_currency_icon.png', 'coins');
    this.coinsEl = coins.value;
    hud.appendChild(coins.el);

    const level = this.createHudStat('/assets/images/UI/ui_level_badge.png', 'level');
    this.levelEl = level.value;
    hud.appendChild(level.el);

    document.body.appendChild(hud);
  }

  private createMenuEl(): void {
    const menu = document.createElement('div');
    menu.id = 'game-menu';
    menu.style.cssText =
      "position:fixed;right:16px;bottom:16px;z-index:90;display:grid;grid-template-columns:repeat(4,64px);gap:8px;" +
      "padding:14px;background:url('/assets/images/V2_Resources/UI_frame.png') center/100% 100% no-repeat;";

    const buttons: [PanelName, string, string][] = [
      ['friends', '/assets/images/UI/ui_menu_friends_icon.png', 'Friends'],
      ['shop', '/assets/images/UI/ui_menu_shop_icon.png', 'Shop'],
      ['inventory', '/assets/images/UI/ui_menu_inventory_icon.png', 'Bag'],
      ['map', '/assets/images/UI/ui_menu_map_icon.png', 'Map'],
    ];
    for (const [panel, image, label] of buttons) {
      const btn = document.createElement('button');
      btn.id = panel === 'shop' ? 'hud-shop' : panel === 'inventory' ? 'hud-inventory' : `hud-${panel}`;
      btn.ariaLabel = label;
      btn.dataset['hud'] = panel;
      btn.style.cssText =
        `width:64px;height:64px;border:0;border-radius:16px;cursor:pointer;background:rgba(255,255,255,.18) url('${image}') center/76% 76% no-repeat;` +
        'box-shadow:0 4px 0 rgba(55,42,22,.35);';
      btn.addEventListener('click', () => this.togglePanel(panel));
      menu.appendChild(btn);
    }
    document.body.appendChild(menu);
  }

  private createQuestDialogEl(): void {
    const dialog = document.createElement('div');
    dialog.id = 'quest-dialog';
    dialog.dataset['ui'] = 'quest';
    dialog.dataset['testid'] = 'quest-dialog';
    dialog.style.cssText =
      "display:none;position:fixed;left:50%;bottom:7%;transform:translateX(-50%);width:min(680px,86vw);min-height:220px;z-index:220;" +
      "background:url('/assets/images/UI/ui_dialog_box.png') center/100% 100% no-repeat;padding:42px 58px 34px;color:#50321d;text-align:center;font-family:Fredoka,system-ui,sans-serif;";

    this.questDialogTitleEl = document.createElement('h3');
    this.questDialogTitleEl.style.cssText = 'margin:0 0 12px;font-size:28px;color:#4c2d19;';
    dialog.appendChild(this.questDialogTitleEl);

    this.questDialogRewardsEl = document.createElement('p');
    this.questDialogRewardsEl.style.cssText = 'margin:0;font-size:19px;color:#6d4a2d;';
    dialog.appendChild(this.questDialogRewardsEl);

    this.questDecisionEl = document.createElement('div');
    this.questDecisionEl.style.cssText = 'display:none;justify-content:center;gap:24px;margin-top:24px;';

    const cancelBtn = this.createImageButton('/assets/images/UI/ui_cancel_button.png', 'Cancel');
    cancelBtn.addEventListener('click', () => this.hideQuestDialog());
    this.questDecisionEl.appendChild(cancelBtn);

    const acceptBtn = this.createImageButton('/assets/images/UI/ui_confirm_button.png', 'Accept');
    acceptBtn.addEventListener('click', () => this.callbacks.onAcceptQuest());
    this.questDecisionEl.appendChild(acceptBtn);

    dialog.appendChild(this.questDecisionEl);
    document.body.appendChild(dialog);
    this.questDialogEl = dialog;
  }

  private createQuestTimerEl(): void {
    const timer = document.createElement('div');
    timer.id = 'quest-timer';
    timer.dataset['testid'] = 'quest-timer';
    timer.dataset['ui'] = 'quest-active';
    timer.style.cssText =
      'display:none;position:fixed;top:20px;left:50%;transform:translateX(-50%);z-index:80;align-items:center;gap:12px;';

    const track = document.createElement('div');
    track.style.cssText = 'width:min(420px,52vw);height:30px;border-radius:999px;overflow:hidden;background:rgba(59,45,28,.35);';
    this.questTimerFillEl = document.createElement('div');
    this.questTimerFillEl.style.cssText =
      "width:100%;height:100%;background:url('/assets/images/UI/ui_task_timer_bar_green.png') left center/100% 100% no-repeat;";
    track.appendChild(this.questTimerFillEl);
    timer.appendChild(track);

    this.questTimerTextEl = document.createElement('span');
    this.questTimerTextEl.style.cssText =
      'min-width:56px;color:#4c2d19;font-size:18px;font-weight:700;text-shadow:0 1px 0 rgba(255,255,255,.7);';
    timer.appendChild(this.questTimerTextEl);

    this.turnInBtn = this.createTextButton('Turn In');
    this.turnInBtn.dataset['action'] = 'turn-in';
    this.turnInBtn.style.display = 'none';
    this.turnInBtn.addEventListener('click', () => this.callbacks.onTurnInQuest());
    timer.appendChild(this.turnInBtn);

    document.body.appendChild(timer);
    this.questTimerEl = timer;
  }

  private createPanels(): void {
    this.createPanel('friends', '/assets/images/UI/ui_friend_list_panel.png', (body) => {
      body.textContent = 'Friends list is empty';
    });
    this.createPanel('shop', '/assets/images/UI/ui_shop_panel.png', (body) => {
      this.shopPanelItems = body;
    });
    this.createPanel('inventory', '/assets/images/UI/ui_inventory_panel.png', (body) => {
      this.inventoryPanelItems = body;
    });
    this.createPanel('map', '/assets/images/UI/ui_minimap_frame.png', (body) => {
      body.textContent = 'Spawn';
    });
  }

  private createPanel(name: PanelName, image: string, attachBody: (body: HTMLDivElement) => void): void {
    const panel = document.createElement('div');
    panel.id = name === 'shop' ? 'shop-panel' : name === 'inventory' ? 'inventory-panel' : `${name}-panel`;
    panel.dataset['ui'] = name;
    panel.dataset['testid'] = `${name}-panel`;
    panel.style.cssText =
      `display:none;position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:210;width:min(520px,86vw);min-height:360px;` +
      `background:url('${image}') center/100% 100% no-repeat;padding:64px 62px 44px;color:#4c2d19;font-family:Fredoka,system-ui,sans-serif;`;

    const body = document.createElement('div');
    body.style.cssText = 'max-height:260px;overflow:auto;font-size:18px;';
    attachBody(body);
    panel.appendChild(body);

    const closeBtn = this.createTextButton('Close');
    closeBtn.style.cssText += 'position:absolute;right:36px;bottom:24px;';
    closeBtn.addEventListener('click', () => { panel.style.display = 'none'; });
    panel.appendChild(closeBtn);

    document.body.appendChild(panel);
    this.panels.set(name, panel);
  }

  private createNotificationEls(): void {
    this.questCompleteEl = this.createPopup('/assets/images/UI/ui_task_complete_stamp.png', 'quest-completed');
    this.questCooldownEl = this.createPopup('/assets/images/UI/ui_task_fail_notice.png', 'quest-cooldown');
    this.levelUpEl = this.createPopup('/assets/images/UI/ui_level_up_banner.png', 'level-up');
    this.levelUpEl.id = 'level-up-notification';
  }

  private createPopup(image: string, testId: string): HTMLDivElement {
    const popup = document.createElement('div');
    popup.dataset['testid'] = testId;
    popup.style.cssText =
      `display:none;position:fixed;top:22%;left:50%;transform:translateX(-50%);z-index:300;min-width:260px;min-height:92px;` +
      `background:url('${image}') center/100% 100% no-repeat;color:#4c2d19;padding:32px 42px;text-align:center;font-size:22px;font-weight:700;`;
    document.body.appendChild(popup);
    return popup;
  }

  private createHudStat(image: string, stat: string): { el: HTMLDivElement; value: HTMLSpanElement } {
    const el = document.createElement('div');
    el.style.cssText =
      `position:relative;width:88px;height:58px;background:url('${image}') center/contain no-repeat;display:flex;align-items:center;justify-content:center;`;
    const value = document.createElement('span');
    value.id = stat === 'coins' ? 'hud-coins' : 'hud-level';
    value.dataset['stat'] = stat;
    value.textContent = stat === 'coins' ? '0' : '0';
    value.style.cssText = 'font-size:21px;font-weight:700;color:#fff;text-shadow:0 2px 3px rgba(0,0,0,.45);transform:translateY(2px);';
    el.appendChild(value);
    return { el, value };
  }

  private createPanelRow(text: string): HTMLDivElement {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px;';
    const label = document.createElement('span');
    label.textContent = text;
    row.appendChild(label);
    return row;
  }

  private createTextButton(text: string): HTMLButtonElement {
    const btn = document.createElement('button');
    btn.textContent = text;
    btn.style.cssText =
      'padding:7px 14px;border:0;border-radius:999px;background:#ffd166;color:#5b3814;cursor:pointer;font-weight:700;';
    return btn;
  }

  private createImageButton(image: string, label: string): HTMLButtonElement {
    const btn = document.createElement('button');
    btn.ariaLabel = label;
    btn.textContent = label;
    btn.style.cssText =
      `width:124px;height:54px;border:0;color:transparent;background:transparent url('${image}') center/contain no-repeat;cursor:pointer;`;
    return btn;
  }

  private togglePanel(panelName: PanelName): void {
    for (const [name, panel] of this.panels) {
      panel.style.display = name === panelName && panel.style.display === 'none' ? 'block' : 'none';
    }
  }

  private formatRewards(rewards: unknown[]): string {
    return rewards
      .map((r) => {
        const rec = r as Record<string, unknown>;
        if (rec['type'] === 'coins') return `$${String(rec['amount'])}`;
        if (rec['type'] === 'equipment') return String(rec['item_id'] ?? 'item');
        return String(rec['type'] ?? '');
      })
      .filter((s) => s.length > 0)
      .join(', ');
  }

  private clearQuestDecisionTimer(): void {
    if (this.questDecisionTimer !== null) {
      clearTimeout(this.questDecisionTimer);
      this.questDecisionTimer = null;
    }
  }
}
