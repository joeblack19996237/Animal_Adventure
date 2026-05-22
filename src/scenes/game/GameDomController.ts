import { characterImage, itemImage } from './GameDomAssets';
import { createCloseButton, createGrid, createHudStat, createPopup, createTextButton } from './GameDomElements';

const NOTIFICATION_AUTO_HIDE_MS = 10_000;
const QUEST_DECISION_DELAY_MS = 10_000;
const WORLD_WIDTH = 5430;
const WORLD_HEIGHT = 7240;

export interface QuestOfferView {
  questId: string;
  npcId: string;
  title: string;
  rewards: unknown[];
}

export interface ShopItemView {
  item_id: string;
  price: number;
  unlock_level?: number;
}

export interface InventoryItemView {
  item_id: string;
  quantity: number;
}

export interface GameDomCallbacks {
  onAcceptQuest: () => void;
  onCancelQuest: () => void;
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
  private questFailedEl: HTMLDivElement | null = null;
  private levelUpEl: HTMLDivElement | null = null;
  private bootstrapErrorEl: HTMLDivElement | null = null;
  private shopPanelItems: HTMLDivElement | null = null;
  private shopMessageEl: HTMLDivElement | null = null;
  private inventoryPanelItems: HTMLDivElement | null = null;
  private mapMarkerEl: HTMLDivElement | null = null;
  private profileImgEl: HTMLImageElement | null = null;
  private profileNameEl: HTMLSpanElement | null = null;
  private coinsEl: HTMLSpanElement | null = null;
  private levelEl: HTMLSpanElement | null = null;
  private readonly panels = new Map<PanelName, HTMLDivElement>();

  constructor(private readonly callbacks: GameDomCallbacks) {}

  create(): void {
    this.createHudEl();
    this.createPlayerProfileEl();
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
      const retry = createTextButton('Retry');
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

  updatePlayerProfile(name: string, characterId: string): void {
    if (this.profileNameEl !== null) this.profileNameEl.textContent = name;
    if (this.profileImgEl !== null) this.profileImgEl.src = characterImage(characterId);
  }

  updatePlayerMapPosition(x: number, y: number): void {
    if (this.mapMarkerEl === null) return;
    this.mapMarkerEl.style.left = `${Math.max(0, Math.min(100, (x / WORLD_WIDTH) * 100))}%`;
    this.mapMarkerEl.style.top = `${Math.max(0, Math.min(100, (y / WORLD_HEIGHT) * 100))}%`;
  }

  updateShopPanel(items: readonly ShopItemView[]): void {
    if (this.shopPanelItems === null) return;
    this.shopPanelItems.innerHTML = '';
    for (const item of items) {
      const btn = this.createItemTile(item.item_id, String(item.price));
      btn.dataset['buyItem'] = item.item_id;
      btn.addEventListener('click', () => this.callbacks.onBuyItem(item.item_id));
      this.shopPanelItems.appendChild(btn);
    }
  }

  showShopMessage(message: string): void {
    if (this.shopMessageEl === null) return;
    this.shopMessageEl.textContent = message;
    this.shopMessageEl.style.display = 'block';
    setTimeout(() => {
      if (this.shopMessageEl !== null) this.shopMessageEl.style.display = 'none';
    }, 3500);
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
      const tile = this.createItemTile(item.item_id, String(item.quantity));
      tile.dataset['inventoryItem'] = item.item_id;
      if (consumableItemIds.has(item.item_id) && item.quantity > 0) {
        tile.dataset['useItem'] = item.item_id;
        tile.addEventListener('click', () => this.callbacks.onUseItem(item.item_id));
      }
      this.inventoryPanelItems.appendChild(tile);
    }
  }

