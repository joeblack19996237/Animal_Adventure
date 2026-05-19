export enum WorldItemStatus {
  Spawned = 'spawned',
  PickedUp = 'picked_up',
  Expired = 'expired',
}

export interface WorldItemInit {
  id: string;
  itemId: string;
  questInstanceId: number;
  x: number;
  y: number;
}

export class WorldItem {
  readonly id: string;
  readonly itemId: string;
  readonly questInstanceId: number;
  readonly x: number;
  readonly y: number;
  private _status: WorldItemStatus;

  constructor(init: WorldItemInit) {
    this.id = init.id;
    this.itemId = init.itemId;
    this.questInstanceId = init.questInstanceId;
    this.x = init.x;
    this.y = init.y;
    this._status = WorldItemStatus.Spawned;
  }

  get status(): WorldItemStatus {
    return this._status;
  }

  pickup(): void {
    if (this._status !== WorldItemStatus.Spawned) {
      throw new Error(`Cannot pick up item ${this.id}: status is ${this._status}`);
    }
    this._status = WorldItemStatus.PickedUp;
  }

  expire(): void {
    if (this._status === WorldItemStatus.PickedUp) {
      throw new Error(`Cannot expire item ${this.id}: already picked up`);
    }
    this._status = WorldItemStatus.Expired;
  }

  isPlayerInPickupRange(playerX: number, playerY: number, pickupRadius: number): boolean {
    const dx = playerX - this.x;
    const dy = playerY - this.y;
    return Math.sqrt(dx * dx + dy * dy) <= pickupRadius;
  }
}
