const NOTIFICATION_AUTO_HIDE_MS = 5000;

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

export class GameDomController {
  private questDialogEl: HTMLDivElement | null = null;
  private questDialogTitleEl: HTMLHeadingElement | null = null;
  private questDialogRewardsEl: HTMLParagraphElement | null = null;
  private questTimerEl: HTMLDivElement | null = null;
  private questTimerTextEl: HTMLSpanElement | null = null;
  private turnInBtn: HTMLButtonElement | null = null;
  private questCompleteEl: HTMLDivElement | null = null;
  private questCooldownEl: HTMLDivElement | null = null;
  private shopPanel: HTMLDivElement | null = null;
  private shopPanelItems: HTMLDivElement | null = null;
  private inventoryPanel: HTMLDivElement | null = null;
  private inventoryPanelItems: HTMLDivElement | null = null;
  private coinsEl: HTMLSpanElement | null = null;
  private levelEl: HTMLSpanElement | null = null;
  private levelUpEl: HTMLDivElement | null = null;
  private bootstrapErrorEl: HTMLDivElement | null = null;

  constructor(private readonly callbacks: GameDomCallbacks) {}

  create(): void {
    this.createHudEl();
    this.createQuestDialogEl();
    this.createQuestTimerEl();
    this.createShopPanelEl();
    this.createInventoryPanelEl();
    this.createNotificationEls();
  }

