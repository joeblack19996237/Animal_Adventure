import { describe, expect, it } from 'vitest';
import {
  isMovementBlocked,
  isPointInLockedRegion,
  npcCollisionBlockers,
  WORLD_BOUNDS,
} from '../../src/scenes/game/WorldCollision';

describe('WorldCollision', () => {
  it('keeps the spawn lane traversable', () => {
    expect(isMovementBlocked(2715, 3620, 38, [])).toBe(false);
  });

  it('blocks movement at the expanded world boundary', () => {
    expect(isMovementBlocked(WORLD_BOUNDS.x + 10, 3620, 38, [])).toBe(true);
    expect(isMovementBlocked(WORLD_BOUNDS.width - 10, 3620, 38, [])).toBe(true);
  });

  it('blocks configured rect, circle, and polygon zones', () => {
    expect(isMovementBlocked(520, 3200, 38, [])).toBe(true);
    expect(isMovementBlocked(3310, 4860, 38, [])).toBe(true);
    expect(isMovementBlocked(420, 5400, 38, [])).toBe(true);
  });

  it('blocks screenshot-backed building and water coordinates', () => {
    expect(isMovementBlocked(1080, 2340, 38, [])).toBe(true);
    expect(isMovementBlocked(1010, 5440, 38, [])).toBe(true);
    expect(isMovementBlocked(2700, 840, 38, [])).toBe(true);
  });

  it('allows bridge movement through a blocked river polygon', () => {
    expect(isMovementBlocked(2260, 5260, 38, [])).toBe(false);
  });

  it('does not block ordinary grass just because a future region is visible', () => {
    expect(isMovementBlocked(2715, 4300, 38, [])).toBe(false);
  });

  it('detects locked regions separately from physical collision', () => {
    expect(isPointInLockedRegion(4100, 1200, 0)).toBe(true);
    expect(isPointInLockedRegion(4100, 1200, 3)).toBe(false);
  });

  it('treats NPCs as dynamic blockers while leaving interaction range reachable', () => {
    const hopper = npcCollisionBlockers().find((npc) => npc.id === 'hopper');
    expect(hopper).toBeDefined();
    expect(isMovementBlocked(2715, 3200, 38)).toBe(true);
    expect(isMovementBlocked(2715, 3105, 38)).toBe(false);
  });
});
