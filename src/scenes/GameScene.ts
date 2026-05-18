import Phaser from 'phaser';
import { SCENE_KEYS } from './sceneKeys';
import { buildMapTileLoadList } from '../assets/loader';
import type { MapTileManifest } from '../assets/loader';
import mapTilesJson from '../../config/map_tiles.json';
import { WSClient } from '../net/WSClient';
import { isStateSyncMsg } from '../net/protocol';

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
  private stateSyncReceived = false;
  private joystickEl: HTMLDivElement | null = null;
  private joystickActive = false;
  private joystickStartX = 0;
  private joystickStartY = 0;
  private joystickDx = 0;
  private joystickDy = 0;

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
    this.cameras.main.setBounds(
      0,
      0,
      MAP_TILE_MANIFEST.map_width,
      MAP_TILE_MANIFEST.map_height,
    );

    this.connectWebSocket();
    this.createJoystick();
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
    if (!isStateSyncMsg(msg)) return;
    const p = msg.player;
    if (typeof p['x'] === 'number') this.playerX = p['x'];
    if (typeof p['y'] === 'number') this.playerY = p['y'];
    if (typeof p['direction'] === 'string') this.playerDirection = p['direction'];
    this.stateSyncReceived = true;
  }

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
      if (dist === 0) {
        this.joystickDx = 0;
        this.joystickDy = 0;
        return;
      }
      const clamp = Math.min(dist, JOYSTICK_RADIUS);
      this.joystickDx = (rawDx / dist) * (clamp / JOYSTICK_RADIUS);
      this.joystickDy = (rawDy / dist) * (clamp / JOYSTICK_RADIUS);
    });

    const stopJoystick = (): void => {
      this.joystickActive = false;
      this.joystickDx = 0;
      this.joystickDy = 0;
    };

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
    if (Math.abs(dx) >= Math.abs(dy)) {
      return dx >= 0 ? 'right' : 'left';
    }
    return dy >= 0 ? 'down' : 'up';
  }

  shutdown(): void {
    if (this.joystickEl !== null && this.joystickEl.parentElement !== null) {
      this.joystickEl.parentElement.removeChild(this.joystickEl);
      this.joystickEl = null;
    }
  }
}
