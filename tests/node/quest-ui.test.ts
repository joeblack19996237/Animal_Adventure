import { describe, it, expect, vi } from 'vitest';
import { NPC } from '../../src/entities/NPC';
import { WorldItem, WorldItemStatus } from '../../src/entities/WorldItem';
import { QuestPanel } from '../../src/ui/QuestPanel';
import type { QuestOffer } from '../../src/ui/QuestPanel';

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

    it('uses euclidean distance — on boundary returns true, one pixel beyond returns false', () => {
      const npc = new NPC({ id: 'hopper', name: 'Hopper', x: 0, y: 0, interactionRadius: 100 });
      expect(npc.isPlayerInRange(60, 80)).toBe(true);
      expect(npc.isPlayerInRange(61, 80)).toBe(false);
    });
  });
});

describe('WorldItem', () => {
  it('stores id, itemId, questInstanceId, position, and initial status on construction', () => {
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
    it('transitions status from spawned to expired and is idempotent on already-expired item', () => {
      const item = new WorldItem({ id: 'wi-5', itemId: 'item_blanket', questInstanceId: 1, x: 2600, y: 3100 });
      item.expire();
      expect(item.status).toBe(WorldItemStatus.Expired);
      expect(() => item.expire()).not.toThrow();
    });

    it('throws when attempting to expire a picked_up item', () => {
      const item = new WorldItem({ id: 'wi-7', itemId: 'item_blanket', questInstanceId: 1, x: 2600, y: 3100 });
      item.pickup();
      expect(() => item.expire()).toThrow();
    });
  });

  describe('isPlayerInPickupRange', () => {
    it.each([
      { px: 0, py: 0, radius: 96, expected: true, label: 'within radius' },
      { px: 96, py: 0, radius: 96, expected: true, label: 'on boundary' },
      { px: 97, py: 0, radius: 96, expected: false, label: 'beyond radius' },
    ])('returns $expected when player is $label', ({ px, py, radius, expected }) => {
      const item = new WorldItem({ id: 'wi-8', itemId: 'item_blanket', questInstanceId: 1, x: 0, y: 0 });
      expect(item.isPlayerInPickupRange(px, py, radius)).toBe(expected);
    });
  });
});

const SAMPLE_OFFER: QuestOffer = {
  npcId: 'hopper',
  questId: 'quest_hopper_blanket',
  title: "Find Hopper's Blanket",
  timeLimitSeconds: 300,
  rewards: [
    { itemId: 'coin', quantity: 25 },
    { itemId: 'accessory_sleepy_hat', quantity: 1 },
  ],
};

describe('QuestPanel', () => {
  describe('initial state', () => {
    it('is hidden and idle on construction', () => {
      const panel = new QuestPanel();
      expect(panel.isVisible()).toBe(false);
      expect(panel.getState().kind).toBe('idle');
    });
  });

  describe('showOffer', () => {
    it('renders quest offer with title and rewards and becomes visible', () => {
      const panel = new QuestPanel();
      panel.showOffer(SAMPLE_OFFER);
      const state = panel.getState();
      expect(panel.isVisible()).toBe(true);
      expect(state.kind).toBe('offer');
      if (state.kind === 'offer') {
        expect(state.offer.title).toBe("Find Hopper's Blanket");
        expect(state.offer.questId).toBe('quest_hopper_blanket');
        expect(state.offer.rewards).toHaveLength(2);
        expect(state.offer.rewards[0]).toEqual({ itemId: 'coin', quantity: 25 });
      }
    });

    it('does not show already_active message when displaying an offer', () => {
      const panel = new QuestPanel();
      panel.showOffer(SAMPLE_OFFER);
      expect(panel.getDisplayMessage()).toBeNull();
    });
  });

  describe('showAlreadyActive', () => {
    it('shows message, becomes visible, and does not display a quest offer', () => {
      const panel = new QuestPanel();
      panel.showAlreadyActive();
      expect(panel.isVisible()).toBe(true);
      expect(panel.getDisplayMessage()).toBe('You already have an active quest.');
      expect(panel.getState().kind).toBe('already_active');
    });
  });

  describe('acceptOffer', () => {
    it('calls onAccept with quest_id when accepting a displayed offer', () => {
      const onAccept = vi.fn();
      const panel = new QuestPanel({ onAccept });
      panel.showOffer(SAMPLE_OFFER);
      panel.acceptOffer();
      expect(onAccept).toHaveBeenCalledOnce();
      expect(onAccept).toHaveBeenCalledWith('quest_hopper_blanket');
    });

    it('does nothing when not in offer state', () => {
      const onAccept = vi.fn();
      const panel = new QuestPanel({ onAccept });
      panel.acceptOffer();
      expect(onAccept).not.toHaveBeenCalled();
    });
  });

  describe('getCountdownSeconds', () => {
    it('returns null when not in active state', () => {
      const panel = new QuestPanel();
      expect(panel.getCountdownSeconds()).toBeNull();
    });

    it('returns remaining seconds from expires_at', () => {
      const expiresAt = '2026-05-10T12:05:00Z';
      const expiresMs = new Date(expiresAt).getTime();
      const panel = new QuestPanel({ nowMs: () => expiresMs - 120_000 });
      panel.startActive('quest_hopper_blanket', expiresAt);
      expect(panel.getCountdownSeconds()).toBe(120);
    });

    it('returns 0 when the quest has already expired', () => {
      const expiresAt = '2026-05-10T12:05:00Z';
      const expiresMs = new Date(expiresAt).getTime();
      const panel = new QuestPanel({ nowMs: () => expiresMs + 5_000 });
      panel.startActive('quest_hopper_blanket', expiresAt);
      expect(panel.getCountdownSeconds()).toBe(0);
    });

    it('reflects elapsed time when nowMs advances', () => {
      const expiresAt = '2026-05-10T12:05:00Z';
      const expiresMs = new Date(expiresAt).getTime();
      let fakeNow = expiresMs - 300_000;
      const panel = new QuestPanel({ nowMs: () => fakeNow });
      panel.startActive('quest_hopper_blanket', expiresAt);
      expect(panel.getCountdownSeconds()).toBe(300);
      fakeNow = expiresMs - 180_000;
      expect(panel.getCountdownSeconds()).toBe(180);
    });
  });

  describe('showCompleted', () => {
    it('displays completion notification with coins awarded and becomes visible', () => {
      const panel = new QuestPanel();
      panel.showCompleted('quest_hopper_blanket', 25);
      expect(panel.isVisible()).toBe(true);
      expect(panel.getState().kind).toBe('completed');
      expect(panel.getDisplayMessage()).toBe('Quest complete! You earned $25.');
    });
  });

  describe('showFailed', () => {
    it('displays failure notification and becomes visible', () => {
      const panel = new QuestPanel();
      panel.showFailed('quest_hopper_blanket');
      expect(panel.isVisible()).toBe(true);
      expect(panel.getState().kind).toBe('failed');
      expect(panel.getDisplayMessage()).toBe('Quest failed.');
    });
  });

  describe('dismiss', () => {
    it('transitions back to idle from any state', () => {
      const panel = new QuestPanel();
      panel.showOffer(SAMPLE_OFFER);
      panel.dismiss();
      expect(panel.getState().kind).toBe('idle');
    });

    it('is not visible after dismiss', () => {
      const panel = new QuestPanel();
      panel.showAlreadyActive();
      panel.dismiss();
      expect(panel.isVisible()).toBe(false);
    });
  });
});
