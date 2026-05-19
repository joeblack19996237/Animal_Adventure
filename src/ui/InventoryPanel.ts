export interface InventoryEntry {
  readonly itemId: string;
  readonly quantity: number;
  readonly slotType: 'inventory' | 'equipment';
}

export interface InventoryPanelOptions {
  consumableIds: string[];
  onUse: (itemId: string) => void;
}

export class InventoryPanel {
  private readonly consumableIds: ReadonlySet<string>;
  private readonly onUse: (itemId: string) => void;
  private visible = false;
  private items: InventoryEntry[] = [];

  constructor(options: InventoryPanelOptions) {
    this.consumableIds = new Set(options.consumableIds);
    this.onUse = options.onUse;
  }

  isVisible(): boolean {
    return this.visible;
  }

  show(): void {
    this.visible = true;
  }

  hide(): void {
    this.visible = false;
  }

  getItems(): readonly InventoryEntry[] {
    return this.items;
  }

  applyInventoryUpdate(inventory: InventoryEntry[], equipment: InventoryEntry[]): void {
    this.items = [...inventory, ...equipment];
  }

  canUseItem(itemId: string): boolean {
    if (!this.consumableIds.has(itemId)) return false;
    const entry = this.items.find((i) => i.itemId === itemId);
    if (entry === undefined) return false;
    return entry.quantity > 0;
  }

  useItem(itemId: string): void {
    if (!this.canUseItem(itemId)) return;
    this.onUse(itemId);
  }
}
