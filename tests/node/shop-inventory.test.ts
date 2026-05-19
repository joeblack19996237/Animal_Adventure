import { describe, it, expect, vi } from 'vitest';
import { ShopPanel } from '../../src/ui/ShopPanel';
import type { ShopItem } from '../../src/ui/ShopPanel';
import { InventoryPanel } from '../../src/ui/InventoryPanel';
import type { InventoryEntry } from '../../src/ui/InventoryPanel';

const SHOP_ITEMS: ShopItem[] = [{ itemId: 'potion_l0', price: 10, unlockLevel: 0 }];

const POTION_ENTRY: InventoryEntry = { itemId: 'potion_l0', quantity: 2, slotType: 'equipment' };
const BLANKET_ENTRY: InventoryEntry = { itemId: 'item_blanket', quantity: 1, slotType: 'inventory' };

describe('ShopPanel', () => {
  describe('initial state', () => {
    it('is hidden on construction', () => {
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
      expect(panel.isVisible()).toBe(false);
    });

    it('exposes configured shop items', () => {
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
      const items = panel.getItems();
      expect(items).toHaveLength(1);
      expect(items[0]).toEqual({ itemId: 'potion_l0', price: 10, unlockLevel: 0 });
    });
  });

  describe('show / hide', () => {
    it('becomes visible after show and hidden after hide', () => {
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
      panel.show(25);
      expect(panel.isVisible()).toBe(true);
      panel.hide();
      expect(panel.isVisible()).toBe(false);
    });

    it('stores the coins balance passed to show', () => {
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
      panel.show(15);
      expect(panel.getCoinsBalance()).toBe(15);
    });
  });

  describe('canBuyItem', () => {
    it('returns true when coins balance >= item price', () => {
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
      panel.show(10);
      expect(panel.canBuyItem('potion_l0')).toBe(true);
    });

    it('returns false when coins balance < item price', () => {
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
      panel.show(9);
      expect(panel.canBuyItem('potion_l0')).toBe(false);
    });

    it('returns false for unknown item id', () => {
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
      panel.show(100);
      expect(panel.canBuyItem('unknown_item')).toBe(false);
    });
  });

  describe('buyItem', () => {
    it('calls onBuy with item id when affordable', () => {
      const onBuy = vi.fn();
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy });
      panel.show(25);
      panel.buyItem('potion_l0');
      expect(onBuy).toHaveBeenCalledOnce();
      expect(onBuy).toHaveBeenCalledWith('potion_l0');
    });

    it('does not call onBuy when insufficient coins', () => {
      const onBuy = vi.fn();
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy });
      panel.show(5);
      panel.buyItem('potion_l0');
      expect(onBuy).not.toHaveBeenCalled();
    });

    it('does not call onBuy for unknown item', () => {
      const onBuy = vi.fn();
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy });
      panel.show(100);
      panel.buyItem('unknown_item');
      expect(onBuy).not.toHaveBeenCalled();
    });
  });

  describe('applyShopResult', () => {
    it('updates coins balance after successful purchase', () => {
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
      panel.show(25);
      panel.applyShopResult(true, 15);
      expect(panel.getCoinsBalance()).toBe(15);
    });

    it('updates coins balance even on failed purchase response', () => {
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
      panel.show(25);
      panel.applyShopResult(false, 25);
      expect(panel.getCoinsBalance()).toBe(25);
    });

    it('canBuyItem reflects updated balance after applyShopResult', () => {
      const panel = new ShopPanel({ items: SHOP_ITEMS, onBuy: vi.fn() });
      panel.show(25);
      expect(panel.canBuyItem('potion_l0')).toBe(true);
      panel.applyShopResult(true, 5);
      expect(panel.canBuyItem('potion_l0')).toBe(false);
    });
  });
});

