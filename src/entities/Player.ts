export interface PlayerSnapshot {
  readonly id: string;
  readonly name: string;
  readonly x: number;
  readonly y: number;
  readonly direction: string;
  readonly characterId: string;
}

export interface PlayerInit {
  id: string;
  name: string;
  x: number;
  y: number;
  direction: string;
  characterId: string;
}

export class Player {
  readonly id: string;
  readonly name: string;
  readonly characterId: string;
  private _x: number;
  private _y: number;
  private _direction: string;

  constructor(init: PlayerInit) {
    this.id = init.id;
    this.name = init.name;
    this.characterId = init.characterId;
    this._x = init.x;
    this._y = init.y;
    this._direction = init.direction;
  }

  get x(): number {
    return this._x;
  }

  get y(): number {
    return this._y;
  }

  get direction(): string {
    return this._direction;
  }

  applyPositionUpdate(x: number, y: number, direction: string): void {
    this._x = x;
    this._y = y;
    this._direction = direction;
  }

  snapshot(): PlayerSnapshot {
    return {
      id: this.id,
      name: this.name,
      x: this._x,
      y: this._y,
      direction: this._direction,
      characterId: this.characterId,
    };
  }
}
