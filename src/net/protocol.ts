function isObj(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

// --- Client-to-server message interfaces ---

export interface PlayerMoveMsg {
  type: 'player_move';
  player_id: string;
  x: number;
  y: number;
  direction: string;
  client_tick: number;
}

export interface NpcInteractRequestMsg {
  type: 'npc_interact_request';
  player_id: string;
  npc_id: string;
}

export interface QuestAcceptMsg {
  type: 'quest_accept';
  player_id: string;
  quest_id: string;
}

export interface ItemPickupRequestMsg {
  type: 'item_pickup_request';
  player_id: string;
  item_instance_id: string;
}

export interface QuestTurnInMsg {
  type: 'quest_turn_in';
  player_id: string;
  quest_id: string;
}

export interface ShopBuyMsg {
  type: 'shop_buy';
  player_id: string;
  item_id: string;
}

export interface UseItemMsg {
  type: 'use_item';
  player_id: string;
  item_id: string;
}

export interface PresetChatMsg {
  type: 'preset_chat';
  player_id: string;
  phrase_id: string;
}

export interface PingMsg {
  type: 'ping';
  client_time: number;
}

// --- Server-to-client message interfaces ---

export interface StateSyncMsg {
  type: 'state_sync';
  server_time: string;
  player: Record<string, unknown>;
  progress: Record<string, unknown>;
  inventory: unknown[];
  equipment: unknown[];
  quests: unknown[];
  online_players: Record<string, unknown>;
  world_items: unknown[];
}

export interface StateUpdateMsg {
  type: 'state_update';
  tick: number;
  players: Record<string, unknown>;
}

export interface PlayerJoinedMsg {
  type: 'player_joined';
  player: {
    id: string;
    name: string;
    x: number;
    y: number;
  };
}

export interface PlayerLeftMsg {
  type: 'player_left';
  player_id: string;
}

export interface QuestOfferMsg {
  type: 'quest_offer';
  npc_id: string;
  quest_id: string;
  title: string;
  time_limit_seconds: number;
  rewards: unknown[];
}

export interface QuestStartedMsg {
  type: 'quest_started';
  quest_id: string;
  expires_at: string;
  world_items: unknown[];
}

export interface QuestProgressMsg {
  type: 'quest_progress';
  quest_id: string;
  collected: unknown[];
}

export interface QuestCompletedMsg {
  type: 'quest_completed';
  quest_id: string;
  coins_awarded: number;
  coins_balance: number;
  rewards: unknown[];
  rewards_granted_json: unknown[];
}

export interface QuestFailedMsg {
  type: 'quest_failed';
  quest_id: string;
  cooldown_until: string;
}

export interface InventoryUpdatedMsg {
  type: 'inventory_updated';
  inventory: unknown[];
  equipment: unknown[];
}

export interface ShopResultMsg {
  type: 'shop_result';
  success: boolean;
  item_id: string;
  coins_spent: number;
  coins_balance: number;
}

export interface LevelUpMsg {
  type: 'level_up';
  level: number;
  unlocked_regions: unknown[];
}

export interface ChatMessageMsg {
  type: 'chat_message';
  player_id: string;
  phrase_id: string;
  message: string;
}

export interface ErrorMsg {
  type: 'error';
  code: string;
  message: string;
}

export interface PongMsg {
  type: 'pong';
  server_time: string;
}

// --- REST response interface ---

export interface LoginResponse {
  player_id: string;
  name: string;
  normalized_name: string;
  character_id: string | null;
}

// --- Type guards: client-to-server ---

export function isPlayerMoveMsg(v: unknown): v is PlayerMoveMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'player_move' &&
    typeof v['player_id'] === 'string' &&
    typeof v['x'] === 'number' &&
    typeof v['y'] === 'number' &&
    typeof v['direction'] === 'string' &&
    typeof v['client_tick'] === 'number'
  );
}

export function isNpcInteractRequestMsg(v: unknown): v is NpcInteractRequestMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'npc_interact_request' &&
    typeof v['player_id'] === 'string' &&
    typeof v['npc_id'] === 'string'
  );
}

