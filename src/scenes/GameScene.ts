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
import { GameDomController } from './game/GameDomController';
import { publishGameStore } from './game/GameStoreDebug';
import { JoystickController } from './game/JoystickController';
import {
  formatCountdown,
  isItemRecord,
  isShopBootstrapItem,
  toInventoryRecord,
  toQuestRecord,
  toWorldItemRecord,
  type InventoryRecord,
  type QuestOffer,
  type QuestRecord,
  type ShopBootstrapItem,
  type WorldItemRecord,
} from './game/gameRecords';
import {
  applyJoystickMove,
  applyJoystickRelease,
  applyKeyDown,
  applyKeyUp,
  createInputState,
  getMovementVector,
  type InputState,
} from '../state/input';

const MAP_TILE_MANIFEST: MapTileManifest = mapTilesJson;
const PLAYER_ID_KEY = 'animal_adventure_player_id';
const PLAYER_SPEED = 300;
const JOYSTICK_RADIUS = 48;
export class GameScene extends Phaser.Scene {
  private wsClient: WSClient | null = null;
  private playerId = '';
  private playerX = 0;
  private playerY = 0;
  private playerDirection = 'down';
  private clientTick = 0;
  private sceneReady = false;
  private stateSyncReceived = false;
  private inputState: InputState = createInputState();
  private quests: QuestRecord[] = [];
  private worldItems: WorldItemRecord[] = [];
  private inventory: InventoryRecord[] = [];
  private equipment: InventoryRecord[] = [];
  private coins = 0;
  private level = 0;
  private serverTimeOffsetMs = 0;
  private pendingQuestOffer: QuestOffer | null = null;
  private activeQuestId: string | null = null;
  private completedQuestIds: Set<string> = new Set();
  private questDeadlineMs: number | null = null;
  private questTimerInterval: ReturnType<typeof setInterval> | null = null;
  private shopBootstrapItems: ShopBootstrapItem[] = [];
  private consumableItemIds: Set<string> = new Set();
  private dom: GameDomController;
  private joystick: JoystickController;
  private boundNpcInteract: ((e: Event) => void) | null = null;
  private boundQuestTurnIn: ((e: Event) => void) | null = null;
  private boundItemPickup: ((e: Event) => void) | null = null;
  private boundKeyDown: ((e: KeyboardEvent) => void) | null = null;
  private boundKeyUp: ((e: KeyboardEvent) => void) | null = null;