  showQuestDialog(offer: QuestOfferView): void {
    this.clearQuestDecisionTimer();
    if (this.questDialogTitleEl !== null) this.questDialogTitleEl.textContent = offer.title;
    if (this.questDialogRewardsEl !== null) this.questDialogRewardsEl.textContent = this.formatRewards(offer.rewards);
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
    const clamped = Math.max(0, Math.min(1, ratio));
    if (this.questTimerFillEl !== null) {
      this.questTimerFillEl.style.transform = `scaleX(${clamped})`;
      this.questTimerFillEl.style.backgroundImage =
        clamped <= 0.1
          ? "url('/assets/images/UI/ui_task_timer_bar_red.png')"
          : "url('/assets/images/UI/ui_task_timer_bar_green.png')";
    }
    if (this.questTimerTextEl !== null) this.questTimerTextEl.textContent = text;
    if (this.questTimerEl !== null) this.questTimerEl.style.display = clamped <= 0 ? 'none' : 'flex';
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
    this.questCompleteEl.textContent = `Quest complete! You earned $${coinsAwarded}`;
    this.showTimedPopup(this.questCompleteEl, 5000);
  }

  showQuestFailed(): void {
    if (this.questFailedEl === null) return;
    this.questFailedEl.textContent = '';
    this.questFailedEl.ariaLabel = 'Quest failed';
    this.showTimedPopup(this.questFailedEl, NOTIFICATION_AUTO_HIDE_MS);
  }

  showQuestCooldown(_cooldownUntil: string): void {
    this.showQuestFailed();
  }

  hideQuestCooldown(): void {
    if (this.questFailedEl !== null) this.questFailedEl.style.display = 'none';
  }

  showLevelUp(level: number): void {
    if (this.levelUpEl === null) return;
    this.levelUpEl.textContent = `Level ${level}!`;
    this.levelUpEl.style.display = 'block';
  }

  destroy(): void {
    this.clearQuestDecisionTimer();
    for (const id of ['hud', 'game-menu', 'quest-dialog', 'quest-timer', 'bootstrap-error', 'player-profile']) {
      document.getElementById(id)?.remove();
    }
    for (const panel of this.panels.values()) panel.remove();
    this.turnInBtn?.remove();
    this.questCompleteEl?.remove();
    this.questFailedEl?.remove();
    this.levelUpEl?.remove();
  }

  private createHudEl(): void {
    const hud = document.createElement('div');
    hud.id = 'hud';
    hud.style.cssText = 'position:fixed;top:12px;right:12px;display:flex;align-items:center;gap:10px;z-index:80;font-family:Fredoka,system-ui,sans-serif;';
    const coins = createHudStat('/assets/images/UI/ui_currency_icon.png', 'coins');
    this.coinsEl = coins.value;
    hud.appendChild(coins.el);
    const level = createHudStat('/assets/images/UI/ui_level_badge.png', 'level');
    this.levelEl = level.value;
    hud.appendChild(level.el);
    document.body.appendChild(hud);
  }

  private createPlayerProfileEl(): void {
    const profile = document.createElement('div');
    profile.id = 'player-profile';
    profile.dataset['testid'] = 'player-profile';
    profile.style.cssText =
      'position:fixed;left:18px;bottom:18px;z-index:100;display:flex;align-items:center;gap:8px;color:#5b3814;font-weight:700;text-shadow:0 1px 0 rgba(255,255,255,.75);';
    const avatar = document.createElement('div');
    avatar.style.cssText = 'width:82px;height:82px;border-radius:50%;background:rgba(255,255,255,.42);border:2px solid rgba(255,255,255,.8);display:flex;align-items:center;justify-content:center;overflow:hidden;';
    this.profileImgEl = document.createElement('img');
    this.profileImgEl.alt = 'player character';
    this.profileImgEl.style.cssText = 'max-width:88%;max-height:88%;object-fit:contain;';
    avatar.appendChild(this.profileImgEl);
    this.profileNameEl = document.createElement('span');
    this.profileNameEl.style.cssText = 'font-size:18px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    profile.appendChild(avatar);
    profile.appendChild(this.profileNameEl);
    document.body.appendChild(profile);
  }