export function isQuestAcceptMsg(v: unknown): v is QuestAcceptMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'quest_accept' &&
    typeof v['player_id'] === 'string' &&
    typeof v['quest_id'] === 'string'
  );
}

export function isItemPickupRequestMsg(v: unknown): v is ItemPickupRequestMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'item_pickup_request' &&
    typeof v['player_id'] === 'string' &&
    typeof v['item_instance_id'] === 'string'
  );
}

export function isQuestTurnInMsg(v: unknown): v is QuestTurnInMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'quest_turn_in' &&
    typeof v['player_id'] === 'string' &&
    typeof v['quest_id'] === 'string'
  );
}

export function isShopBuyMsg(v: unknown): v is ShopBuyMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'shop_buy' &&
    typeof v['player_id'] === 'string' &&
    typeof v['item_id'] === 'string'
  );
}

export function isUseItemMsg(v: unknown): v is UseItemMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'use_item' &&
    typeof v['player_id'] === 'string' &&
    typeof v['item_id'] === 'string'
  );
}

export function isPresetChatMsg(v: unknown): v is PresetChatMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'preset_chat' &&
    typeof v['player_id'] === 'string' &&
    typeof v['phrase_id'] === 'string'
  );
}

export function isPingMsg(v: unknown): v is PingMsg {
  if (!isObj(v)) return false;
  return v['type'] === 'ping' && typeof v['client_time'] === 'number';
}

// --- Type guards: server-to-client ---

export function isStateSyncMsg(v: unknown): v is StateSyncMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'state_sync' &&
    typeof v['server_time'] === 'string' &&
    isObj(v['player']) &&
    isObj(v['progress']) &&
    Array.isArray(v['inventory']) &&
    Array.isArray(v['equipment']) &&
    Array.isArray(v['quests']) &&
    isObj(v['online_players']) &&
    Array.isArray(v['world_items'])
  );
}

export function isStateUpdateMsg(v: unknown): v is StateUpdateMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'state_update' &&
    typeof v['tick'] === 'number' &&
    isObj(v['players'])
  );
}

export function isPlayerJoinedMsg(v: unknown): v is PlayerJoinedMsg {
  if (!isObj(v)) return false;
  if (v['type'] !== 'player_joined') return false;
  const player = v['player'];
  if (!isObj(player)) return false;
  return typeof player['id'] === 'string' && typeof player['name'] === 'string';
}

export function isPlayerLeftMsg(v: unknown): v is PlayerLeftMsg {
  if (!isObj(v)) return false;
  return v['type'] === 'player_left' && typeof v['player_id'] === 'string';
}

export function isQuestOfferMsg(v: unknown): v is QuestOfferMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'quest_offer' &&
    typeof v['npc_id'] === 'string' &&
    typeof v['quest_id'] === 'string' &&
    typeof v['title'] === 'string' &&
    typeof v['time_limit_seconds'] === 'number' &&
    Array.isArray(v['rewards'])
  );
}

export function isQuestStartedMsg(v: unknown): v is QuestStartedMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'quest_started' &&
    typeof v['quest_id'] === 'string' &&
    typeof v['expires_at'] === 'string' &&
    Array.isArray(v['world_items'])
  );
}

export function isQuestProgressMsg(v: unknown): v is QuestProgressMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'quest_progress' &&
    typeof v['quest_id'] === 'string' &&
    Array.isArray(v['collected'])
  );
}

export function isQuestCompletedMsg(v: unknown): v is QuestCompletedMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'quest_completed' &&
    typeof v['quest_id'] === 'string' &&
    typeof v['coins_awarded'] === 'number' &&
    typeof v['coins_balance'] === 'number' &&
    Array.isArray(v['rewards']) &&
    Array.isArray(v['rewards_granted_json'])
  );
}

export function isQuestFailedMsg(v: unknown): v is QuestFailedMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'quest_failed' &&
    typeof v['quest_id'] === 'string' &&
    typeof v['cooldown_until'] === 'string'
  );
}

export function isInventoryUpdatedMsg(v: unknown): v is InventoryUpdatedMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'inventory_updated' &&
    Array.isArray(v['inventory']) &&
    Array.isArray(v['equipment'])
  );
}

