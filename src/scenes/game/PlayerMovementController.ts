import {
  fillMovementVector,
  type InputState,
  type MutableMovementVector,
} from '../../state/input';

export interface MovementSender {
  sendMove(msg: Record<string, unknown>): void;
}

interface ServerMovementSnapshot {
  readonly x?: unknown;
  readonly y?: unknown;
  readonly direction?: unknown;
}

export class PlayerMovementController {
  private readonly vector: MutableMovementVector = { dx: 0, dy: 0 };
  private playerId = '';
  private x = 0;
  private y = 0;
  private direction = 'down';
  private clientTick = 0;
  private receivedStateSync = false;

  constructor(private readonly speed: number) {}

  setPlayerId(playerId: string): void {
    this.playerId = playerId;
  }

  applyServerSnapshot(snapshot: ServerMovementSnapshot): void {
    if (typeof snapshot.x === 'number') this.x = snapshot.x;
    if (typeof snapshot.y === 'number') this.y = snapshot.y;
    if (typeof snapshot.direction === 'string') this.direction = snapshot.direction;
    this.receivedStateSync = true;
  }

  hasStateSyncReceived(): boolean {
    return this.receivedStateSync;
  }

  getX(): number {
    return this.x;
  }

  getY(): number {
    return this.y;
  }

  tick(deltaMs: number, inputState: InputState, sender: MovementSender | null): void {
    if (sender === null || !this.receivedStateSync) return;

    fillMovementVector(inputState, this.vector);
    if (this.vector.dx === 0 && this.vector.dy === 0) return;

    const magnitude = Math.sqrt(this.vector.dx * this.vector.dx + this.vector.dy * this.vector.dy);
    const dx = magnitude > 1 ? this.vector.dx / magnitude : this.vector.dx;
    const dy = magnitude > 1 ? this.vector.dy / magnitude : this.vector.dy;
    const dt = deltaMs / 1000;

    this.x += dx * this.speed * dt;
    this.y += dy * this.speed * dt;
    this.direction = this.resolveDirection(dx, dy);
    this.clientTick++;

    sender.sendMove({
      type: 'player_move',
      player_id: this.playerId,
      x: this.x,
      y: this.y,
      direction: this.direction,
      client_tick: this.clientTick,
    });
  }

  private resolveDirection(dx: number, dy: number): string {
    if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? 'right' : 'left';
    return dy >= 0 ? 'down' : 'up';
  }
}
