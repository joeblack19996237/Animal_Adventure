export interface ShopItem {
  readonly itemId: string;
  readonly price: number;
  readonly unlockLevel: number;
}

export interface ShopPanelOptions {
  items: ShopItem[];
  onBuy: (itemId: string) => void;
}

export class ShopPanel {
  private readonly items: readonly ShopItem[];
  private readonly onBuy: (itemId: string) => void;
  private visible = false;
  private coinsBalance = 0;

  constructor(options: ShopPanelOptions) {
    this.items = [...options.items];
    this.onBuy = options.onBuy;
  }

  isVisible(): boolean {
    return this.visible;
  }

  show(coinsBalance: number): void {
    this.coinsBalance = coinsBalance;
    this.visible = true;
  }

  hide(): void {
    this.visible = false;
  }

  getItems(): readonly ShopItem[] {
    return this.items;
  }

  getCoinsBalance(): number {
    return this.coinsBalance;
  }

  canBuyItem(itemId: string): boolean {
    const item = this.items.find((i) => i.itemId === itemId);
    if (item === undefined) return false;
    return this.coinsBalance >= item.price;
  }

  buyItem(itemId: string): void {
    if (!this.canBuyItem(itemId)) return;
    this.onBuy(itemId);
  }

  applyShopResult(success: boolean, coinsBalance: number): void {
    if (!success) return;
    this.coinsBalance = coinsBalance;
  }
}
