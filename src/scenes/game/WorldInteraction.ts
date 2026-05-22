import npcsJson from '../../../config/npcs.json';
import type { WorldItemRecord } from './gameRecords';

export interface NpcInteractionTarget {
  id: string;
  x: number;
  y: number;
  interaction_radius: number;
}

const NPCS = npcsJson as NpcInteractionTarget[];

function distance(aX: number, aY: number, bX: number, bY: number): number {
  return Math.hypot(aX - bX, aY - bY);
}

export function findNearestNpc(
  playerX: number,
  playerY: number,
  interactionRadiusOverride?: number,
): NpcInteractionTarget | null {
  let best: NpcInteractionTarget | null = null;
  let bestDistance = Infinity;
  for (const npc of NPCS) {
    const d = distance(playerX, playerY, npc.x, npc.y);
    const radius = interactionRadiusOverride ?? npc.interaction_radius;
    if (d <= radius && d < bestDistance) {
      best = npc;
      bestDistance = d;
    }
  }
  return best;
}

export function findNearestWorldItem(
  items: readonly WorldItemRecord[],
  playerX: number,
  playerY: number,
  pickupRadius = 180,
): WorldItemRecord | null {
  let best: WorldItemRecord | null = null;
  let bestDistance = Infinity;
  for (const item of items) {
    const d = distance(playerX, playerY, item.x, item.y);
    if (d <= pickupRadius && d < bestDistance) {
      best = item;
      bestDistance = d;
    }
  }
  return best;
}