  constructor() {
    super({ key: SCENE_KEYS.GAME });
    this.dom = new GameDomController({
      onAcceptQuest: () => this.onAcceptQuest(),
      onBuyItem: (itemId) => this.sendShopBuy(itemId),
      onUseItem: (itemId) => this.sendUseItem(itemId),
      onTurnInQuest: () => {
        const questId = this.activeQuestId ?? '';
        if (questId) this.sendQuestTurnIn(questId);
      },
      onBootstrapRetry: () => void this.loadBootstrapAsync(),
    });
    this.joystick = new JoystickController(
      JOYSTICK_RADIUS,
      (dx, dy) => {
        this.inputState = applyJoystickMove(this.inputState, dx, dy);
      },
      () => {
        this.inputState = applyJoystickRelease(this.inputState);
      },
    );
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
    this.joystick.create();
    this.dom.create();
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
      this.dom.showBootstrapError(result.message);
      return;
    }
    this.dom.hideBootstrapError();
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
      this.dom.showQuestCooldown(failedQuest.cooldown_until);
    } else {
      this.dom.hideQuestCooldown();
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
    this.dom.showQuestDialog(this.pendingQuestOffer);
  }

  private handleQuestStarted(msg: QuestStartedMsg): void {
    this.activeQuestId = msg.quest_id;
    this.dom.hideQuestDialog();
    this.startQuestTimer(msg.expires_at, null);
    const newItems = (msg.world_items as unknown[]).map(toWorldItemRecord).filter((w): w is WorldItemRecord => w !== null);
    this.worldItems = [...this.worldItems, ...newItems];
    this.dom.setTurnInQuest(null);
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
    this.dom.setTurnInQuest(this.activeQuestId);
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
    this.dom.setTurnInQuest(null);
    this.dom.showQuestComplete(coinsAwarded);
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
    if (cooldownUntil !== null) this.dom.showQuestCooldown(cooldownUntil);
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
    this.dom.showLevelUp(msg.level);
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
    const worldItem = this.worldItems.find(
      (item) => item.item_id === itemId && item.quest_instance_id === q?.quest_instance_id,
    );
    this.wsClient.send({
      type: 'item_pickup_request',
      player_id: this.playerId,
      quest_id: questId,
      item_id: itemId,
      item_instance_id: worldItem?.id ?? itemId,
      x: this.playerX,
      y: this.playerY,
    });
  }

  private sendShopBuy(itemId: string): void {
    if (this.wsClient !== null) {
      this.wsClient.send({ type: 'shop_buy', player_id: this.playerId, item_id: itemId });
    }
  }

  private sendUseItem(itemId: string): void {
    if (this.wsClient !== null) {
      this.wsClient.send({ type: 'use_item', player_id: this.playerId, item_id: itemId });
    }
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
    this.dom.hideQuestTimer();
  }

  private tickQuestTimer(): void {
    if (this.questDeadlineMs === null) return;
    const remainingMs = this.questDeadlineMs - Date.now();
    this.dom.showQuestTimer(formatCountdown(remainingMs));
  }

  private updateCoinsDisplay(): void {
    this.dom.updateCoinsDisplay(this.coins);
  }

  private updateLevelDisplay(): void {
    this.dom.updateLevelDisplay(this.level);
  }

  private updateShopPanel(): void {
    this.dom.updateShopPanel(this.shopBootstrapItems);
  }

  private updateInventoryPanel(): void {
    this.dom.updateInventoryPanel(this.inventory, this.equipment, this.consumableItemIds);
  }

  private onAcceptQuest(): void {
    if (this.pendingQuestOffer === null || this.wsClient === null) return;
    const questId = this.pendingQuestOffer.questId;
    this.wsClient.send({ type: 'quest_accept', player_id: this.playerId, quest_id: questId });
    this.dom.hideQuestDialog();
    this.pendingQuestOffer = null;
  }

  private updateGameStore(): void {
    publishGameStore({
      ready: this.sceneReady,
      stateSyncReceived: this.stateSyncReceived,
      wsOpen: this.wsClient?.isOpen() ?? false,
      quests: this.quests.slice(),
      worldItems: this.worldItems.slice(),
      inventory: this.inventory.slice(),
      equipment: this.equipment.slice(),
      player: { coins: this.coins, level: this.level },
    });
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
    this.boundKeyDown = (e: KeyboardEvent) => {
      this.inputState = applyKeyDown(this.inputState, e.key);
    };
    this.boundKeyUp = (e: KeyboardEvent) => {
      this.inputState = applyKeyUp(this.inputState, e.key);
    };
    window.addEventListener('keydown', this.boundKeyDown);
    window.addEventListener('keyup', this.boundKeyUp);
  }

  update(_time: number, delta: number): void {
    if (this.wsClient === null || !this.stateSyncReceived) return;
    const vector = getMovementVector(this.inputState);
    if (vector.dx === 0 && vector.dy === 0) return;
    const magnitude = Math.sqrt(vector.dx * vector.dx + vector.dy * vector.dy);
    const dx = magnitude > 1 ? vector.dx / magnitude : vector.dx;
    const dy = magnitude > 1 ? vector.dy / magnitude : vector.dy;

    const dt = delta / 1000;
    this.playerX += dx * PLAYER_SPEED * dt;
    this.playerY += dy * PLAYER_SPEED * dt;
    this.playerDirection = this.resolveDirection(dx, dy);
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
    if (this.questTimerInterval !== null) {
      clearInterval(this.questTimerInterval);
      this.questTimerInterval = null;
    }
    if (this.boundNpcInteract !== null) window.removeEventListener('game:npc-interact', this.boundNpcInteract);
    if (this.boundQuestTurnIn !== null) window.removeEventListener('game:quest-turn-in', this.boundQuestTurnIn);
    if (this.boundItemPickup !== null) window.removeEventListener('game:item-pickup', this.boundItemPickup);
    if (this.boundKeyDown !== null) window.removeEventListener('keydown', this.boundKeyDown);
    if (this.boundKeyUp !== null) window.removeEventListener('keyup', this.boundKeyUp);
    this.dom.destroy();
    this.joystick.destroy();
  }
}
