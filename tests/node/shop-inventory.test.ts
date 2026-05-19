import { describe, it, expect, vi } from 'vitest';
import { ShopPanel } from '../../src/ui/ShopPanel';
import type { ShopItem } from '../../src/ui/ShopPanel';
import { InventoryPanel } from '../../src/ui/InventoryPanel';
import type { InventoryEntry } from '../../src/ui/InventoryPanel';
import { ProgressionState } from '../../src/state/ProgressionState';

const SHOP_ITEMS: ShopItem[] = [{ itemId: 'potion_l0', price: 10, unlockLevel: 0 }];
const CONSUMABLE_IDS = ['potion_l0'];
const POTION_ENTRY: InventoryEntry = { itemId: 'potion_l0', quantity: 1, slotType: 'equipment' };
const BLANKET_ENTRY: InventoryEntry = { itemId: 'item_blanket', quantity: 1, slotType: 'inventory' };

describe('ShopPanel', () => {
  it('is hidden on construction and exposes configured items', () => {
    const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
    expect(panel.isVisible()).toBe(false);
    expect(panel.getItems()).toEqual(SHOP_ITEMS);
  });

  it('becomes visible after show storing balance, hidden after hide', () => {
    const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
    panel.show(25);
    expect(panel.isVisible()).toBe(true);
    expect(panel.getCoinsBalance()).toBe(25);
    panel.hide();
    expect(panel.isVisible()).toBe(false);
  });

  it('canBuyItem returns true when balance >= price, false otherwise', () => {
    const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
    panel.show(10);
    expect(panel.canBuyItem('potion_l0')).toBe(true);
    panel.show(9);
    expect(panel.canBuyItem('potion_l0')).toBe(false);
    expect(panel.canBuyItem('unknown_item')).toBe(false);
  });

  it('buyItem calls onBuy when affordable, skips when insufficient', () => {
    const onBuy = vi.fn();
    const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy });
    panel.show(25);
    panel.buyItem('potion_l0');
    expect(onBuy).toHaveBeenCalledWith('potion_l0');
    panel.show(5);
    panel.buyItem('potion_l0');
    expect(onBuy).toHaveBeenCalledTimes(1);
  });

  it('applyShopResult updates balance and canBuyItem reflects new balance', () => {
    const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
    panel.show(25);
    panel.applyShopResult(true, 15);
    expect(panel.getCoinsBalance()).toBe(15);
    expect(panel.canBuyItem('potion_l0')).toBe(true);
    panel.applyShopResult(true, 5);
    expect(panel.canBuyItem('potion_l0')).toBe(false);
  });
});

describe('InventoryPanel', () => {
  it('is hidden on construction with empty items', () => {
    const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
    expect(panel.isVisible()).toBe(false);
    expect(panel.getItems()).toHaveLength(0);
  });

  it('becomes visible after show and hidden after hide', () => {
    const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
    panel.show();
    expect(panel.isVisible()).toBe(true);
    panel.hide();
    expect(panel.isVisible()).toBe(false);
  });

  it('applyInventoryUpdate merges inventory and equipment, replaces on subsequent call', () => {
    const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
    panel.applyInventoryUpdate([BLANKET_ENTRY], [POTION_ENTRY]);
    expect(panel.getItems()).toHaveLength(2);
    panel.applyInventoryUpdate([], [POTION_ENTRY]);
    expect(panel.getItems()).toHaveLength(1);
    expect(panel.getItems()[0].itemId).toBe('potion_l0');
  });

  it('canUseItem true for consumable with quantity > 0, false for non-consumable or empty', () => {
    const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
    panel.applyInventoryUpdate([BLANKET_ENTRY], [POTION_ENTRY]);
    expect(panel.canUseItem('potion_l0')).toBe(true);
    expect(panel.canUseItem('item_blanket')).toBe(false);
    panel.applyInventoryUpdate([], [{ itemId: 'potion_l0', quantity: 0, slotType: 'equipment' }]);
    expect(panel.canUseItem('potion_l0')).toBe(false);
  });

  it('useItem calls onUse for consumable, skips for non-consumable', () => {
    const onUse = vi.fn();
    const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse });
    panel.applyInventoryUpdate([BLANKET_ENTRY], [POTION_ENTRY]);
    panel.useItem('item_blanket');
    expect(onUse).not.toHaveBeenCalled();
    panel.useItem('potion_l0');
    expect(onUse).toHaveBeenCalledWith('potion_l0');
  });
});

