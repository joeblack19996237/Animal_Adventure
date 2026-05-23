import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  applyKeyDown,
  applyJoystickMove,
  createInputState,
} from '../../src/state/input';
import { PlayerMovementController } from '../../src/scenes/game/PlayerMovementController';

describe('game scene movement structure', () => {
  it('keeps GameScene.update as a thin movement controller delegation', () => {
    const source = readFileSync(join(process.cwd(), 'src/scenes/GameScene.ts'), 'utf-8');
    const updateMatch = source.match(/\n  update\(_time: number, delta: number\): void \{([\s\S]*?)\n  \}/);
    expect(updateMatch?.[1]).toContain('this.movement.tick(delta, this.inputState, this.wsClient);');
    expect(updateMatch?.[1]).not.toContain('getMovementVector');
    expect(updateMatch?.[1]).not.toContain('Math.sqrt');
    expect(updateMatch?.[1]).not.toContain('sendMove');
    expect(source).not.toMatch(/connectWebSocket\(\);\s*\n\s*this\.updateGameStore\(\);\s*\n\s*void this\.loadBootstrapAsync\(\);/);
  });

  it('preloads only initial map tiles instead of all map tiles', () => {
    const source = readFileSync(join(process.cwd(), 'src/scenes/GameScene.ts'), 'utf-8');
    expect(source).toContain('preloadInitialMapTiles(this, MAP_TILE_MANIFEST);');
    expect(source).toContain('preloadInitialForegroundTiles(this, MAP_TILE_MANIFEST, FOREGROUND_TILE_MANIFEST);');
    expect(source).not.toContain('buildMapTileLoadList');
  });

  it('passes the sparse foreground tile manifest into the map renderer', () => {
    const source = readFileSync(join(process.cwd(), 'src/scenes/GameScene.ts'), 'utf-8');
    expect(source).toContain("import foregroundTilesJson from '../../config/foreground_tiles.json';");
    expect(source).toContain('const FOREGROUND_TILE_MANIFEST: ForegroundTileManifest = foregroundTilesJson;');
    expect(source).toContain('new MapTileRenderer(this, MAP_TILE_MANIFEST, FOREGROUND_TILE_MANIFEST);');
  });

  it('uses responsive camera zoom and removes NPC text labels from world rendering', () => {
    const sceneSource = readFileSync(join(process.cwd(), 'src/scenes/GameScene.ts'), 'utf-8');
    const cameraSource = readFileSync(join(process.cwd(), 'src/scenes/game/CameraViewport.ts'), 'utf-8');
    const rendererSource = readFileSync(join(process.cwd(), 'src/scenes/game/WorldRenderer.ts'), 'utf-8');
    expect(sceneSource).toContain('this.cameras.main.setZoom(chooseCameraZoom());');
    expect(cameraSource).toContain("import { isTouchDevice } from '../../layout/device';");
    expect(cameraSource).toContain('return isTouchDevice() ? 0.58 : 0.66;');
    expect(rendererSource).not.toContain('.text(');
    expect(rendererSource).not.toContain('E / Click');
  });

  it('uses per-tile foreground depth while keeping locked overlays map-height based', () => {
    const source = readFileSync(join(process.cwd(), 'src/scenes/game/MapTileRenderer.ts'), 'utf-8');
    expect(source).toContain('export function foregroundDepthForTile(tile: MapTile): number');
    expect(source).toContain('return tile.y + tile.height + 10;');
    expect(source).toContain('this.lockedOverlayDepth = this.manifest.map_height + 1000;');
    expect(source).toContain('.setDepth(this.lockedOverlayDepth + 1)');
  });

  it('loads background music and registers automatic NPC proximity triggers', () => {
    const source = readFileSync(join(process.cwd(), 'src/scenes/GameScene.ts'), 'utf-8');
    expect(source).toContain('loadBackgroundMusic(this);');
    expect(source).toContain('new BackgroundMusicController(this)');
    expect(source).toContain('this.npcAutoTrigger.tick(');
  });
});

describe('PlayerMovementController', () => {
  it('does not send movement before the first state_sync', () => {
    const sent: Record<string, unknown>[] = [];
    const controller = new PlayerMovementController(300);
    controller.setPlayerId('p1');
    const input = applyKeyDown(createInputState(), 'd');

    controller.tick(1000, input, { sendMove: (msg) => sent.push(msg) });

    expect(sent).toHaveLength(0);
    expect(controller.isMoving()).toBe(false);
  });

  it('predicts keyboard movement and sends the player_move payload after state_sync', () => {
    const sent: Record<string, unknown>[] = [];
    const controller = new PlayerMovementController(300);
    controller.setPlayerId('p1');
    controller.applyServerSnapshot({ x: 10, y: 20, direction: 'down' });
    const input = applyKeyDown(createInputState(), 'd');

    controller.tick(1000, input, { sendMove: (msg) => sent.push(msg) });

    expect(sent).toEqual([
      {
        type: 'player_move',
        player_id: 'p1',
        x: 310,
        y: 20,
        direction: 'right',
        client_tick: 1,
      },
    ]);
    expect(controller.isMoving()).toBe(true);
  });

  it('normalizes diagonal joystick movement', () => {
    const sent: Record<string, unknown>[] = [];
    const controller = new PlayerMovementController(300);
    controller.setPlayerId('p1');
    controller.applyServerSnapshot({ x: 0, y: 0, direction: 'down' });
    const input = applyJoystickMove(createInputState(), 1, 1);

    controller.tick(1000, input, { sendMove: (msg) => sent.push(msg) });

    expect(sent[0]['x']).toBeCloseTo(212.132, 3);
    expect(sent[0]['y']).toBeCloseTo(212.132, 3);
    expect(sent[0]['direction']).toBe('right');
  });

  it('moves toward a tap target when no keyboard or joystick input is active', () => {
    const sent: Record<string, unknown>[] = [];
    const controller = new PlayerMovementController(300);
    controller.setPlayerId('p1');
    controller.applyServerSnapshot({ x: 100, y: 100, direction: 'down' });
    controller.setMoveTarget(400, 100);

    controller.tick(1000, createInputState(), { sendMove: (msg) => sent.push(msg) });

    expect(sent[0]).toMatchObject({
      type: 'player_move',
      player_id: 'p1',
      x: 400,
      y: 100,
      direction: 'right',
    });
  });

  it('does not send movement when the predicted position is blocked', () => {
    const sent: Record<string, unknown>[] = [];
    const controller = new PlayerMovementController(300, 38, () => true);
    controller.setPlayerId('p1');
    controller.applyServerSnapshot({ x: 100, y: 100, direction: 'down' });
    controller.setMoveTarget(400, 100);

    controller.tick(1000, createInputState(), { sendMove: (msg) => sent.push(msg) });

    expect(sent).toHaveLength(0);
    expect(controller.isMoving()).toBe(false);
  });

  it('reports idle after a tick with no movement vector', () => {
    const controller = new PlayerMovementController(300);
    controller.setPlayerId('p1');
    controller.applyServerSnapshot({ x: 100, y: 100, direction: 'down' });

    controller.tick(1000, createInputState(), { sendMove: () => undefined });

    expect(controller.isMoving()).toBe(false);
  });
});
