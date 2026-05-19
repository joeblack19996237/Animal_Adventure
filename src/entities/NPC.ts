export interface NPCInit {
  id: string;
  name: string;
  x: number;
  y: number;
  interactionRadius: number;
}

export class NPC {
  readonly id: string;
  readonly name: string;
  readonly x: number;
  readonly y: number;
  readonly interactionRadius: number;

  constructor(init: NPCInit) {
    this.id = init.id;
    this.name = init.name;
    this.x = init.x;
    this.y = init.y;
    this.interactionRadius = init.interactionRadius;
  }

  isPlayerInRange(playerX: number, playerY: number): boolean {
    const dx = playerX - this.x;
    const dy = playerY - this.y;
    return Math.sqrt(dx * dx + dy * dy) <= this.interactionRadius;
  }
}
