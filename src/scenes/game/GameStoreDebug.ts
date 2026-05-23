export interface GameStoreSnapshot {
  ready: boolean;
  stateSyncReceived: boolean;
  wsOpen: boolean;
  quests: unknown[];
  worldItems: unknown[];
  inventory: unknown[];
  equipment: unknown[];
  player: { coins: number; level: number; x: number; y: number; direction: string };
}

const DEBUG_STORE_KEY = '__gameStore';

export function publishGameStore(snapshot: GameStoreSnapshot): void {
  (window as unknown as Record<string, unknown>)[DEBUG_STORE_KEY] = snapshot;
}