  private createMenuEl(): void {
    const menu = document.createElement('div');
    menu.id = 'game-menu';
    menu.style.cssText =
      "position:fixed;right:14px;bottom:14px;z-index:90;display:grid;grid-template-columns:repeat(4,88px);gap:10px;" +
      "padding:18px;background:url('/assets/images/V2_Resources/UI_frame.png') center/100% 100% no-repeat;";
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
        `width:88px;height:88px;border:0;border-radius:14px;cursor:pointer;background:rgba(255,255,255,.08) url('${image}') center/92% 92% no-repeat;` +
        'box-shadow:0 5px 0 rgba(55,42,22,.28);';
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
      "display:none;position:fixed;left:50%;bottom:6%;transform:translateX(-50%);width:min(540px,78vw);min-height:156px;z-index:220;" +
      "background:url('/assets/images/UI/ui_dialog_box.png') center/100% 100% no-repeat;padding:28px 46px 26px;color:#50321d;text-align:center;font-family:Fredoka,system-ui,sans-serif;";
    this.questDialogTitleEl = document.createElement('h3');
    this.questDialogTitleEl.style.cssText = 'margin:0 0 8px;font-size:22px;line-height:1.08;color:#4c2d19;';
    dialog.appendChild(this.questDialogTitleEl);
    this.questDialogRewardsEl = document.createElement('p');
    this.questDialogRewardsEl.style.cssText = 'margin:0;font-size:16px;color:#6d4a2d;';
    dialog.appendChild(this.questDialogRewardsEl);
    this.questDecisionEl = document.createElement('div');
    this.questDecisionEl.style.cssText = 'display:none;justify-content:center;gap:20px;margin-top:14px;';
    const cancelBtn = this.createImageButton('/assets/images/UI/ui_cancel_button.png', 'Cancel');
    cancelBtn.addEventListener('click', () => {
      this.hideQuestDialog();
      this.callbacks.onCancelQuest();
    });
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
    timer.style.cssText = 'display:none;position:fixed;top:18px;left:50%;transform:translateX(-50%);z-index:80;align-items:center;gap:10px;';
    const track = document.createElement('div');
    track.style.cssText = 'width:min(360px,48vw);height:28px;border-radius:999px;overflow:hidden;';
    this.questTimerFillEl = document.createElement('div');
    this.questTimerFillEl.style.cssText =
      "width:100%;height:100%;transform-origin:left center;background:url('/assets/images/UI/ui_task_timer_bar_green.png') left center/100% 100% no-repeat;filter:drop-shadow(0 3px 3px rgba(0,0,0,.25));";
    track.appendChild(this.questTimerFillEl);
    timer.appendChild(track);
    this.questTimerTextEl = document.createElement('span');
    this.questTimerTextEl.style.cssText = 'min-width:54px;color:#4c2d19;font-size:17px;font-weight:700;text-shadow:0 1px 0 rgba(255,255,255,.7);';
    timer.appendChild(this.questTimerTextEl);
    this.turnInBtn = createTextButton('Turn In');
    this.turnInBtn.dataset['action'] = 'turn-in';
    this.turnInBtn.style.cssText +=
      'display:none;position:fixed;top:18px;left:calc(50% + min(230px, 30vw));z-index:82;width:86px;height:34px;padding:0;';
    this.turnInBtn.addEventListener('click', () => this.callbacks.onTurnInQuest());
    document.body.appendChild(this.turnInBtn);
    document.body.appendChild(timer);
    this.questTimerEl = timer;
  }

  private createPanels(): void {
    this.createPanel('friends', '/assets/images/UI/ui_friend_list_panel.png', () => undefined);
    this.createPanel('shop', '/assets/images/UI/ui_shop_panel.png', (body) => {
      this.shopMessageEl = document.createElement('div');
      this.shopMessageEl.style.cssText = 'display:none;margin-bottom:10px;text-align:center;color:#8f271c;font-size:17px;font-weight:700;';
      body.appendChild(this.shopMessageEl);
      this.shopPanelItems = createGrid();
      body.appendChild(this.shopPanelItems);
    });
    this.createPanel('inventory', '/assets/images/UI/ui_inventory_panel.png', (body) => {
      this.inventoryPanelItems = createGrid();
      body.appendChild(this.inventoryPanelItems);
    });
    this.createPanel('map', '/assets/images/UI/ui_minimap_frame.png', (body) => {
      body.appendChild(this.createMiniMap());
    });
  }

