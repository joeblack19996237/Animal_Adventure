import Phaser from 'phaser';
import { SCENE_KEYS } from './sceneKeys';
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
import { BackgroundMusicController, loadBackgroundMusic } from './game/BackgroundMusicController';
import { chooseCameraZoom } from './game/CameraViewport';
import { GameDomController } from './game/GameDomController';
import { publishGameStore } from './game/GameStoreDebug';
import { JoystickController } from './game/JoystickController';
import { MapTileRenderer, preloadInitialMapTiles } from './game/MapTileRenderer';
import { NpcAutoTriggerController } from './game/NpcAutoTriggerController';
import { PlayerMovementController } from './game/PlayerMovementController';
import { QuestTimerController } from './game/QuestTimerController';
import { findNearestNpc, findNearestWorldItem } from './game/WorldInteraction';
import { WorldRenderer, loadWorldTextures } from './game/WorldRenderer';
import { isMovementBlocked } from './game/WorldCollision';
import {
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
  type InputState,
} from '../state/input';

const MAP_TILE_MANIFEST: MapTileManifest = mapTilesJson;
const PLAYER_ID_KEY = 'animal_adventure_player_id';
const PLAYER_SPEED = 300;
const PLAYER_COLLISION_RADIUS = 38;
const JOYSTICK_RADIUS = 48;
export class GameScene extends Phaser.Scene {
  private wsClient: WSClient | null = null;
  private playerId = '';
  private sceneReady = false;
  private inputState: InputState = createInputState();
  private readonly movement = new PlayerMovementController(
    PLAYER_SPEED,
    PLAYER_COLLISION_RADIUS,
    (x, y, radius) => isMovementBlocked(x, y, radius),
  );
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
  private shopBootstrapItems: ShopBootstrapItem[] = [];
  private consumableItemIds: Set<string> = new Set();
  private dom: GameDomController;
  private joystick: JoystickController;
  private mapRenderer: MapTileRenderer | null = null;
  private worldRenderer: WorldRenderer | null = null;
  private music: BackgroundMusicController | null = null;
  private readonly npcAutoTrigger = new NpcAutoTriggerController();
  private readonly questTimer = new QuestTimerController(
    (text, ratio) => this.dom.showQuestTimer(text, ratio),
    () => this.dom.hideQuestTimer(),
  );
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
    preloadInitialMapTiles(this, MAP_TILE_MANIFEST);
    loadWorldTextures(this);
    loadBackgroundMusic(this);
  }
  create(): void {
    this.mapRenderer = new MapTileRenderer(this, MAP_TILE_MANIFEST);
    this.mapRenderer.renderLoadedTiles();
    this.cameras.main.setBounds(0, 0, MAP_TILE_MANIFEST.map_width, MAP_TILE_MANIFEST.map_height);
    this.cameras.main.setZoom(chooseCameraZoom());
    this.joystick.create();
    this.worldRenderer = new WorldRenderer(this);
    this.worldRenderer.createNpcs((npcId) => this.sendNpcInteract(npcId));
    this.dom.create();
    this.music = new BackgroundMusicController(this);
    this.registerGameEventListeners();
    this.sceneReady = true;
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
    this.connectWebSocket();
    this.updateGameStore();
  }

  private connectWebSocket(): void {
    const storedId = localStorage.getItem(PLAYER_ID_KEY);
    if (storedId === null) return;
    if (this.wsClient !== null) return;
    this.playerId = storedId;
    this.movement.setPlayerId(storedId);
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
    this.movement.applyServerSnapshot({ x: p['x'], y: p['y'], direction: p['direction'] });
    this.mapRenderer?.ensureTilesAround(this.movement.getX(), this.movement.getY());
    this.worldRenderer?.updatePlayerFromServer(p);
    if (typeof p['coins'] === 'number') this.coins = p['coins'];
    if (typeof p['level'] === 'number') this.level = p['level'];

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
      this.questTimer.start(activeQuest.expires_at, msg.server_time, this.serverTimeOffsetMs);
    } else {
      if (activeQuest === undefined) this.activeQuestId = null;
      this.questTimer.stop();
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
    this.renderWorldItems();
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
    this.questTimer.start(msg.expires_at, null, this.serverTimeOffsetMs);
    const newItems = (msg.world_items as unknown[]).map(toWorldItemRecord).filter((w): w is WorldItemRecord => w !== null);
    this.worldItems = [...this.worldItems, ...newItems];
    this.renderWorldItems();
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
    this.worldItems = this.worldItems.filter((item) => item.item_id !== msg['item_id']);
    this.renderWorldItems();
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
    this.questTimer.stop();
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
    this.questTimer.stop();
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
    this.wsClient.send({ type: 'quest_turn_in', player_id: this.playerId, quest_id: questId, x: this.movement.getX(), y: this.movement.getY() });
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
      x: this.movement.getX(),
      y: this.movement.getY(),
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

  private updateCoinsDisplay(): void { this.dom.updateCoinsDisplay(this.coins); }

  private updateLevelDisplay(): void { this.dom.updateLevelDisplay(this.level); }

  private updateShopPanel(): void { this.dom.updateShopPanel(this.shopBootstrapItems); }

  private updateInventoryPanel(): void { this.dom.updateInventoryPanel(this.inventory, this.equipment, this.consumableItemIds); }

  private onAcceptQuest(): void {
    if (this.pendingQuestOffer === null || this.wsClient === null) return;
    const questId = this.pendingQuestOffer.questId;
    this.wsClient.send({ type: 'quest_accept', player_id: this.playerId, quest_id: questId });
    this.dom.hideQuestDialog();
    this.pendingQuestOffer = null;
  }

  private sendNpcInteract(npcId: string): void {
    if (this.wsClient !== null) this.wsClient.send({ type: 'npc_interact_request', player_id: this.playerId, npc_id: npcId, x: this.movement.getX(), y: this.movement.getY() });
  }

  private interactWithNearestNpc(): void {
    const npc = findNearestNpc(this.movement.getX(), this.movement.getY());
    if (npc !== null) this.sendNpcInteract(npc.id);
  }

  private pickUpNearestWorldItem(): void {
    if (this.activeQuestId === null) return;
    const item = findNearestWorldItem(this.worldItems, this.movement.getX(), this.movement.getY());
    if (item !== null) this.sendItemPickup(this.activeQuestId, item.item_id);
  }

  private renderWorldItems(): void {
    this.worldRenderer?.renderWorldItems(this.worldItems, (item) => { if (this.activeQuestId !== null) this.sendItemPickup(this.activeQuestId, item.item_id); });
  }

  private updateGameStore(): void {
    publishGameStore({
      ready: this.sceneReady,
      stateSyncReceived: this.movement.hasStateSyncReceived(),
      wsOpen: this.wsClient?.isOpen() ?? false,
      quests: this.quests.slice(),
      worldItems: this.worldItems.slice(),
      inventory: this.inventory.slice(),
      equipment: this.equipment.slice(),
      player: { coins: this.coins, level: this.level },
    });
  }

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
    this.input.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
      this.music?.startAfterUserGesture();
      if (this.movement.hasStateSyncReceived()) this.movement.setMoveTarget(pointer.worldX, pointer.worldY);
    });
    this.boundKeyDown = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === 'e') {
        this.interactWithNearestNpc();
      } else if (e.code === 'Space') {
        this.pickUpNearestWorldItem();
      }
      this.music?.startAfterUserGesture();
      this.inputState = applyKeyDown(this.inputState, e.key);
    };
    this.boundKeyUp = (e: KeyboardEvent) => {
      this.inputState = applyKeyUp(this.inputState, e.key);
    };
    window.addEventListener('keydown', this.boundKeyDown);
    window.addEventListener('keyup', this.boundKeyUp);
  }

  update(_time: number, delta: number): void {
    this.movement.tick(delta, this.inputState, this.wsClient);
    this.worldRenderer?.updatePlayerPosition(
      this.movement.getX(),
      this.movement.getY(),
      this.movement.getDirection(),
      this.movement.isMoving(),
    );
    this.mapRenderer?.ensureTilesAround(this.movement.getX(), this.movement.getY());
    this.npcAutoTrigger.tick(
      this.movement.getX(),
      this.movement.getY(),
      this.pendingQuestOffer === null && this.activeQuestId === null,
      (npcId) => this.sendNpcInteract(npcId),
    );
  }

  shutdown(): void {
    this.questTimer.stop();
    if (this.boundNpcInteract !== null) window.removeEventListener('game:npc-interact', this.boundNpcInteract);
    if (this.boundQuestTurnIn !== null) window.removeEventListener('game:quest-turn-in', this.boundQuestTurnIn);
    if (this.boundItemPickup !== null) window.removeEventListener('game:item-pickup', this.boundItemPickup);
    if (this.boundKeyDown !== null) window.removeEventListener('keydown', this.boundKeyDown);
    if (this.boundKeyUp !== null) window.removeEventListener('keyup', this.boundKeyUp);
    this.dom.destroy();
    this.joystick.destroy();
    this.music?.destroy();
    this.music = null;
    this.worldRenderer?.destroy();
    this.worldRenderer = null;
  }
}