describe('InventoryPanel', () => {
  const CONSUMABLE_IDS = ['potion_l0'];

  describe('initial state', () => {
    it('is hidden on construction', () => {
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
      expect(panel.isVisible()).toBe(false);
    });

    it('returns empty item list initially', () => {
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
      expect(panel.getItems()).toHaveLength(0);
    });
  });

  describe('show / hide', () => {
    it('becomes visible after show and hidden after hide', () => {
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
      panel.show();
      expect(panel.isVisible()).toBe(true);
      panel.hide();
      expect(panel.isVisible()).toBe(false);
    });
  });

  describe('applyInventoryUpdate', () => {
    it('merges inventory and equipment entries', () => {
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
      panel.applyInventoryUpdate([BLANKET_ENTRY], [POTION_ENTRY]);
      const items = panel.getItems();
      expect(items).toHaveLength(2);
      expect(items.find((i) => i.itemId === 'item_blanket')).toBeDefined();
      expect(items.find((i) => i.itemId === 'potion_l0')).toBeDefined();
    });

    it('renders item with correct quantity', () => {
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
      panel.applyInventoryUpdate([], [POTION_ENTRY]);
      const potion = panel.getItems().find((i) => i.itemId === 'potion_l0');
      expect(potion?.quantity).toBe(2);
    });

    it('replaces previous items on each update', () => {
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
      panel.applyInventoryUpdate([BLANKET_ENTRY], []);
      panel.applyInventoryUpdate([], [POTION_ENTRY]);
      const items = panel.getItems();
      expect(items).toHaveLength(1);
      expect(items[0].itemId).toBe('potion_l0');
    });
  });

  describe('canUseItem', () => {
    it('returns true for a consumable item with quantity > 0', () => {
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
      panel.applyInventoryUpdate([], [POTION_ENTRY]);
      expect(panel.canUseItem('potion_l0')).toBe(true);
    });

    it('returns false for a non-consumable item', () => {
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
      panel.applyInventoryUpdate([BLANKET_ENTRY], []);
      expect(panel.canUseItem('item_blanket')).toBe(false);
    });

    it('returns false for item not in inventory', () => {
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
      expect(panel.canUseItem('potion_l0')).toBe(false);
    });

    it('returns false for item with quantity 0', () => {
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse: vi.fn() });
      panel.applyInventoryUpdate([], [{ itemId: 'potion_l0', quantity: 0, slotType: 'equipment' }]);
      expect(panel.canUseItem('potion_l0')).toBe(false);
    });
  });

  describe('useItem', () => {
    it('calls onUse with item id for consumable with quantity > 0', () => {
      const onUse = vi.fn();
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse });
      panel.applyInventoryUpdate([], [POTION_ENTRY]);
      panel.useItem('potion_l0');
      expect(onUse).toHaveBeenCalledOnce();
      expect(onUse).toHaveBeenCalledWith('potion_l0');
    });

    it('does not call onUse for non-consumable item', () => {
      const onUse = vi.fn();
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse });
      panel.applyInventoryUpdate([BLANKET_ENTRY], []);
      panel.useItem('item_blanket');
      expect(onUse).not.toHaveBeenCalled();
    });

    it('does not call onUse for item not in inventory', () => {
      const onUse = vi.fn();
      const panel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse });
      panel.useItem('potion_l0');
      expect(onUse).not.toHaveBeenCalled();
    });
  });

  describe('Potion purchase/use UI flow from server messages', () => {
    it('shop panel reflects new balance after shop_result; inventory panel reflects new items after inventory_updated', () => {
      const onBuy = vi.fn();
      const onUse = vi.fn();
      const shopPanel = new ShopPanel({ items: SHOP_ITEMS, onBuy });
      const inventoryPanel = new InventoryPanel({ consumableIds: CONSUMABLE_IDS, onUse });

      shopPanel.show(25);
      expect(shopPanel.canBuyItem('potion_l0')).toBe(true);

      shopPanel.buyItem('potion_l0');
      expect(onBuy).toHaveBeenCalledWith('potion_l0');

      shopPanel.applyShopResult(true, 15);
      expect(shopPanel.getCoinsBalance()).toBe(15);

      inventoryPanel.applyInventoryUpdate([], [{ itemId: 'potion_l0', quantity: 1, slotType: 'equipment' }]);
      expect(inventoryPanel.canUseItem('potion_l0')).toBe(true);

      inventoryPanel.useItem('potion_l0');
      expect(onUse).toHaveBeenCalledWith('potion_l0');

      inventoryPanel.applyInventoryUpdate([], []);
      expect(inventoryPanel.canUseItem('potion_l0')).toBe(false);
    });
  });
});
