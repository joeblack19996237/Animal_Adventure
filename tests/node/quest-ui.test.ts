import { describe, it, expect } from 'vitest';
import { NPC } from '../../src/entities/NPC';
import { WorldItem, WorldItemStatus } from '../../src/entities/WorldItem';

describe('NPC', () => {
  it('stores id, name, position, and interaction radius on construction', () => {
    const npc = new NPC({ id: 'hopper', name: 'Hopper', x: 2715, y: 3200, interactionRadius: 160 });
    expect(npc.id).toBe('hopper');
    expect(npc.name).toBe('Hopper');
    expect(npc.x).toBe(2715);
    expect(npc.y).toBe(3200);
    expect(npc.interactionRadius).toBe(160);
  });

  describe('isPlayerInRange', () => {
    it('returns true when player is within interaction radius', () => {
      const npc = new NPC({ id: 'hopper', name: 'Hopper', x: 2715, y: 3200, interactionRadius: 160 });
      expect(npc.isPlayerInRange(2715, 3200)).toBe(true);
    });

    it('returns true when player is exactly at interaction radius boundary', () => {
      const npc = new NPC({ id: 'copper', name: 'Copper', x: 3150, y: 3620, interactionRadius: 160 });
      expect(npc.isPlayerInRange(3150 + 160, 3620)).toBe(true);
    });

    it('returns false when player is beyond interaction radius', () => {
      const npc = new NPC({ id: 'elisa', name: 'Elisa', x: 2715, y: 4050, interactionRadius: 160 });
      expect(npc.isPlayerInRange(2715 + 161, 4050)).toBe(false);
    });

    it('uses euclidean distance for radius check', () => {
      const npc = new NPC({ id: 'hopper', name: 'Hopper', x: 0, y: 0, interactionRadius: 100 });
      // (60, 80) has euclidean distance of 100 — exactly on boundary
      expect(npc.isPlayerInRange(60, 80)).toBe(true);
      // (61, 80) is beyond 100
      expect(npc.isPlayerInRange(61, 80)).toBe(false);
    });
  });
});

describe('WorldItem', () => {
  it('stores id, item_id, quest_instance_id, position, and initial status on construction', () => {
    const item = new WorldItem({
      id: 'wi-1',
      itemId: 'item_blanket',
      questInstanceId: 42,
      x: 2600,
      y: 3100,
    });
    expect(item.id).toBe('wi-1');
    expect(item.itemId).toBe('item_blanket');
    expect(item.questInstanceId).toBe(42);
    expect(item.x).toBe(2600);
    expect(item.y).toBe(3100);
    expect(item.status).toBe(WorldItemStatus.Spawned);
  });

  describe('pickup', () => {
    it('transitions status from spawned to picked_up', () => {
      const item = new WorldItem({ id: 'wi-2', itemId: 'item_bagpipe', questInstanceId: 7, x: 3330, y: 3500 });
      item.pickup();
      expect(item.status).toBe(WorldItemStatus.PickedUp);
    });

    it('throws when attempting pickup on an already picked_up item', () => {
      const item = new WorldItem({ id: 'wi-3', itemId: 'item_bagpipe', questInstanceId: 7, x: 3330, y: 3500 });
      item.pickup();
      expect(() => item.pickup()).toThrow();
    });

    it('throws when attempting pickup on an expired item', () => {
      const item = new WorldItem({ id: 'wi-4', itemId: 'item_dance_shoes', questInstanceId: 9, x: 2830, y: 4250 });
      item.expire();
      expect(() => item.pickup()).toThrow();
    });
  });

  describe('expire', () => {
    it('transitions status from spawned to expired', () => {
      const item = new WorldItem({ id: 'wi-5', itemId: 'item_blanket', questInstanceId: 1, x: 2600, y: 3100 });
      item.expire();
      expect(item.status).toBe(WorldItemStatus.Expired);
    });

    it('is idempotent when called on an already expired item', () => {
      const item = new WorldItem({ id: 'wi-6', itemId: 'item_blanket', questInstanceId: 1, x: 2600, y: 3100 });
      item.expire();
      expect(() => item.expire()).not.toThrow();
      expect(item.status).toBe(WorldItemStatus.Expired);
    });

    it('throws when attempting to expire a picked_up item', () => {
      const item = new WorldItem({ id: 'wi-7', itemId: 'item_blanket', questInstanceId: 1, x: 2600, y: 3100 });
      item.pickup();
      expect(() => item.expire()).toThrow();
    });
  });

  describe('isPlayerInPickupRange', () => {
    it('returns true when player is within pickup radius', () => {
      const item = new WorldItem({ id: 'wi-8', itemId: 'item_blanket', questInstanceId: 1, x: 0, y: 0 });
      expect(item.isPlayerInPickupRange(0, 0, 96)).toBe(true);
    });

    it('returns true when player is exactly at pickup radius boundary', () => {
      const item = new WorldItem({ id: 'wi-9', itemId: 'item_blanket', questInstanceId: 1, x: 0, y: 0 });
      expect(item.isPlayerInPickupRange(96, 0, 96)).toBe(true);
    });

    it('returns false when player is beyond pickup radius', () => {
      const item = new WorldItem({ id: 'wi-10', itemId: 'item_blanket', questInstanceId: 1, x: 0, y: 0 });
      expect(item.isPlayerInPickupRange(97, 0, 96)).toBe(false);
    });
  });
});
