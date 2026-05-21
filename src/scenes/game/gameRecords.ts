export interface QuestRecord {
  quest_instance_id: number;
  npc_id: string;
  quest_id: string;
  status: string;
  expires_at: string | null;
  cooldown_until: string | null;
  progress: { collected: string[] };
  rewards_granted_json: string[];
}

export interface WorldItemRecord {
  id: string;
  item_id: string;
  quest_instance_id: number;
  x: number;
  y: number;
  status: string;
}

export interface InventoryRecord {
  item_id: string;
  quantity: number;
  slot_type: string;
}

export interface ShopBootstrapItem {
  item_id: string;
  price: number;
  unlock_level: number;
}

export interface QuestOffer {
  questId: string;
  npcId: string;
  title: string;
  rewards: unknown[];
}

export function isShopBootstrapItem(v: unknown): v is ShopBootstrapItem {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return false;
  const r = v as Record<string, unknown>;
  return typeof r['item_id'] === 'string' && typeof r['price'] === 'number';
}

export function isItemRecord(v: unknown): v is { id: string; type: string } {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return false;
  const r = v as Record<string, unknown>;
  return typeof r['id'] === 'string' && typeof r['type'] === 'string';
}

export function toQuestRecord(v: unknown): QuestRecord | null {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return null;
  const r = v as Record<string, unknown>;
  if (typeof r['quest_id'] !== 'string' || typeof r['status'] !== 'string') return null;
  const progress = (r['progress'] as Record<string, unknown> | undefined) ?? {};
  return {
    quest_instance_id: typeof r['quest_instance_id'] === 'number' ? r['quest_instance_id'] : 0,
    npc_id: typeof r['npc_id'] === 'string' ? r['npc_id'] : '',
    quest_id: r['quest_id'],
    status: r['status'],
    expires_at: typeof r['expires_at'] === 'string' ? r['expires_at'] : null,
    cooldown_until: typeof r['cooldown_until'] === 'string' ? r['cooldown_until'] : null,
    progress: {
      collected: Array.isArray(progress['collected'])
        ? (progress['collected'] as unknown[]).filter((x): x is string => typeof x === 'string')
        : [],
    },
    rewards_granted_json: Array.isArray(r['rewards_granted_json'])
      ? (r['rewards_granted_json'] as unknown[]).filter((x): x is string => typeof x === 'string')
      : [],
  };
}

export function toWorldItemRecord(v: unknown): WorldItemRecord | null {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return null;
  const r = v as Record<string, unknown>;
  if (typeof r['id'] !== 'string') return null;
  return {
    id: r['id'],
    item_id: typeof r['item_id'] === 'string' ? r['item_id'] : '',
    quest_instance_id: typeof r['quest_instance_id'] === 'number' ? r['quest_instance_id'] : 0,
    x: typeof r['x'] === 'number' ? r['x'] : 0,
    y: typeof r['y'] === 'number' ? r['y'] : 0,
    status: typeof r['status'] === 'string' ? r['status'] : '',
  };
}

export function toInventoryRecord(v: unknown): InventoryRecord | null {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return null;
  const r = v as Record<string, unknown>;
  if (typeof r['item_id'] !== 'string') return null;
  return {
    item_id: r['item_id'],
    quantity: typeof r['quantity'] === 'number' ? r['quantity'] : 1,
    slot_type: typeof r['slot_type'] === 'string' ? r['slot_type'] : 'inventory',
  };
}

export function formatCountdown(remainingMs: number): string {
  const totalSecs = Math.max(0, Math.floor(remainingMs / 1000));
  const mins = Math.floor(totalSecs / 60);
  const secs = totalSecs % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}
