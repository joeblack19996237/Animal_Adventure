import Phaser from 'phaser';
import { SCENE_KEYS } from './sceneKeys';
import { buildMapTileLoadList } from '../assets/loader';
import type { MapTileManifest } from '../assets/loader';
import mapTilesJson from '../../config/map_tiles.json';
import { WSClient } from '../net/WSClient';
import {
  isStateSyncMsg,
  isQuestOfferMsg,
  isQuestStartedMsg,
  isInventoryUpdatedMsg,
  isLevelUpMsg,
  type StateSyncMsg,
  type QuestOfferMsg,
  type QuestStartedMsg,
  type InventoryUpdatedMsg,
  type LevelUpMsg,
} from '../net/protocol';
import { BootstrapService } from '../services/BootstrapService';

const MAP_TILE_MANIFEST: MapTileManifest = mapTilesJson;
const PLAYER_ID_KEY = 'animal_adventure_player_id';
const PLAYER_SPEED = 300;
const JOYSTICK_RADIUS = 48;
const NOTIFICATION_AUTO_HIDE_MS = 5000;

interface QuestRecord {
  quest_instance_id: number;
  npc_id: string;
  quest_id: string;
  status: string;
  expires_at: string | null;
  cooldown_until: string | null;
  progress: { collected: string[] };
  rewards_granted_json: string[];
}

interface WorldItemRecord {
  id: string;
  item_id: string;
  quest_instance_id: number;
  x: number;
  y: number;
  status: string;
}

interface InventoryRecord {
  item_id: string;
  quantity: number;
  slot_type: string;
}

interface ShopBootstrapItem {
  item_id: string;
  price: number;
  unlock_level: number;
}

interface QuestOffer {
  questId: string;
  npcId: string;
  title: string;
  rewards: unknown[];
}

function isShopBootstrapItem(v: unknown): v is ShopBootstrapItem {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return false;
  const r = v as Record<string, unknown>;
  return typeof r['item_id'] === 'string' && typeof r['price'] === 'number';
}

function isItemRecord(v: unknown): v is { id: string; type: string } {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return false;
  const r = v as Record<string, unknown>;
  return typeof r['id'] === 'string' && typeof r['type'] === 'string';
}

function toQuestRecord(v: unknown): QuestRecord | null {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return null;
  const r = v as Record<string, unknown>;
  if (typeof r['quest_id'] !== 'string' || typeof r['status'] !== 'string') return null;
  const progress = (r['progress'] as Record<string, unknown> | undefined) ?? {};
  return {
    quest_instance_id: typeof r['quest_instance_id'] === 'number' ? r['quest_instance_id'] : 0,
    npc_id: typeof r['npc_id'] === 'string' ? r['npc_id'] : '',
    quest_id: r['quest_id'],
    status: r['status'],
    expires_at: typeof r['expires_at'] === 'string' ? r['expires_at'] : null,
    cooldown_until: typeof r['cooldown_until'] === 'string' ? r['cooldown_until'] : null,
    progress: {
      collected: Array.isArray(progress['collected'])
        ? (progress['collected'] as unknown[]).filter((x): x is string => typeof x === 'string')
        : [],
    },
    rewards_granted_json: Array.isArray(r['rewards_granted_json'])
      ? (r['rewards_granted_json'] as unknown[]).filter((x): x is string => typeof x === 'string')
      : [],
  };
}

function toWorldItemRecord(v: unknown): WorldItemRecord | null {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return null;
  const r = v as Record<string, unknown>;
  if (typeof r['id'] !== 'string') return null;
  return {
    id: r['id'],
    item_id: typeof r['item_id'] === 'string' ? r['item_id'] : '',
    quest_instance_id: typeof r['quest_instance_id'] === 'number' ? r['quest_instance_id'] : 0,
    x: typeof r['x'] === 'number' ? r['x'] : 0,
    y: typeof r['y'] === 'number' ? r['y'] : 0,
    status: typeof r['status'] === 'string' ? r['status'] : '',
  };
}

function toInventoryRecord(v: unknown): InventoryRecord | null {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return null;
  const r = v as Record<string, unknown>;
  if (typeof r['item_id'] !== 'string') return null;
  return {
    item_id: r['item_id'],
    quantity: typeof r['quantity'] === 'number' ? r['quantity'] : 1,
    slot_type: typeof r['slot_type'] === 'string' ? r['slot_type'] : 'inventory',
  };
}

