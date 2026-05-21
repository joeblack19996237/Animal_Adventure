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
});

describe('PlayerMovementController', () => {
  it('does not send movement before the first state_sync', () => {
    const sent: Record<string, unknown>[] = [];
    const controller = new PlayerMovementController(300);
    controller.setPlayerId('p1');
    const input = applyKeyDown(createInputState(), 'd');

    controller.tick(1000, input, { sendMove: (msg) => sent.push(msg) });

    expect(sent).toHaveLength(0);
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
});
