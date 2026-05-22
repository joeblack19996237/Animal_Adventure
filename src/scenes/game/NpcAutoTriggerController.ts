import { findNearestNpc } from './WorldInteraction';

export class NpcAutoTriggerController {
  private activeNpcId: string | null = null;

  tick(playerX: number, playerY: number, canTrigger: boolean, onTrigger: (npcId: string) => void): void {
    const npc = findNearestNpc(playerX, playerY, 96);
    if (npc === null) {
      this.activeNpcId = null;
      return;
    }
    if (!canTrigger || this.activeNpcId === npc.id) return;
    this.activeNpcId = npc.id;
    onTrigger(npc.id);
  }
}