function formatCountdown(remainingMs: number): string {
  const totalSecs = Math.max(0, Math.floor(remainingMs / 1000));
  const mins = Math.floor(totalSecs / 60);
  const secs = totalSecs % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export class GameScene extends Phaser.Scene {
  // WebSocket + player movement (existing)
  private wsClient: WSClient | null = null;
  private playerId = '';
  private playerX = 0;
  private playerY = 0;
  private playerDirection = 'down';
  private clientTick = 0;
  private sceneReady = false;
  private stateSyncReceived = false;
  private joystickEl: HTMLDivElement | null = null;
  private joystickActive = false;
  private joystickStartX = 0;
  private joystickStartY = 0;
  private joystickDx = 0;
  private joystickDy = 0;

  // Player / game state
  private quests: QuestRecord[] = [];
  private worldItems: WorldItemRecord[] = [];
  private inventory: InventoryRecord[] = [];
  private equipment: InventoryRecord[] = [];
  private coins = 0;
  private level = 0;
  private serverTimeOffsetMs = 0;

  // Quest state machine
  private pendingQuestOffer: QuestOffer | null = null;
  private activeQuestId: string | null = null;
  private completedQuestIds: Set<string> = new Set();

  // Quest timer
  private questDeadlineMs: number | null = null;
  private questTimerInterval: ReturnType<typeof setInterval> | null = null;

  // Bootstrap data
  private shopBootstrapItems: ShopBootstrapItem[] = [];
  private consumableItemIds: Set<string> = new Set();

  // DOM elements
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

  // Event listener references for cleanup
  private boundNpcInteract: ((e: Event) => void) | null = null;
  private boundQuestTurnIn: ((e: Event) => void) | null = null;
  private boundItemPickup: ((e: Event) => void) | null = null;

  constructor() {
    super({ key: SCENE_KEYS.GAME });
  }

  preload(): void {
    for (const entry of buildMapTileLoadList(MAP_TILE_MANIFEST)) {
      this.load.image(entry.key, entry.url);
    }
  }

  create(): void {
    for (const tile of MAP_TILE_MANIFEST.tiles) {
      this.add.image(tile.x + tile.width / 2, tile.y + tile.height / 2, tile.id);
    }
    this.cameras.main.setBounds(0, 0, MAP_TILE_MANIFEST.map_width, MAP_TILE_MANIFEST.map_height);
    this.createJoystick();
    this.createDomElements();
    this.registerGameEventListeners();
    this.sceneReady = true;
    this.connectWebSocket();
    this.updateGameStore();
    void this.loadBootstrapAsync();
  }

  private async loadBootstrapAsync(): Promise<void> {
    const svc = new BootstrapService(window.location.origin);
    const result = await svc.fetchConfig();
    if (result.kind !== 'ok') {
      this.showBootstrapError(result.message);
      return;
    }
    this.hideBootstrapError();
    const shop = result.config.shop as Record<string, unknown> | null;
    if (shop !== null && typeof shop === 'object' && Array.isArray(shop['items'])) {
      this.shopBootstrapItems = (shop['items'] as unknown[]).filter(isShopBootstrapItem);
    }
    if (Array.isArray(result.config.items)) {
      for (const item of result.config.items as unknown[]) {
        if (isItemRecord(item) && item.type === 'consumable') {
          this.consumableItemIds.add(item.id);
        }
      }
    }
    this.updateShopPanel();
  }

  private showBootstrapError(message: string): void {
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
        void this.loadBootstrapAsync();
      });
      overlay.appendChild(retry);

      document.body.appendChild(overlay);
      this.bootstrapErrorEl = overlay;
    }
    this.bootstrapErrorEl.style.display = 'flex';
  }

  private hideBootstrapError(): void {
    if (this.bootstrapErrorEl !== null) {
      this.bootstrapErrorEl.style.display = 'none';
    }
  }

  private connectWebSocket(): void {
    const storedId = localStorage.getItem(PLAYER_ID_KEY);
    if (storedId === null) return;
    this.playerId = storedId;
    this.wsClient = new WSClient({
      playerId: this.playerId,
      onMessage: (msg) => this.onWsMessage(msg),
    });
    this.wsClient.connect();
  }

  private onWsMessage(msg: Record<string, unknown>): void {
    if (isStateSyncMsg(msg)) { this.handleStateSync(msg); return; }
    if (isQuestOfferMsg(msg)) { this.handleQuestOffer(msg); return; }
    if (isQuestStartedMsg(msg)) { this.handleQuestStarted(msg); return; }
    if (isInventoryUpdatedMsg(msg)) { this.handleInventoryUpdated(msg); return; }
    if (isLevelUpMsg(msg)) { this.handleLevelUp(msg); return; }
    const type = msg['type'];
    if (type === 'item_picked_up') { this.handleItemPickedUp(msg); return; }
    if (type === 'quest_completed') { this.handleQuestCompleted(msg); return; }
    if (type === 'quest_failed') { this.handleQuestFailed(msg); return; }
    if (type === 'shop_purchase_ok' || type === 'shop_result') { this.handleShopResult(msg); return; }
    if (type === 'item_used') { this.handleItemUsed(msg); return; }
  }

  private handleStateSync(msg: StateSyncMsg): void {
    this.serverTimeOffsetMs = Date.now() - new Date(msg.server_time).getTime();
    const p = msg.player;
    if (typeof p['x'] === 'number') this.playerX = p['x'];
    if (typeof p['y'] === 'number') this.playerY = p['y'];
    if (typeof p['direction'] === 'string') this.playerDirection = p['direction'];
    if (typeof p['coins'] === 'number') this.coins = p['coins'];
    if (typeof p['level'] === 'number') this.level = p['level'];
    this.stateSyncReceived = true;

    this.quests = (msg.quests as unknown[]).map(toQuestRecord).filter((q): q is QuestRecord => q !== null);
    this.worldItems = (msg.world_items as unknown[]).map(toWorldItemRecord).filter((w): w is WorldItemRecord => w !== null);
    this.inventory = (msg.inventory as unknown[]).map(toInventoryRecord).filter((i): i is InventoryRecord => i !== null);
    this.equipment = (msg.equipment as unknown[]).map(toInventoryRecord).filter((i): i is InventoryRecord => i !== null);

    for (const q of this.quests) {
      if (q.status === 'completed') this.completedQuestIds.add(q.quest_id);
    }

    const activeQuest = this.quests.find((q) => q.status === 'active');
    if (activeQuest !== undefined && activeQuest.expires_at !== null) {
      this.activeQuestId = activeQuest.quest_id;
      this.startQuestTimer(activeQuest.expires_at, msg.server_time);
    } else {
      if (activeQuest === undefined) this.activeQuestId = null;
      this.stopQuestTimer();
    }

    const failedQuest = this.quests.find((q) => q.status === 'failed' && q.cooldown_until !== null);
    if (failedQuest !== undefined && failedQuest.cooldown_until !== null) {
      this.showQuestCooldown(failedQuest.cooldown_until);
    } else {
      this.hideQuestCooldown();
    }

    this.updateCoinsDisplay();
    this.updateLevelDisplay();
    this.updateInventoryPanel();
    this.updateGameStore();
  }

  private handleQuestOffer(msg: QuestOfferMsg): void {
    this.pendingQuestOffer = {
      questId: msg.quest_id,
      npcId: msg.npc_id,
      title: msg.title,
      rewards: msg.rewards,
    };
    this.showQuestDialog(this.pendingQuestOffer);
  }

  private handleQuestStarted(msg: QuestStartedMsg): void {
    this.activeQuestId = msg.quest_id;
    this.hideQuestDialog();
    this.startQuestTimer(msg.expires_at, null);
    const newItems = (msg.world_items as unknown[]).map(toWorldItemRecord).filter((w): w is WorldItemRecord => w !== null);
    this.worldItems = [...this.worldItems, ...newItems];
    if (this.turnInBtn !== null) this.turnInBtn.style.display = 'none';
  }

  private handleItemPickedUp(msg: Record<string, unknown>): void {
    if (Array.isArray(msg['inventory'])) {
      const picked = (msg['inventory'] as unknown[]).map(toInventoryRecord).filter((i): i is InventoryRecord => i !== null);
      for (const item of picked) {
        const existing = this.inventory.find((i) => i.item_id === item.item_id);
        if (existing !== undefined) {
          existing.quantity += item.quantity;
        } else {
          this.inventory.push(item);
        }
      }
    }
    if (this.turnInBtn !== null && this.activeQuestId !== null) {
      this.turnInBtn.dataset['questId'] = this.activeQuestId;
      this.turnInBtn.style.display = 'inline-block';
    }
    this.updateInventoryPanel();
  }

  private handleQuestCompleted(msg: Record<string, unknown>): void {
    const questId = typeof msg['quest_id'] === 'string' ? msg['quest_id'] : '';
    const coinsAwarded = typeof msg['coins_awarded'] === 'number' ? msg['coins_awarded'] : 0;
    if (typeof msg['coins_balance'] === 'number') this.coins = msg['coins_balance'];
    this.completedQuestIds.add(questId);
    const q = this.quests.find((item) => item.quest_id === questId);
    if (q !== undefined) {
      q.status = 'completed';
      if (Array.isArray(msg['rewards_granted_json'])) {
        q.rewards_granted_json = (msg['rewards_granted_json'] as unknown[]).filter((x): x is string => typeof x === 'string');
      }
    }
    if (this.activeQuestId === questId) {
      this.activeQuestId = null;
    }
    this.stopQuestTimer();
    if (this.turnInBtn !== null) this.turnInBtn.style.display = 'none';
    this.showQuestComplete(coinsAwarded);
    this.updateCoinsDisplay();
    this.updateGameStore();
  }

  private handleQuestFailed(msg: Record<string, unknown>): void {
    const questId = typeof msg['quest_id'] === 'string' ? msg['quest_id'] : '';
    const cooldownUntil = typeof msg['cooldown_until'] === 'string' ? msg['cooldown_until'] : null;
    const q = this.quests.find((item) => item.quest_id === questId);
    if (q !== undefined) {
      q.status = 'failed';
      q.cooldown_until = cooldownUntil;
    }
    if (this.activeQuestId === questId) this.activeQuestId = null;
    this.stopQuestTimer();
    if (cooldownUntil !== null) this.showQuestCooldown(cooldownUntil);
    this.updateGameStore();
  }

  private handleInventoryUpdated(msg: InventoryUpdatedMsg): void {
    const inv = (msg.inventory as unknown[]).map(toInventoryRecord).filter((i): i is InventoryRecord => i !== null);
    const eq = (msg.equipment as unknown[]).map(toInventoryRecord).filter((i): i is InventoryRecord => i !== null);
    this.inventory = inv;
    this.equipment = eq;
    this.updateInventoryPanel();
    this.updateGameStore();
  }

  private handleShopResult(msg: Record<string, unknown>): void {
    if (typeof msg['coins_balance'] === 'number') {
      this.coins = msg['coins_balance'];
      this.updateCoinsDisplay();
      this.updateGameStore();
    }
  }

  private handleItemUsed(msg: Record<string, unknown>): void {
    if (typeof msg['coins_balance'] === 'number') {
      this.coins = msg['coins_balance'];
      this.updateCoinsDisplay();
      this.updateGameStore();
    }
  }

  private handleLevelUp(msg: LevelUpMsg): void {
    this.level = msg.level;
    this.updateLevelDisplay();
    this.showLevelUp(msg.level);
    this.updateGameStore();
  }

  private sendQuestTurnIn(questId: string): void {
    if (this.completedQuestIds.has(questId)) return;
    const q = this.quests.find((item) => item.quest_id === questId);
    if (q !== undefined && q.status !== 'active') return;
    if (this.wsClient === null) return;
    this.wsClient.send({ type: 'quest_turn_in', player_id: this.playerId, quest_id: questId });
  }

  private sendItemPickup(questId: string, itemId: string): void {
    const q = this.quests.find((item) => item.quest_id === questId);
    if (q !== undefined && q.status !== 'active') return;
    if (this.wsClient === null) return;
    this.wsClient.send({ type: 'item_pickup_request', player_id: this.playerId, quest_id: questId, item_id: itemId });
  }

  // --- Quest timer ---

  private startQuestTimer(expiresAtISO: string, serverTimeISO: string | null): void {
    // Clear any running interval first, without clearing questDeadlineMs
    if (this.questTimerInterval !== null) {
      clearInterval(this.questTimerInterval);
      this.questTimerInterval = null;
    }
    const expiresMs = new Date(expiresAtISO).getTime();
    if (serverTimeISO !== null) {
      const remainingMs = expiresMs - new Date(serverTimeISO).getTime();
      this.questDeadlineMs = Date.now() + remainingMs;
    } else {
      this.questDeadlineMs = expiresMs + this.serverTimeOffsetMs;
    }
    this.tickQuestTimer();
    this.questTimerInterval = setInterval(() => this.tickQuestTimer(), 1000);
  }

  private stopQuestTimer(): void {
    if (this.questTimerInterval !== null) {
      clearInterval(this.questTimerInterval);
      this.questTimerInterval = null;
    }
    this.questDeadlineMs = null;
    if (this.questTimerEl !== null) {
      this.questTimerEl.style.display = 'none';
    }
  }

  private tickQuestTimer(): void {
    if (this.questDeadlineMs === null || this.questTimerEl === null) return;
    const remainingMs = this.questDeadlineMs - Date.now();
    if (this.questTimerTextEl !== null) {
      this.questTimerTextEl.textContent = formatCountdown(remainingMs);
    }
    this.questTimerEl.style.display = 'block';
  }

  // --- DOM creation ---

  private createDomElements(): void {
    this.createHudEl();
    this.createQuestDialogEl();
    this.createQuestTimerEl();
    this.createShopPanelEl();
    this.createInventoryPanelEl();
    this.createNotificationEls();
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
    acceptBtn.addEventListener('click', () => this.onAcceptQuest());
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
    this.turnInBtn.addEventListener('click', () => {
      const questId = this.turnInBtn?.dataset['questId'] ?? this.activeQuestId ?? '';
      if (questId) this.sendQuestTurnIn(questId);
    });
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
    closeBtn.addEventListener('click', () => { if (this.shopPanel) this.shopPanel.style.display = 'none'; });
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
    closeBtn.addEventListener('click', () => { if (this.inventoryPanel) this.inventoryPanel.style.display = 'none'; });
    panel.appendChild(closeBtn);

    document.body.appendChild(panel);
    this.inventoryPanel = panel;
  }

  private createNotificationEls(): void {
    // Quest completed notification
    const complete = document.createElement('div');
    complete.dataset['testid'] = 'quest-completed';
    complete.style.cssText =
      'display:none;position:fixed;top:30%;left:50%;transform:translateX(-50%);' +
      'background:#163d1f;color:#7fff7f;border:2px solid #3aaf3a;border-radius:8px;' +
      'padding:14px 24px;z-index:300;text-align:center;font-size:1rem;';
    document.body.appendChild(complete);
    this.questCompleteEl = complete;

    // Quest failed / cooldown indicator
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

    // Level-up notification
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

  // --- UI update helpers ---

  private updateCoinsDisplay(): void {
    if (this.coinsEl !== null) {
      this.coinsEl.textContent = `$${this.coins}`;
    }
  }

  private updateLevelDisplay(): void {
    if (this.levelEl !== null) {
      this.levelEl.textContent = `Level: ${this.level}`;
    }
  }

  private updateShopPanel(): void {
    if (this.shopPanelItems === null) return;
    this.shopPanelItems.innerHTML = '';
    for (const item of this.shopBootstrapItems) {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:10px;margin-bottom:8px;';

      const label = document.createElement('span');
      label.textContent = `${item.item_id} ($${item.price})`;
      row.appendChild(label);

      const buyBtn = document.createElement('button');
      buyBtn.textContent = 'Buy';
      buyBtn.dataset['buyItem'] = item.item_id;
      buyBtn.style.cssText = 'padding:4px 10px;cursor:pointer;';
      buyBtn.addEventListener('click', () => {
        if (this.wsClient !== null) {
          this.wsClient.send({ type: 'shop_buy', player_id: this.playerId, item_id: item.item_id });
        }
      });
      row.appendChild(buyBtn);
      this.shopPanelItems.appendChild(row);
    }
  }

  private updateInventoryPanel(): void {
    if (this.inventoryPanelItems === null) return;
    this.inventoryPanelItems.innerHTML = '';
    const allItems = [...this.inventory, ...this.equipment];
    const seen = new Set<string>();
    for (const item of allItems) {
      if (seen.has(item.item_id)) continue;
      seen.add(item.item_id);
      const row = document.createElement('div');
      row.dataset['itemId'] = item.item_id;
      row.dataset['inventoryItem'] = item.item_id;
      row.style.cssText = 'display:flex;align-items:center;gap:10px;margin-bottom:8px;';

      const label = document.createElement('span');
      label.textContent = `${item.item_id} ×${item.quantity}`;
      row.appendChild(label);

      if (this.consumableItemIds.has(item.item_id) && item.quantity > 0) {
        const useBtn = document.createElement('button');
        useBtn.textContent = 'Use';
        useBtn.dataset['useItem'] = item.item_id;
        useBtn.style.cssText = 'padding:4px 10px;cursor:pointer;';
        useBtn.addEventListener('click', () => {
          if (this.wsClient !== null) {
            this.wsClient.send({ type: 'use_item', player_id: this.playerId, item_id: item.item_id });
          }
        });
        row.appendChild(useBtn);
      }
      this.inventoryPanelItems.appendChild(row);
    }
  }

  private showQuestDialog(offer: QuestOffer): void {
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

  private hideQuestDialog(): void {
    if (this.questDialogEl !== null) this.questDialogEl.style.display = 'none';
  }

  private onAcceptQuest(): void {
    if (this.pendingQuestOffer === null || this.wsClient === null) return;
    const questId = this.pendingQuestOffer.questId;
    this.wsClient.send({ type: 'quest_accept', player_id: this.playerId, quest_id: questId });
    this.hideQuestDialog();
    this.pendingQuestOffer = null;
  }

  private showQuestComplete(coinsAwarded: number): void {
    if (this.questCompleteEl === null) return;
    this.questCompleteEl.textContent = `Quest complete! You earned $${coinsAwarded} coins.`;
    this.questCompleteEl.style.display = 'block';
    setTimeout(() => {
      if (this.questCompleteEl !== null) this.questCompleteEl.style.display = 'none';
    }, NOTIFICATION_AUTO_HIDE_MS);
  }

  private showQuestCooldown(cooldownUntil: string): void {
    if (this.questCooldownEl === null) return;
    this.questCooldownEl.textContent = `Quest failed — available after ${cooldownUntil}`;
    this.questCooldownEl.style.display = 'block';
  }

  private hideQuestCooldown(): void {
    if (this.questCooldownEl !== null) this.questCooldownEl.style.display = 'none';
  }

  private showLevelUp(level: number): void {
    if (this.levelUpEl === null) return;
    this.levelUpEl.textContent = `Level ${level}! Level up!`;
    this.levelUpEl.style.display = 'block';
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

  private updateGameStore(): void {
    (window as unknown as Record<string, unknown>)['__gameStore'] = {
      ready: this.sceneReady,
      stateSyncReceived: this.stateSyncReceived,
      wsOpen: this.wsClient?.isOpen() ?? false,
      quests: this.quests.slice(),
      worldItems: this.worldItems.slice(),
      inventory: this.inventory.slice(),
      equipment: this.equipment.slice(),
      player: { coins: this.coins, level: this.level },
    };
  }

  // --- Window event listeners ---

  private registerGameEventListeners(): void {
    this.boundNpcInteract = (e: Event) => {
      const detail = (e as CustomEvent<Record<string, unknown>>).detail;
      const npcId = typeof detail?.['npc_id'] === 'string' ? detail['npc_id'] : '';
      if (npcId && this.wsClient !== null) {
        this.wsClient.send({ type: 'npc_interact_request', player_id: this.playerId, npc_id: npcId });
      }
    };
    this.boundQuestTurnIn = (e: Event) => {
      const detail = (e as CustomEvent<Record<string, unknown>>).detail;
      const questId = typeof detail?.['quest_id'] === 'string' ? detail['quest_id'] : '';
      if (questId) this.sendQuestTurnIn(questId);
    };
    this.boundItemPickup = (e: Event) => {
      const detail = (e as CustomEvent<Record<string, unknown>>).detail;
      const questId = typeof detail?.['quest_id'] === 'string' ? detail['quest_id'] : '';
      const itemId = typeof detail?.['item_id'] === 'string' ? detail['item_id'] : '';
      if (questId && itemId) this.sendItemPickup(questId, itemId);
    };
    window.addEventListener('game:npc-interact', this.boundNpcInteract);
    window.addEventListener('game:quest-turn-in', this.boundQuestTurnIn);
    window.addEventListener('game:item-pickup', this.boundItemPickup);
  }

  // --- Joystick (existing) ---

  private createJoystick(): void {
    const base = document.createElement('div');
    base.id = 'joystick-base';
    base.style.cssText =
      `position:fixed;bottom:60px;left:60px;` +
      `width:${JOYSTICK_RADIUS * 2}px;height:${JOYSTICK_RADIUS * 2}px;` +
      `border-radius:50%;background:rgba(255,255,255,0.3);` +
      `border:2px solid rgba(255,255,255,0.6);touch-action:none;z-index:100;`;
    document.body.appendChild(base);
    this.joystickEl = base;

    base.addEventListener('pointerdown', (e: PointerEvent) => {
      e.preventDefault();
      base.setPointerCapture(e.pointerId);
      this.joystickActive = true;
      this.joystickStartX = e.clientX;
      this.joystickStartY = e.clientY;
      this.joystickDx = 0;
      this.joystickDy = 0;
    });

    base.addEventListener('pointermove', (e: PointerEvent) => {
      if (!this.joystickActive) return;
      const rawDx = e.clientX - this.joystickStartX;
      const rawDy = e.clientY - this.joystickStartY;
      const dist = Math.sqrt(rawDx * rawDx + rawDy * rawDy);
      if (dist === 0) { this.joystickDx = 0; this.joystickDy = 0; return; }
      const clamp = Math.min(dist, JOYSTICK_RADIUS);
      this.joystickDx = (rawDx / dist) * (clamp / JOYSTICK_RADIUS);
      this.joystickDy = (rawDy / dist) * (clamp / JOYSTICK_RADIUS);
    });

    const stopJoystick = (): void => { this.joystickActive = false; this.joystickDx = 0; this.joystickDy = 0; };
    base.addEventListener('pointerup', stopJoystick);
    base.addEventListener('pointercancel', stopJoystick);
  }

  update(_time: number, delta: number): void {
    if (!this.joystickActive || this.wsClient === null || !this.stateSyncReceived) return;
    if (this.joystickDx === 0 && this.joystickDy === 0) return;

    const dt = delta / 1000;
    this.playerX += this.joystickDx * PLAYER_SPEED * dt;
    this.playerY += this.joystickDy * PLAYER_SPEED * dt;
    this.playerDirection = this.resolveDirection(this.joystickDx, this.joystickDy);
    this.clientTick++;

    this.wsClient.sendMove({
      type: 'player_move',
      player_id: this.playerId,
      x: this.playerX,
      y: this.playerY,
      direction: this.playerDirection,
      client_tick: this.clientTick,
    });
  }

  private resolveDirection(dx: number, dy: number): string {
    if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? 'right' : 'left';
    return dy >= 0 ? 'down' : 'up';
  }

  shutdown(): void {
    // Clear timer
    if (this.questTimerInterval !== null) {
      clearInterval(this.questTimerInterval);
      this.questTimerInterval = null;
    }
    // Remove event listeners
    if (this.boundNpcInteract !== null) window.removeEventListener('game:npc-interact', this.boundNpcInteract);
    if (this.boundQuestTurnIn !== null) window.removeEventListener('game:quest-turn-in', this.boundQuestTurnIn);
    if (this.boundItemPickup !== null) window.removeEventListener('game:item-pickup', this.boundItemPickup);
    // Remove DOM elements
    const idsToRemove = ['hud', 'quest-dialog', 'quest-timer', 'shop-panel', 'inventory-panel', 'bootstrap-error'];
    for (const id of idsToRemove) {
      const el = document.getElementById(id);
      if (el?.parentElement) el.parentElement.removeChild(el);
    }
    if (this.questCompleteEl?.parentElement) this.questCompleteEl.parentElement.removeChild(this.questCompleteEl);
    if (this.questCooldownEl?.parentElement) this.questCooldownEl.parentElement.removeChild(this.questCooldownEl);
    if (this.levelUpEl?.parentElement) this.levelUpEl.parentElement.removeChild(this.levelUpEl);
    // Remove joystick
    if (this.joystickEl?.parentElement) {
      this.joystickEl.parentElement.removeChild(this.joystickEl);
      this.joystickEl = null;
    }
  }
}