describe('ProgressionState', () => {
  it('initializes from state_sync and exposes accessors', () => {
    const state = new ProgressionState();
    state.applyStateSync({
      used_potion_count: 1,
      unique_completed_quest_ids: ['quest_hopper_blanket'],
      level: 0,
      unlocked_regions: ['spawn'],
    });
    expect(state.getUsedPotionCount()).toBe(1);
    expect(state.getUniqueCompletedQuestIds()).toHaveLength(1);
    expect(state.getLevel()).toBe(0);
  });

  it('applyPotionUsed increments used_potion_count each call', () => {
    const state = new ProgressionState();
    state.applyStateSync({ used_potion_count: 0, unique_completed_quest_ids: [], level: 0, unlocked_regions: ['spawn'] });
    state.applyPotionUsed();
    state.applyPotionUsed();
    expect(state.getUsedPotionCount()).toBe(2);
  });

  it.each<[number, string[], boolean]>([
    [0, [], false],
    [2, ['q1'], false],
    [1, ['q1', 'q2'], false],
    [2, ['q1', 'q2'], true],
  ])('meetsL3Conditions(%i potions, %i quests) → %s', (potions, quests, expected) => {
    const state = new ProgressionState();
    state.applyStateSync({ used_potion_count: potions, unique_completed_quest_ids: quests, level: 0, unlocked_regions: ['spawn'] });
    expect(state.meetsL3Conditions()).toBe(expected);
  });

  it('applyLevelUp sets level and unlocked_regions from level_up message', () => {
    const state = new ProgressionState();
    state.applyStateSync({ used_potion_count: 0, unique_completed_quest_ids: [], level: 0, unlocked_regions: ['spawn'] });
    state.applyLevelUp(3, ['spawn', 'playground']);
    expect(state.getLevel()).toBe(3);
    expect(state.getUnlockedRegions()).toContain('playground');
  });
});

describe('Full Potion purchase and use integration flow', () => {
  it('shop_buy → shop_result → inventory_updated → use_item × 2 → level_up triggers at L3', () => {
    const onBuy = vi.fn();
    const onUse = vi.fn();
    const shopPanel = new ShopPanel({ items: SHOP_ITEMS, onBuy });
    const inventoryPanel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse });
    const progression = new ProgressionState();

    progression.applyStateSync({
      used_potion_count: 0,
      unique_completed_quest_ids: ['quest_hopper_blanket', 'quest_copper_bagpipe'],
      level: 0,
      unlocked_regions: ['spawn'],
    });
    expect(progression.meetsL3Conditions()).toBe(false);

    // First Potion: shop_buy → shop_result → inventory_updated → use_item
    shopPanel.show(25);
    shopPanel.buyItem('potion_l0');
    expect(onBuy).toHaveBeenCalledWith('potion_l0');
    shopPanel.applyShopResult(true, 15);
    expect(shopPanel.getCoinsBalance()).toBe(15);
    inventoryPanel.applyInventoryUpdate([], [{ itemId: 'potion_l0', quantity: 1, slotType: 'equipment' }]);
    expect(inventoryPanel.canUseItem('potion_l0')).toBe(true);
    inventoryPanel.useItem('potion_l0');
    expect(onUse).toHaveBeenCalledWith('potion_l0');
    inventoryPanel.applyInventoryUpdate([], []);
    progression.applyPotionUsed();
    expect(progression.getUsedPotionCount()).toBe(1);
    expect(progression.meetsL3Conditions()).toBe(false);

    // Second Potion: same flow
    shopPanel.show(15);
    shopPanel.buyItem('potion_l0');
    shopPanel.applyShopResult(true, 5);
    inventoryPanel.applyInventoryUpdate([], [{ itemId: 'potion_l0', quantity: 1, slotType: 'equipment' }]);
    inventoryPanel.useItem('potion_l0');
    inventoryPanel.applyInventoryUpdate([], []);
    progression.applyPotionUsed();
    expect(progression.getUsedPotionCount()).toBe(2);
    expect(progression.meetsL3Conditions()).toBe(true);

    // level_up received from server
    progression.applyLevelUp(3, ['spawn', 'playground']);
    expect(progression.getLevel()).toBe(3);
    expect(progression.getUnlockedRegions()).toContain('playground');
  });
});