export function isShopResultMsg(v: unknown): v is ShopResultMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'shop_result' &&
    typeof v['success'] === 'boolean' &&
    typeof v['item_id'] === 'string' &&
    typeof v['coins_spent'] === 'number' &&
    typeof v['coins_balance'] === 'number'
  );
}

export function isLevelUpMsg(v: unknown): v is LevelUpMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'level_up' &&
    typeof v['level'] === 'number' &&
    Array.isArray(v['unlocked_regions'])
  );
}

export function isChatMessageMsg(v: unknown): v is ChatMessageMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'chat_message' &&
    typeof v['player_id'] === 'string' &&
    typeof v['phrase_id'] === 'string' &&
    typeof v['message'] === 'string'
  );
}

export function isErrorMsg(v: unknown): v is ErrorMsg {
  if (!isObj(v)) return false;
  return (
    v['type'] === 'error' &&
    typeof v['code'] === 'string' &&
    typeof v['message'] === 'string'
  );
}

export function isPongMsg(v: unknown): v is PongMsg {
  if (!isObj(v)) return false;
  return v['type'] === 'pong' && typeof v['server_time'] === 'string';
}

// --- REST type guards ---

export function isLoginResponse(v: unknown): v is LoginResponse {
  if (!isObj(v)) return false;
  return (
    typeof v['player_id'] === 'string' &&
    typeof v['name'] === 'string' &&
    typeof v['normalized_name'] === 'string' &&
    (typeof v['character_id'] === 'string' || v['character_id'] === null)
  );
}

// --- Parse functions ---

type ClientMessage =
  | PlayerMoveMsg
  | NpcInteractRequestMsg
  | QuestAcceptMsg
  | ItemPickupRequestMsg
  | QuestTurnInMsg
  | ShopBuyMsg
  | UseItemMsg
  | PresetChatMsg
  | PingMsg;

type ServerMessage =
  | StateSyncMsg
  | StateUpdateMsg
  | PlayerJoinedMsg
  | PlayerLeftMsg
  | QuestOfferMsg
  | QuestStartedMsg
  | QuestProgressMsg
  | QuestCompletedMsg
  | QuestFailedMsg
  | InventoryUpdatedMsg
  | ShopResultMsg
  | LevelUpMsg
  | ChatMessageMsg
  | ErrorMsg
  | PongMsg;

export function parseClientMessage(raw: string): ClientMessage | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isObj(parsed)) return null;
  if (isPlayerMoveMsg(parsed)) return parsed;
  if (isNpcInteractRequestMsg(parsed)) return parsed;
  if (isQuestAcceptMsg(parsed)) return parsed;
  if (isItemPickupRequestMsg(parsed)) return parsed;
  if (isQuestTurnInMsg(parsed)) return parsed;
  if (isShopBuyMsg(parsed)) return parsed;
  if (isUseItemMsg(parsed)) return parsed;
  if (isPresetChatMsg(parsed)) return parsed;
  if (isPingMsg(parsed)) return parsed;
  return null;
}

export function parseServerMessage(raw: string): ServerMessage | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isObj(parsed)) return null;
  if (isStateSyncMsg(parsed)) return parsed;
  if (isStateUpdateMsg(parsed)) return parsed;
  if (isPlayerJoinedMsg(parsed)) return parsed;
  if (isPlayerLeftMsg(parsed)) return parsed;
  if (isQuestOfferMsg(parsed)) return parsed;
  if (isQuestStartedMsg(parsed)) return parsed;
  if (isQuestProgressMsg(parsed)) return parsed;
  if (isQuestCompletedMsg(parsed)) return parsed;
  if (isQuestFailedMsg(parsed)) return parsed;
  if (isInventoryUpdatedMsg(parsed)) return parsed;
  if (isShopResultMsg(parsed)) return parsed;
  if (isLevelUpMsg(parsed)) return parsed;
  if (isChatMessageMsg(parsed)) return parsed;
  if (isErrorMsg(parsed)) return parsed;
  if (isPongMsg(parsed)) return parsed;
  return null;
}
