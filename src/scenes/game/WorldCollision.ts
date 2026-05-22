import collisionZonesJson from '../../../config/collision_zones.json';
import npcsJson from '../../../config/npcs.json';

interface BoundsZone {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface RectZone {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface CircleZone {
  id: string;
  x: number;
  y: number;
  radius: number;
}

interface PolygonZone {
  id: string;
  points: [number, number][];
}

interface CollisionConfig {
  bounds: BoundsZone;
  rects: RectZone[];
  circles: CircleZone[];
  polygons: PolygonZone[];
  bridges?: RectZone[];
  locked_regions?: Array<RectZone & { unlock_level: number }>;
}

interface NpcConfig {
  id: string;
  x: number;
  y: number;
}

export interface DynamicBlocker {
  id?: string;
  x: number;
  y: number;
  radius: number;
}

const COLLISION_ZONES = collisionZonesJson as CollisionConfig;
const NPCS = npcsJson as NpcConfig[];
const NPC_BLOCKER_RADIUS = 42;

export const WORLD_BOUNDS = COLLISION_ZONES.bounds;
export const LOCKED_REGIONS = COLLISION_ZONES.locked_regions ?? [];

export function npcCollisionBlockers(): DynamicBlocker[] {
  return NPCS.map((npc) => ({
    id: npc.id,
    x: npc.x,
    y: npc.y,
    radius: NPC_BLOCKER_RADIUS,
  }));
}

export function isMovementBlocked(
  x: number,
  y: number,
  playerRadius = 38,
  dynamicBlockers: readonly DynamicBlocker[] = npcCollisionBlockers(),
): boolean {
  if (isOutsideBounds(x, y, playerRadius, COLLISION_ZONES.bounds)) return true;
  if ((COLLISION_ZONES.bridges ?? []).some((bridge) => circleIntersectsRect(x, y, playerRadius, bridge))) return false;
  if (COLLISION_ZONES.rects.some((rect) => circleIntersectsRect(x, y, playerRadius, rect))) return true;
  if (COLLISION_ZONES.circles.some((circle) => circleIntersectsCircle(x, y, playerRadius, circle))) return true;
  if (COLLISION_ZONES.polygons.some((polygon) => circleIntersectsPolygon(x, y, playerRadius, polygon))) return true;
  return dynamicBlockers.some((blocker) => circleIntersectsCircle(x, y, playerRadius, blocker));
}

export function isPointInLockedRegion(x: number, y: number, playerLevel: number): boolean {
  return LOCKED_REGIONS.some((region) => (
    playerLevel < region.unlock_level &&
    x >= region.x &&
    y >= region.y &&
    x <= region.x + region.width &&
    y <= region.y + region.height
  ));
}

function isOutsideBounds(x: number, y: number, radius: number, bounds: BoundsZone): boolean {
  return (
    x - radius < bounds.x ||
    y - radius < bounds.y ||
    x + radius > bounds.x + bounds.width ||
    y + radius > bounds.y + bounds.height
  );
}

function circleIntersectsRect(x: number, y: number, radius: number, rect: RectZone): boolean {
  const nearestX = clamp(x, rect.x, rect.x + rect.width);
  const nearestY = clamp(y, rect.y, rect.y + rect.height);
  return distanceSquared(x, y, nearestX, nearestY) <= radius * radius;
}

function circleIntersectsCircle(
  x: number,
  y: number,
  radius: number,
  circle: { x: number; y: number; radius: number },
): boolean {
  const combinedRadius = radius + circle.radius;
  return distanceSquared(x, y, circle.x, circle.y) <= combinedRadius * combinedRadius;
}

function circleIntersectsPolygon(x: number, y: number, radius: number, polygon: PolygonZone): boolean {
  if (pointInPolygon(x, y, polygon.points)) return true;
  for (let i = 0; i < polygon.points.length; i++) {
    const [x1, y1] = polygon.points[i];
    const [x2, y2] = polygon.points[(i + 1) % polygon.points.length];
    if (distanceToSegmentSquared(x, y, x1, y1, x2, y2) <= radius * radius) return true;
  }
  return false;
}

function pointInPolygon(x: number, y: number, points: readonly [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i];
    const [xj, yj] = points[j];
    const intersects = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

function distanceToSegmentSquared(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  const dx = x2 - x1;
  const dy = y2 - y1;
  if (dx === 0 && dy === 0) return distanceSquared(px, py, x1, y1);
  const t = clamp(((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy), 0, 1);
  return distanceSquared(px, py, x1 + t * dx, y1 + t * dy);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function distanceSquared(x1: number, y1: number, x2: number, y2: number): number {
  const dx = x2 - x1;
  const dy = y2 - y1;
  return dx * dx + dy * dy;
}
