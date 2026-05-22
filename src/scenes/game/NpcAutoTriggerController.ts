import { findNearestNpc, type NpcInteractionTarget } from './WorldInteraction';

export class NpcAutoTriggerController {
  private activeNpcId: string | null = null;

  tick(
    playerX: number,
    playerY: number,
    canTrigger: boolean,
    onTrigger: (npcId: string) => void,
    onLeave: () => void = () => undefined,
  ): NpcInteractionTarget | null {
    const npc = findNearestNpc(playerX, playerY, 96);
    if (npc === null) {
      if (this.activeNpcId !== null) {
        this.activeNpcId = null;
        onLeave();
      }
      return null;
    }
    if (!canTrigger || this.activeNpcId === npc.id) return npc;
    this.activeNpcId = npc.id;
    onTrigger(npc.id);
    return npc;
  }

  reset(): void {
    this.activeNpcId = null;
  }
}