  showBootstrapError(message: string): void {
    if (this.bootstrapErrorEl === null) {
      const overlay = document.createElement('div');
      overlay.id = 'bootstrap-error';
      overlay.dataset['testid'] = 'bootstrap-error';
      overlay.style.cssText =
        'position:fixed;top:0;left:0;width:100%;height:100%;z-index:2000;' +
        'display:flex;flex-direction:column;align-items:center;justify-content:center;' +
        'gap:12px;background:rgba(8,12,24,0.94);color:#fff;text-align:center;padding:24px;';

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
      retry.style.cssText = 'padding:8px 18px;cursor:pointer;font-size:1rem;';
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
    if (this.bootstrapErrorEl !== null) {
      this.bootstrapErrorEl.style.display = 'none';
    }
  }

  updateCoinsDisplay(coins: number): void {
    if (this.coinsEl !== null) {
      this.coinsEl.textContent = `$${coins}`;
    }
  }

  updateLevelDisplay(level: number): void {
    if (this.levelEl !== null) {
      this.levelEl.textContent = `Level: ${level}`;
    }
  }

  updateShopPanel(items: readonly ShopItemView[]): void {
    if (this.shopPanelItems === null) return;
    this.shopPanelItems.innerHTML = '';
    for (const item of items) {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:10px;margin-bottom:8px;';

      const label = document.createElement('span');
      label.textContent = `${item.item_id} ($${item.price})`;
      row.appendChild(label);

      const buyBtn = document.createElement('button');
      buyBtn.textContent = 'Buy';
      buyBtn.dataset['buyItem'] = item.item_id;
      buyBtn.style.cssText = 'padding:4px 10px;cursor:pointer;';
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
      const row = document.createElement('div');
      row.dataset['itemId'] = item.item_id;
      row.dataset['inventoryItem'] = item.item_id;
      row.style.cssText = 'display:flex;align-items:center;gap:10px;margin-bottom:8px;';

      const label = document.createElement('span');
      label.textContent = `${item.item_id} x${item.quantity}`;
      row.appendChild(label);

      if (consumableItemIds.has(item.item_id) && item.quantity > 0) {
        const useBtn = document.createElement('button');
        useBtn.textContent = 'Use';
        useBtn.dataset['useItem'] = item.item_id;
        useBtn.style.cssText = 'padding:4px 10px;cursor:pointer;';
        useBtn.addEventListener('click', () => this.callbacks.onUseItem(item.item_id));
        row.appendChild(useBtn);
      }
      this.inventoryPanelItems.appendChild(row);
    }
  }

  showQuestDialog(offer: QuestOfferView): void {
    if (this.questDialogTitleEl !== null) this.questDialogTitleEl.textContent = offer.title;
    if (this.questDialogRewardsEl !== null) {
      const rewardStrs = offer.rewards.map((r) => {
        const rec = r as Record<string, unknown>;
        if (rec['type'] === 'coins') return `$${String(rec['amount'])} coins`;
        if (rec['type'] === 'equipment') return String(rec['item_id'] ?? 'item');
        return String(rec['type'] ?? '');
      });
      this.questDialogRewardsEl.textContent = `Rewards: ${rewardStrs.join(', ')}`;
    }
    if (this.questDialogEl !== null) this.questDialogEl.style.display = 'block';
  }

  hideQuestDialog(): void {
    if (this.questDialogEl !== null) this.questDialogEl.style.display = 'none';
  }

  showQuestTimer(text: string): void {
    if (this.questTimerTextEl !== null) {
      this.questTimerTextEl.textContent = text;
    }
    if (this.questTimerEl !== null) {
      this.questTimerEl.style.display = 'block';
    }
  }

  hideQuestTimer(): void {
    if (this.questTimerEl !== null) {
      this.questTimerEl.style.display = 'none';
    }
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
    this.questCompleteEl.textContent = `Quest complete! You earned $${coinsAwarded} coins.`;
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
    this.levelUpEl.textContent = `Level ${level}! Level up!`;
    this.levelUpEl.style.display = 'block';
  }

  destroy(): void {
    const idsToRemove = [
      'hud',
      'quest-dialog',
      'quest-timer',
      'shop-panel',
      'inventory-panel',
      'bootstrap-error',
    ];
    for (const id of idsToRemove) {
      const el = document.getElementById(id);
      if (el?.parentElement) el.parentElement.removeChild(el);
    }
    if (this.questCompleteEl?.parentElement) this.questCompleteEl.parentElement.removeChild(this.questCompleteEl);
    if (this.questCooldownEl?.parentElement) this.questCooldownEl.parentElement.removeChild(this.questCooldownEl);
    if (this.levelUpEl?.parentElement) this.levelUpEl.parentElement.removeChild(this.levelUpEl);
  }

  private toggleShopPanel(): void {
    if (this.shopPanel === null) return;
    const isVisible = this.shopPanel.style.display !== 'none';
    this.shopPanel.style.display = isVisible ? 'none' : 'block';
    if (this.inventoryPanel !== null) this.inventoryPanel.style.display = 'none';
  }

  private toggleInventoryPanel(): void {
    if (this.inventoryPanel === null) return;
    const isVisible = this.inventoryPanel.style.display !== 'none';
    this.inventoryPanel.style.display = isVisible ? 'none' : 'block';
    if (this.shopPanel !== null) this.shopPanel.style.display = 'none';
  }

  private createHudEl(): void {
    const hud = document.createElement('div');
    hud.id = 'hud';
    hud.style.cssText =
      'position:fixed;top:12px;right:12px;display:flex;align-items:center;gap:8px;z-index:50;';

    this.coinsEl = document.createElement('span');
    this.coinsEl.id = 'hud-coins';
    this.coinsEl.dataset['stat'] = 'coins';
    this.coinsEl.style.cssText = 'color:#ffe066;font-weight:bold;font-size:1.1rem;';
    this.coinsEl.textContent = '$0';
    hud.appendChild(this.coinsEl);

    this.levelEl = document.createElement('span');
    this.levelEl.id = 'hud-level';
    this.levelEl.dataset['stat'] = 'level';
    this.levelEl.style.cssText = 'color:#aad4ff;font-weight:bold;font-size:1.1rem;';
    this.levelEl.textContent = 'Level: 0';
    hud.appendChild(this.levelEl);

    const shopBtn = document.createElement('button');
    shopBtn.id = 'hud-shop';
    shopBtn.dataset['hud'] = 'shop';
    shopBtn.textContent = 'Shop';
    shopBtn.style.cssText = 'padding:6px 14px;cursor:pointer;z-index:50;';
    shopBtn.addEventListener('click', () => this.toggleShopPanel());
    hud.appendChild(shopBtn);

    const invBtn = document.createElement('button');
    invBtn.id = 'hud-inventory';
    invBtn.dataset['hud'] = 'inventory';
    invBtn.textContent = 'Bag';
    invBtn.style.cssText = 'padding:6px 14px;cursor:pointer;z-index:50;';
    invBtn.addEventListener('click', () => this.toggleInventoryPanel());
    hud.appendChild(invBtn);

    document.body.appendChild(hud);
  }

  private createQuestDialogEl(): void {
    const dialog = document.createElement('div');
    dialog.id = 'quest-dialog';
    dialog.dataset['ui'] = 'quest';
    dialog.dataset['testid'] = 'quest-dialog';
    dialog.style.cssText =
      'display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);' +
      'background:#1a1a2e;color:#fff;border:2px solid #4a90d9;border-radius:8px;' +
      'padding:20px 28px;min-width:280px;z-index:200;text-align:center;';

    this.questDialogTitleEl = document.createElement('h3');
    this.questDialogTitleEl.style.cssText = 'margin:0 0 10px;color:#ffe066;';
    dialog.appendChild(this.questDialogTitleEl);

    this.questDialogRewardsEl = document.createElement('p');
    this.questDialogRewardsEl.style.cssText = 'margin:0 0 14px;font-size:0.9rem;color:#aad4ff;';
    dialog.appendChild(this.questDialogRewardsEl);

    const acceptBtn = document.createElement('button');
    acceptBtn.textContent = 'Accept';
    acceptBtn.style.cssText = 'padding:8px 20px;cursor:pointer;font-size:1rem;';
    acceptBtn.addEventListener('click', () => this.callbacks.onAcceptQuest());
    dialog.appendChild(acceptBtn);

    document.body.appendChild(dialog);
    this.questDialogEl = dialog;
  }

  private createQuestTimerEl(): void {
    const timer = document.createElement('div');
    timer.id = 'quest-timer';
    timer.dataset['testid'] = 'quest-timer';
    timer.dataset['ui'] = 'quest-active';
    timer.style.cssText =
      'display:none;position:fixed;top:52px;left:50%;transform:translateX(-50%);' +
      'background:rgba(10,20,40,0.85);color:#ffe066;border:1px solid #4a90d9;' +
      'border-radius:6px;padding:8px 16px;z-index:50;text-align:center;';

    const label = document.createElement('span');
    label.textContent = 'Quest: ';
    label.style.color = '#aad4ff';
    timer.appendChild(label);

    this.questTimerTextEl = document.createElement('span');
    this.questTimerTextEl.textContent = '0:00';
    timer.appendChild(this.questTimerTextEl);

    this.turnInBtn = document.createElement('button');
    this.turnInBtn.textContent = 'Turn In';
    this.turnInBtn.dataset['action'] = 'turn-in';
    this.turnInBtn.style.cssText = 'display:none;margin-left:12px;padding:4px 12px;cursor:pointer;';
    this.turnInBtn.addEventListener('click', () => this.callbacks.onTurnInQuest());
    timer.appendChild(this.turnInBtn);

    document.body.appendChild(timer);
    this.questTimerEl = timer;
  }

  private createShopPanelEl(): void {
    const panel = document.createElement('div');
    panel.id = 'shop-panel';
    panel.dataset['ui'] = 'shop';
    panel.dataset['testid'] = 'shop-panel';
    panel.style.cssText =
      'display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);' +
      'background:#1a1a2e;color:#fff;border:2px solid #4a90d9;border-radius:8px;' +
      'padding:20px 28px;min-width:240px;z-index:200;';

    const title = document.createElement('h3');
    title.textContent = 'Shop';
    title.style.cssText = 'margin:0 0 12px;color:#ffe066;';
    panel.appendChild(title);

    this.shopPanelItems = document.createElement('div');
    panel.appendChild(this.shopPanelItems);

    const closeBtn = document.createElement('button');
    closeBtn.textContent = 'Close';
    closeBtn.style.cssText = 'margin-top:12px;padding:4px 12px;cursor:pointer;';
    closeBtn.addEventListener('click', () => {
      if (this.shopPanel) this.shopPanel.style.display = 'none';
    });
    panel.appendChild(closeBtn);

    document.body.appendChild(panel);
    this.shopPanel = panel;
  }

  private createInventoryPanelEl(): void {
    const panel = document.createElement('div');
    panel.id = 'inventory-panel';
    panel.dataset['ui'] = 'inventory';
    panel.dataset['testid'] = 'inventory-panel';
    panel.style.cssText =
      'display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);' +
      'background:#1a1a2e;color:#fff;border:2px solid #4a90d9;border-radius:8px;' +
      'padding:20px 28px;min-width:240px;z-index:200;';

    const title = document.createElement('h3');
    title.textContent = 'Inventory';
    title.style.cssText = 'margin:0 0 12px;color:#ffe066;';
    panel.appendChild(title);

    this.inventoryPanelItems = document.createElement('div');
    panel.appendChild(this.inventoryPanelItems);

    const closeBtn = document.createElement('button');
    closeBtn.textContent = 'Close';
    closeBtn.style.cssText = 'margin-top:12px;padding:4px 12px;cursor:pointer;';
    closeBtn.addEventListener('click', () => {
      if (this.inventoryPanel) this.inventoryPanel.style.display = 'none';
    });
    panel.appendChild(closeBtn);

    document.body.appendChild(panel);
    this.inventoryPanel = panel;
  }

  private createNotificationEls(): void {
    const complete = document.createElement('div');
    complete.dataset['testid'] = 'quest-completed';
    complete.style.cssText =
      'display:none;position:fixed;top:30%;left:50%;transform:translateX(-50%);' +
      'background:#163d1f;color:#7fff7f;border:2px solid #3aaf3a;border-radius:8px;' +
      'padding:14px 24px;z-index:300;text-align:center;font-size:1rem;';
    document.body.appendChild(complete);
    this.questCompleteEl = complete;

    const cooldown = document.createElement('div');
    cooldown.dataset['ui'] = 'quest-cooldown';
    cooldown.dataset['testid'] = 'quest-cooldown';
    cooldown.style.cssText =
      'display:none;position:fixed;top:52px;left:50%;transform:translateX(-50%);' +
      'background:rgba(80,20,20,0.9);color:#ff9999;border:1px solid #c04040;' +
      'border-radius:6px;padding:8px 16px;z-index:50;';
    cooldown.textContent = 'Quest failed';
    document.body.appendChild(cooldown);
    this.questCooldownEl = cooldown;

    const levelUp = document.createElement('div');
    levelUp.id = 'level-up-notification';
    levelUp.dataset['testid'] = 'level-up';
    levelUp.style.cssText =
      'display:none;position:fixed;top:20%;left:50%;transform:translateX(-50%);' +
      'background:#1a1a2e;color:#ffe066;border:2px solid #f0c040;border-radius:8px;' +
      'padding:18px 32px;z-index:300;text-align:center;font-size:1.4rem;font-weight:bold;';
    document.body.appendChild(levelUp);
    this.levelUpEl = levelUp;
  }
}