  private createPanel(name: PanelName, image: string, attachBody: (body: HTMLDivElement) => void): void {
    const panel = document.createElement('div');
    panel.id = name === 'shop' ? 'shop-panel' : name === 'inventory' ? 'inventory-panel' : `${name}-panel`;
    panel.dataset['ui'] = name;
    panel.dataset['testid'] = `${name}-panel`;
    panel.style.cssText =
      `display:none;position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:210;width:min(560px,86vw);min-height:360px;` +
      `background:url('${image}') center/100% 100% no-repeat;padding:58px 54px 42px;color:#4c2d19;font-family:Fredoka,system-ui,sans-serif;`;
    const body = document.createElement('div');
    body.style.cssText = 'max-height:292px;overflow:auto;';
    attachBody(body);
    panel.appendChild(body);
    const closeBtn = createCloseButton();
    closeBtn.addEventListener('click', () => { panel.style.display = 'none'; });
    panel.appendChild(closeBtn);
    document.body.appendChild(panel);
    this.panels.set(name, panel);
  }

  private createNotificationEls(): void {
    this.questCompleteEl = createPopup('/assets/images/UI/ui_task_complete_stamp.png', 'quest-completed');
    this.questFailedEl = createPopup('/assets/images/UI/ui_task_fail_notice.png', 'quest-cooldown');
    this.questFailedEl.dataset['ui'] = 'quest-failed';
    this.levelUpEl = createPopup('/assets/images/UI/ui_level_up_banner.png', 'level-up');
    this.levelUpEl.id = 'level-up-notification';
  }

  private createItemTile(itemId: string, badge: string): HTMLButtonElement {
    const btn = document.createElement('button');
    const image = itemImage(itemId);
    btn.type = 'button';
    btn.ariaLabel = itemId;
    btn.style.cssText =
      'position:relative;aspect-ratio:1;border:0;border-radius:8px;background:rgba(255,255,255,.34);cursor:pointer;display:flex;align-items:center;justify-content:center;padding:8px;';
    const img = document.createElement('img');
    img.src = image;
    img.alt = itemId;
    img.style.cssText = 'max-width:84%;max-height:84%;object-fit:contain;filter:drop-shadow(0 4px 3px rgba(0,0,0,.18));';
    btn.appendChild(img);
    const count = document.createElement('span');
    count.textContent = badge;
    count.style.cssText = 'position:absolute;right:6px;bottom:4px;color:#5b3814;font-size:15px;font-weight:700;text-shadow:0 1px 0 #fff;';
    btn.appendChild(count);
    return btn;
  }

  private createMiniMap(): HTMLDivElement {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'position:relative;width:100%;aspect-ratio:5430/7240;max-height:274px;margin:auto;overflow:hidden;border-radius:8px;';
    const img = document.createElement('img');
    img.src = '/assets/images/Items/game_map_full.png';
    img.alt = 'world map';
    img.style.cssText = 'width:100%;height:100%;object-fit:cover;display:block;';
    wrap.appendChild(img);
    this.mapMarkerEl = document.createElement('div');
    this.mapMarkerEl.dataset['testid'] = 'map-player-marker';
    this.mapMarkerEl.style.cssText =
      'position:absolute;width:16px;height:16px;border-radius:50%;background:#e63946;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.45);transform:translate(-50%,-50%);';
    wrap.appendChild(this.mapMarkerEl);
    return wrap;
  }

  private createImageButton(image: string, label: string): HTMLButtonElement {
    const btn = document.createElement('button');
    btn.ariaLabel = label;
    btn.textContent = label;
    btn.style.cssText = `width:110px;height:48px;border:0;color:transparent;background:transparent url('${image}') center/contain no-repeat;cursor:pointer;`;
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

  private showTimedPopup(el: HTMLDivElement, duration: number): void {
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, duration);
  }

  private clearQuestDecisionTimer(): void {
    if (this.questDecisionTimer !== null) {
      clearTimeout(this.questDecisionTimer);
      this.questDecisionTimer = null;
    }
  }
}
