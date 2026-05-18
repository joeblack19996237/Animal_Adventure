import { describe, it, expect } from 'vitest';
import {
  isPlayerMoveMsg,
  isNpcInteractRequestMsg,
  isQuestAcceptMsg,
  isItemPickupRequestMsg,
  isQuestTurnInMsg,
  isShopBuyMsg,
  isUseItemMsg,
  isPresetChatMsg,
  isPingMsg,
  parseClientMessage,
  isStateSyncMsg,
  isStateUpdateMsg,
  isPlayerJoinedMsg,
  isPlayerLeftMsg,
  isQuestOfferMsg,
  isQuestStartedMsg,
  isQuestProgressMsg,
  isQuestCompletedMsg,
  isQuestFailedMsg,
  isInventoryUpdatedMsg,
  isShopResultMsg,
  isLevelUpMsg,
  isChatMessageMsg,
  isErrorMsg,
  isPongMsg,
  parseServerMessage,
  isLoginResponse,
} from '../../src/net/protocol';

describe('protocol_type_guards', () => {
  describe('client-to-server WS messages', () => {
    describe('player_move', () => {
      it('accepts valid player_move message', () => {
        const msg = { type: 'player_move', player_id: 'p1', x: 2715, y: 3620, direction: 'down', client_tick: 12 };
        expect(isPlayerMoveMsg(msg)).toBe(true);
      });

      it('rejects message missing type field', () => {
        const msg = { player_id: 'p1', x: 2715, y: 3620, direction: 'down', client_tick: 12 };
        expect(isPlayerMoveMsg(msg)).toBe(false);
      });

      it('rejects wrong type discriminant', () => {
        const msg = { type: 'state_update', player_id: 'p1', x: 2715, y: 3620, direction: 'down', client_tick: 12 };
        expect(isPlayerMoveMsg(msg)).toBe(false);
      });

      it('rejects missing x coordinate', () => {
        const msg = { type: 'player_move', player_id: 'p1', y: 3620, direction: 'down', client_tick: 12 };
        expect(isPlayerMoveMsg(msg)).toBe(false);
      });

      it('rejects non-numeric x coordinate', () => {
        const msg = { type: 'player_move', player_id: 'p1', x: '2715', y: 3620, direction: 'down', client_tick: 12 };
        expect(isPlayerMoveMsg(msg)).toBe(false);
      });

      it('rejects missing y coordinate', () => {
        const msg = { type: 'player_move', player_id: 'p1', x: 2715, direction: 'down', client_tick: 12 };
        expect(isPlayerMoveMsg(msg)).toBe(false);
      });

      it('rejects missing direction', () => {
        const msg = { type: 'player_move', player_id: 'p1', x: 2715, y: 3620, client_tick: 12 };
        expect(isPlayerMoveMsg(msg)).toBe(false);
      });

      it('rejects missing client_tick', () => {
        const msg = { type: 'player_move', player_id: 'p1', x: 2715, y: 3620, direction: 'down' };
        expect(isPlayerMoveMsg(msg)).toBe(false);
      });

      it('rejects null', () => {
        expect(isPlayerMoveMsg(null)).toBe(false);
      });

      it('rejects non-object primitive', () => {
        expect(isPlayerMoveMsg('player_move')).toBe(false);
      });
    });

    describe('npc_interact_request', () => {
      it('accepts valid npc_interact_request message', () => {
        const msg = { type: 'npc_interact_request', player_id: 'p1', npc_id: 'hopper' };
        expect(isNpcInteractRequestMsg(msg)).toBe(true);
      });

      it('rejects missing npc_id', () => {
        const msg = { type: 'npc_interact_request', player_id: 'p1' };
        expect(isNpcInteractRequestMsg(msg)).toBe(false);
      });

      it('rejects missing player_id', () => {
        const msg = { type: 'npc_interact_request', npc_id: 'hopper' };
        expect(isNpcInteractRequestMsg(msg)).toBe(false);
      });

      it('rejects wrong type discriminant', () => {
        const msg = { type: 'quest_accept', player_id: 'p1', npc_id: 'hopper' };
        expect(isNpcInteractRequestMsg(msg)).toBe(false);
      });
    });

    describe('quest_accept', () => {
      it('accepts valid quest_accept message', () => {
        const msg = { type: 'quest_accept', player_id: 'p1', quest_id: 'quest_hopper_blanket' };
        expect(isQuestAcceptMsg(msg)).toBe(true);
      });

      it('rejects missing quest_id', () => {
        const msg = { type: 'quest_accept', player_id: 'p1' };
        expect(isQuestAcceptMsg(msg)).toBe(false);
      });

      it('rejects wrong type discriminant', () => {
        const msg = { type: 'quest_turn_in', player_id: 'p1', quest_id: 'quest_hopper_blanket' };
        expect(isQuestAcceptMsg(msg)).toBe(false);
      });

      it('rejects null', () => {
        expect(isQuestAcceptMsg(null)).toBe(false);
      });
    });

    describe('item_pickup_request', () => {
      it('accepts valid item_pickup_request message', () => {
        const msg = { type: 'item_pickup_request', player_id: 'p1', item_instance_id: 'wi_123' };
        expect(isItemPickupRequestMsg(msg)).toBe(true);
      });

      it('rejects missing item_instance_id', () => {
        const msg = { type: 'item_pickup_request', player_id: 'p1' };
        expect(isItemPickupRequestMsg(msg)).toBe(false);
      });

      it('rejects non-string item_instance_id', () => {
        const msg = { type: 'item_pickup_request', player_id: 'p1', item_instance_id: 123 };
        expect(isItemPickupRequestMsg(msg)).toBe(false);
      });
    });

    describe('quest_turn_in', () => {
      it('accepts valid quest_turn_in message', () => {
        const msg = { type: 'quest_turn_in', player_id: 'p1', quest_id: 'quest_hopper_blanket' };
        expect(isQuestTurnInMsg(msg)).toBe(true);
      });

      it('rejects missing quest_id', () => {
        const msg = { type: 'quest_turn_in', player_id: 'p1' };
        expect(isQuestTurnInMsg(msg)).toBe(false);
      });

      it('rejects wrong type discriminant', () => {
        const msg = { type: 'quest_accept', player_id: 'p1', quest_id: 'quest_hopper_blanket' };
        expect(isQuestTurnInMsg(msg)).toBe(false);
      });
    });

    describe('shop_buy', () => {
      it('accepts valid shop_buy message', () => {
        const msg = { type: 'shop_buy', player_id: 'p1', item_id: 'potion_l0' };
        expect(isShopBuyMsg(msg)).toBe(true);
      });

      it('rejects missing item_id', () => {
        const msg = { type: 'shop_buy', player_id: 'p1' };
        expect(isShopBuyMsg(msg)).toBe(false);
      });

      it('rejects wrong type discriminant', () => {
        const msg = { type: 'use_item', player_id: 'p1', item_id: 'potion_l0' };
        expect(isShopBuyMsg(msg)).toBe(false);
      });
    });

    describe('use_item', () => {
      it('accepts valid use_item message', () => {
        const msg = { type: 'use_item', player_id: 'p1', item_id: 'potion_l0' };
        expect(isUseItemMsg(msg)).toBe(true);
      });

      it('rejects missing item_id', () => {
        const msg = { type: 'use_item', player_id: 'p1' };
        expect(isUseItemMsg(msg)).toBe(false);
      });

      it('rejects wrong type discriminant', () => {
        const msg = { type: 'shop_buy', player_id: 'p1', item_id: 'potion_l0' };
        expect(isUseItemMsg(msg)).toBe(false);
      });
    });

    describe('preset_chat', () => {
      it('accepts valid preset_chat message', () => {
        const msg = { type: 'preset_chat', player_id: 'p1', phrase_id: 'hello' };
        expect(isPresetChatMsg(msg)).toBe(true);
      });

      it('rejects missing phrase_id', () => {
        const msg = { type: 'preset_chat', player_id: 'p1' };
        expect(isPresetChatMsg(msg)).toBe(false);
      });

      it('rejects non-string phrase_id', () => {
        const msg = { type: 'preset_chat', player_id: 'p1', phrase_id: 42 };
        expect(isPresetChatMsg(msg)).toBe(false);
      });
    });

    describe('ping', () => {
      it('accepts valid ping message', () => {
        const msg = { type: 'ping', client_time: 1710000000000 };
        expect(isPingMsg(msg)).toBe(true);
      });

      it('rejects missing client_time', () => {
        const msg = { type: 'ping' };
        expect(isPingMsg(msg)).toBe(false);
      });

      it('rejects non-numeric client_time', () => {
        const msg = { type: 'ping', client_time: '1710000000000' };
        expect(isPingMsg(msg)).toBe(false);
      });

      it('rejects null', () => {
        expect(isPingMsg(null)).toBe(false);
      });
    });
  });

  describe('parseClientMessage', () => {
    it('returns parsed player_move for valid JSON', () => {
      const raw = JSON.stringify({
        type: 'player_move',
        player_id: 'p1',
        x: 100,
        y: 200,
        direction: 'right',
        client_tick: 5,
      });
      const msg = parseClientMessage(raw);
      expect(msg).not.toBeNull();
      expect(msg?.type).toBe('player_move');
    });

    it('returns parsed ping for valid JSON', () => {
      const raw = JSON.stringify({ type: 'ping', client_time: 1710000000000 });
      const msg = parseClientMessage(raw);
      expect(msg).not.toBeNull();
      expect(msg?.type).toBe('ping');
    });

    it('returns null for unknown message type', () => {
      const raw = JSON.stringify({ type: 'unknown_type', foo: 'bar' });
      expect(parseClientMessage(raw)).toBeNull();
    });

    it('returns null for invalid JSON', () => {
      expect(parseClientMessage('not json')).toBeNull();
    });

    it('returns null for JSON that is not an object', () => {
      expect(parseClientMessage('"string"')).toBeNull();
    });

    it('returns null for JSON array', () => {
      expect(parseClientMessage('[]')).toBeNull();
    });

    it('returns null for message missing type field', () => {
      const raw = JSON.stringify({ player_id: 'p1', x: 100 });
      expect(parseClientMessage(raw)).toBeNull();
    });

    it('returns null for message with valid type but missing required fields', () => {
      const raw = JSON.stringify({ type: 'player_move', player_id: 'p1' });
      expect(parseClientMessage(raw)).toBeNull();
    });
  });

  describe('server-to-client WS messages', () => {
    describe('state_sync', () => {
      const validStateSync = {
        type: 'state_sync',
        server_time: '2026-05-10T11:58:30Z',
        player: {
          id: 'p1',
          name: 'Kitty',
          normalized_name: 'kitty',
          character_id: 'arctic_fox',
          x: 2715,
          y: 3620,
          direction: 'down',
          level: 0,
          coins: 25,
        },
        progress: {
          completed_quest_count: 0,
          unique_completed_quest_ids: [],
          used_potion_count: 0,
          unlocked_level: 0,
          unlocked_regions: ['spawn'],
        },
        inventory: [],
        equipment: [],
        quests: [],
        online_players: {},
        world_items: [],
      };

      it('accepts valid state_sync message', () => {
        expect(isStateSyncMsg(validStateSync)).toBe(true);
      });

      it('rejects missing player field', () => {
        const { player: _p, ...rest } = validStateSync;
        expect(isStateSyncMsg(rest)).toBe(false);
      });

      it('rejects missing server_time field', () => {
        const { server_time: _t, ...rest } = validStateSync;
        expect(isStateSyncMsg(rest)).toBe(false);
      });

      it('rejects missing inventory field', () => {
        const { inventory: _i, ...rest } = validStateSync;
        expect(isStateSyncMsg(rest)).toBe(false);
      });

      it('rejects wrong type discriminant', () => {
        expect(isStateSyncMsg({ ...validStateSync, type: 'state_update' })).toBe(false);
      });

      it('rejects null', () => {
        expect(isStateSyncMsg(null)).toBe(false);
      });
    });

    describe('state_update', () => {
      it('accepts valid state_update message', () => {
        const msg = { type: 'state_update', tick: 100, players: { p1: { x: 2720, y: 3624, direction: 'right' } } };
        expect(isStateUpdateMsg(msg)).toBe(true);
      });

      it('accepts state_update with empty players map', () => {
        const msg = { type: 'state_update', tick: 1, players: {} };
        expect(isStateUpdateMsg(msg)).toBe(true);
      });

      it('rejects missing tick field', () => {
        const msg = { type: 'state_update', players: {} };
        expect(isStateUpdateMsg(msg)).toBe(false);
      });

      it('rejects non-numeric tick', () => {
        const msg = { type: 'state_update', tick: '100', players: {} };
        expect(isStateUpdateMsg(msg)).toBe(false);
      });

      it('rejects missing players field', () => {
        const msg = { type: 'state_update', tick: 1 };
        expect(isStateUpdateMsg(msg)).toBe(false);
      });
    });

    describe('player_joined', () => {
      it('accepts valid player_joined message', () => {
        const msg = { type: 'player_joined', player: { id: 'p2', name: 'Bunny', x: 2700, y: 3600 } };
        expect(isPlayerJoinedMsg(msg)).toBe(true);
      });

      it('rejects missing player field', () => {
        const msg = { type: 'player_joined' };
        expect(isPlayerJoinedMsg(msg)).toBe(false);
      });

      it('rejects player missing id', () => {
        const msg = { type: 'player_joined', player: { name: 'Bunny', x: 2700, y: 3600 } };
        expect(isPlayerJoinedMsg(msg)).toBe(false);
      });

      it('rejects player missing name', () => {
        const msg = { type: 'player_joined', player: { id: 'p2', x: 2700, y: 3600 } };
        expect(isPlayerJoinedMsg(msg)).toBe(false);
      });
    });

    describe('player_left', () => {
      it('accepts valid player_left message', () => {
        const msg = { type: 'player_left', player_id: 'p2' };
        expect(isPlayerLeftMsg(msg)).toBe(true);
      });

      it('rejects missing player_id', () => {
        const msg = { type: 'player_left' };
        expect(isPlayerLeftMsg(msg)).toBe(false);
      });

      it('rejects non-string player_id', () => {
        const msg = { type: 'player_left', player_id: 42 };
        expect(isPlayerLeftMsg(msg)).toBe(false);
      });
    });

    describe('quest_offer', () => {
      it('accepts valid quest_offer message', () => {
        const msg = {
          type: 'quest_offer',
          npc_id: 'hopper',
          quest_id: 'quest_hopper_blanket',
          title: "Find Hopper's Blanket",
          time_limit_seconds: 300,
          rewards: [{ item_id: 'coin', quantity: 25 }],
        };
        expect(isQuestOfferMsg(msg)).toBe(true);
      });

      it('rejects missing npc_id', () => {
        const msg = { type: 'quest_offer', quest_id: 'q1', title: 'title', time_limit_seconds: 300, rewards: [] };
        expect(isQuestOfferMsg(msg)).toBe(false);
      });

      it('rejects missing quest_id', () => {
        const msg = { type: 'quest_offer', npc_id: 'hopper', title: 'title', time_limit_seconds: 300, rewards: [] };
        expect(isQuestOfferMsg(msg)).toBe(false);
      });

      it('rejects non-numeric time_limit_seconds', () => {
        const msg = {
          type: 'quest_offer',
          npc_id: 'hopper',
          quest_id: 'q1',
          title: 'title',
          time_limit_seconds: '300',
          rewards: [],
        };
        expect(isQuestOfferMsg(msg)).toBe(false);
      });
    });

    describe('quest_started', () => {
      it('accepts valid quest_started message', () => {
        const msg = {
          type: 'quest_started',
          quest_id: 'quest_hopper_blanket',
          expires_at: '2026-05-10T12:00:00Z',
          world_items: [{ id: 'wi_123', item_id: 'item_blanket', x: 2600, y: 3100 }],
        };
        expect(isQuestStartedMsg(msg)).toBe(true);
      });

      it('accepts quest_started with empty world_items', () => {
        const msg = { type: 'quest_started', quest_id: 'q1', expires_at: '2026-05-10T12:00:00Z', world_items: [] };
        expect(isQuestStartedMsg(msg)).toBe(true);
      });

      it('rejects missing expires_at', () => {
        const msg = { type: 'quest_started', quest_id: 'q1', world_items: [] };
        expect(isQuestStartedMsg(msg)).toBe(false);
      });

      it('rejects missing quest_id', () => {
        const msg = { type: 'quest_started', expires_at: '2026-05-10T12:00:00Z', world_items: [] };
        expect(isQuestStartedMsg(msg)).toBe(false);
      });
    });

    describe('quest_progress', () => {
      it('accepts valid quest_progress message', () => {
        const msg = { type: 'quest_progress', quest_id: 'quest_hopper_blanket', collected: ['item_blanket'] };
        expect(isQuestProgressMsg(msg)).toBe(true);
      });

      it('accepts quest_progress with empty collected array', () => {
        const msg = { type: 'quest_progress', quest_id: 'q1', collected: [] };
        expect(isQuestProgressMsg(msg)).toBe(true);
      });

      it('rejects missing collected field', () => {
        const msg = { type: 'quest_progress', quest_id: 'q1' };
        expect(isQuestProgressMsg(msg)).toBe(false);
      });

      it('rejects missing quest_id', () => {
        const msg = { type: 'quest_progress', collected: [] };
        expect(isQuestProgressMsg(msg)).toBe(false);
      });
    });

    describe('quest_completed', () => {
      it('accepts valid quest_completed message', () => {
        const msg = {
          type: 'quest_completed',
          quest_id: 'quest_hopper_blanket',
          coins_awarded: 25,
          coins_balance: 50,
          rewards: ['accessory_sleepy_hat'],
          rewards_granted_json: ['coins:25', 'equipment:accessory_sleepy_hat:1'],
        };
        expect(isQuestCompletedMsg(msg)).toBe(true);
      });

      it('rejects missing coins_awarded', () => {
        const msg = {
          type: 'quest_completed',
          quest_id: 'q1',
          coins_balance: 50,
          rewards: [],
          rewards_granted_json: [],
        };
        expect(isQuestCompletedMsg(msg)).toBe(false);
      });

      it('rejects non-numeric coins_awarded', () => {
        const msg = {
          type: 'quest_completed',
          quest_id: 'q1',
          coins_awarded: '25',
          coins_balance: 50,
          rewards: [],
          rewards_granted_json: [],
        };
        expect(isQuestCompletedMsg(msg)).toBe(false);
      });

      it('rejects missing rewards_granted_json', () => {
        const msg = {
          type: 'quest_completed',
          quest_id: 'q1',
          coins_awarded: 25,
          coins_balance: 50,
          rewards: [],
        };
        expect(isQuestCompletedMsg(msg)).toBe(false);
      });
    });

    describe('quest_failed', () => {
      it('accepts valid quest_failed message', () => {
        const msg = {
          type: 'quest_failed',
          quest_id: 'quest_hopper_blanket',
          cooldown_until: '2026-05-10T12:30:00Z',
        };
        expect(isQuestFailedMsg(msg)).toBe(true);
      });

      it('rejects missing cooldown_until', () => {
        const msg = { type: 'quest_failed', quest_id: 'q1' };
        expect(isQuestFailedMsg(msg)).toBe(false);
      });

      it('rejects missing quest_id', () => {
        const msg = { type: 'quest_failed', cooldown_until: '2026-05-10T12:30:00Z' };
        expect(isQuestFailedMsg(msg)).toBe(false);
      });
    });

    describe('inventory_updated', () => {
      it('accepts valid inventory_updated message', () => {
        const msg = {
          type: 'inventory_updated',
          inventory: [],
          equipment: [{ item_id: 'potion_l0', quantity: 1 }],
        };
        expect(isInventoryUpdatedMsg(msg)).toBe(true);
      });

      it('accepts inventory_updated with both arrays empty', () => {
        const msg = { type: 'inventory_updated', inventory: [], equipment: [] };
        expect(isInventoryUpdatedMsg(msg)).toBe(true);
      });

      it('rejects missing inventory field', () => {
        const msg = { type: 'inventory_updated', equipment: [] };
        expect(isInventoryUpdatedMsg(msg)).toBe(false);
      });

      it('rejects missing equipment field', () => {
        const msg = { type: 'inventory_updated', inventory: [] };
        expect(isInventoryUpdatedMsg(msg)).toBe(false);
      });
    });

    describe('shop_result', () => {
      it('accepts valid successful shop_result', () => {
        const msg = { type: 'shop_result', success: true, item_id: 'potion_l0', coins_spent: 10, coins_balance: 15 };
        expect(isShopResultMsg(msg)).toBe(true);
      });

      it('accepts valid failed shop_result', () => {
        const msg = { type: 'shop_result', success: false, item_id: 'potion_l0', coins_spent: 0, coins_balance: 5 };
        expect(isShopResultMsg(msg)).toBe(true);
      });

      it('rejects missing success field', () => {
        const msg = { type: 'shop_result', item_id: 'potion_l0', coins_spent: 10, coins_balance: 15 };
        expect(isShopResultMsg(msg)).toBe(false);
      });

      it('rejects non-boolean success field', () => {
        const msg = { type: 'shop_result', success: 1, item_id: 'potion_l0', coins_spent: 10, coins_balance: 15 };
        expect(isShopResultMsg(msg)).toBe(false);
      });

      it('rejects missing coins_balance', () => {
        const msg = { type: 'shop_result', success: true, item_id: 'potion_l0', coins_spent: 10 };
        expect(isShopResultMsg(msg)).toBe(false);
      });
    });

    describe('level_up', () => {
      it('accepts valid level_up message', () => {
        const msg = { type: 'level_up', level: 3, unlocked_regions: ['spawn', 'playground'] };
        expect(isLevelUpMsg(msg)).toBe(true);
      });

      it('rejects non-numeric level', () => {
        const msg = { type: 'level_up', level: '3', unlocked_regions: [] };
        expect(isLevelUpMsg(msg)).toBe(false);
      });

      it('rejects missing unlocked_regions', () => {
        const msg = { type: 'level_up', level: 3 };
        expect(isLevelUpMsg(msg)).toBe(false);
      });

      it('rejects missing level', () => {
        const msg = { type: 'level_up', unlocked_regions: ['spawn'] };
        expect(isLevelUpMsg(msg)).toBe(false);
      });
    });

    describe('chat_message', () => {
      it('accepts valid chat_message', () => {
        const msg = { type: 'chat_message', player_id: 'p1', phrase_id: 'hello', message: 'Hello!' };
        expect(isChatMessageMsg(msg)).toBe(true);
      });

      it('rejects missing phrase_id', () => {
        const msg = { type: 'chat_message', player_id: 'p1', message: 'Hello!' };
        expect(isChatMessageMsg(msg)).toBe(false);
      });

      it('rejects missing message field', () => {
        const msg = { type: 'chat_message', player_id: 'p1', phrase_id: 'hello' };
        expect(isChatMessageMsg(msg)).toBe(false);
      });

      it('rejects missing player_id', () => {
        const msg = { type: 'chat_message', phrase_id: 'hello', message: 'Hello!' };
        expect(isChatMessageMsg(msg)).toBe(false);
      });
    });

    describe('error', () => {
      it('accepts valid error message', () => {
        const msg = { type: 'error', code: 'quest_on_cooldown', message: 'NPC is cooling down.' };
        expect(isErrorMsg(msg)).toBe(true);
      });

      it('rejects missing code', () => {
        const msg = { type: 'error', message: 'something failed' };
        expect(isErrorMsg(msg)).toBe(false);
      });

      it('rejects missing message field', () => {
        const msg = { type: 'error', code: 'internal_error' };
        expect(isErrorMsg(msg)).toBe(false);
      });

      it('rejects non-string code', () => {
        const msg = { type: 'error', code: 500, message: 'error' };
        expect(isErrorMsg(msg)).toBe(false);
      });

      it('rejects null', () => {
        expect(isErrorMsg(null)).toBe(false);
      });
    });

    describe('pong', () => {
      it('accepts valid pong message', () => {
        const msg = { type: 'pong', server_time: '2026-05-10T11:58:30Z' };
        expect(isPongMsg(msg)).toBe(true);
      });

      it('rejects missing server_time', () => {
        const msg = { type: 'pong' };
        expect(isPongMsg(msg)).toBe(false);
      });

      it('rejects non-string server_time', () => {
        const msg = { type: 'pong', server_time: 1234567890 };
        expect(isPongMsg(msg)).toBe(false);
      });
    });
  });

  describe('parseServerMessage', () => {
    it('returns parsed error message for valid JSON', () => {
      const raw = JSON.stringify({ type: 'error', code: 'duplicate_session', message: 'Duplicate session.' });
      const msg = parseServerMessage(raw);
      expect(msg).not.toBeNull();
      expect(msg?.type).toBe('error');
    });

    it('returns parsed pong message for valid JSON', () => {
      const raw = JSON.stringify({ type: 'pong', server_time: '2026-05-10T11:58:30Z' });
      const msg = parseServerMessage(raw);
      expect(msg).not.toBeNull();
      expect(msg?.type).toBe('pong');
    });

    it('returns null for unknown message type', () => {
      const raw = JSON.stringify({ type: 'unknown_server_msg' });
      expect(parseServerMessage(raw)).toBeNull();
    });

    it('returns null for invalid JSON', () => {
      expect(parseServerMessage('{')).toBeNull();
    });

    it('returns null for JSON that is not an object', () => {
      expect(parseServerMessage('42')).toBeNull();
    });

    it('returns null for JSON array', () => {
      expect(parseServerMessage('[]')).toBeNull();
    });

    it('returns null for valid type but missing required fields', () => {
      const raw = JSON.stringify({ type: 'error', code: 'oops' });
      expect(parseServerMessage(raw)).toBeNull();
    });
  });

  describe('message type discrimination', () => {
    it('parseClientMessage discriminates all supported client message types', () => {
      const messages = [
        { type: 'player_move', player_id: 'p1', x: 0, y: 0, direction: 'down', client_tick: 1 },
        { type: 'npc_interact_request', player_id: 'p1', npc_id: 'hopper' },
        { type: 'quest_accept', player_id: 'p1', quest_id: 'q1' },
        { type: 'item_pickup_request', player_id: 'p1', item_instance_id: 'wi_1' },
        { type: 'quest_turn_in', player_id: 'p1', quest_id: 'q1' },
        { type: 'shop_buy', player_id: 'p1', item_id: 'potion_l0' },
        { type: 'use_item', player_id: 'p1', item_id: 'potion_l0' },
        { type: 'preset_chat', player_id: 'p1', phrase_id: 'hello' },
        { type: 'ping', client_time: 1000 },
      ];

      for (const msg of messages) {
        const result = parseClientMessage(JSON.stringify(msg));
        expect(result, `Expected ${msg.type} to parse successfully`).not.toBeNull();
        expect(result?.type).toBe(msg.type);
      }
    });

    it('parseServerMessage discriminates all supported server message types', () => {
      const messages = [
        { type: 'state_update', tick: 1, players: {} },
        { type: 'player_joined', player: { id: 'p2', name: 'Bob', x: 0, y: 0 } },
        { type: 'player_left', player_id: 'p2' },
        {
          type: 'quest_offer',
          npc_id: 'hopper',
          quest_id: 'q1',
          title: 'title',
          time_limit_seconds: 300,
          rewards: [],
        },
        {
          type: 'quest_started',
          quest_id: 'q1',
          expires_at: '2026-05-10T12:00:00Z',
          world_items: [],
        },
        { type: 'quest_progress', quest_id: 'q1', collected: [] },
        {
          type: 'quest_completed',
          quest_id: 'q1',
          coins_awarded: 25,
          coins_balance: 50,
          rewards: [],
          rewards_granted_json: [],
        },
        { type: 'quest_failed', quest_id: 'q1', cooldown_until: '2026-01-01T00:00:00Z' },
        { type: 'inventory_updated', inventory: [], equipment: [] },
        { type: 'shop_result', success: true, item_id: 'potion_l0', coins_spent: 10, coins_balance: 15 },
        { type: 'level_up', level: 3, unlocked_regions: ['spawn'] },
        { type: 'chat_message', player_id: 'p1', phrase_id: 'hi', message: 'Hi!' },
        { type: 'error', code: 'internal_error', message: 'Oops' },
        { type: 'pong', server_time: '2026-05-10T11:58:30Z' },
      ];

      for (const msg of messages) {
        const result = parseServerMessage(JSON.stringify(msg));
        expect(result, `Expected ${msg.type} to parse successfully`).not.toBeNull();
        expect(result?.type).toBe(msg.type);
      }
    });

    it('parseClientMessage returns null for server-only message types', () => {
      const raw = JSON.stringify({ type: 'state_sync', server_time: '2026-05-10T11:58:30Z' });
      expect(parseClientMessage(raw)).toBeNull();
    });

    it('parseServerMessage returns null for client-only message types', () => {
      const raw = JSON.stringify({
        type: 'player_move',
        player_id: 'p1',
        x: 0,
        y: 0,
        direction: 'down',
        client_tick: 1,
      });
      expect(parseServerMessage(raw)).toBeNull();
    });
  });

  describe('REST type guards', () => {
    describe('isLoginResponse', () => {
      it('accepts valid login response with character_id', () => {
        const resp = { player_id: 'p1', name: 'Kitty', normalized_name: 'kitty', character_id: 'arctic_fox' };
        expect(isLoginResponse(resp)).toBe(true);
      });

      it('accepts login response with null character_id for new player before selection', () => {
        const resp = { player_id: 'p1', name: 'Kitty', normalized_name: 'kitty', character_id: null };
        expect(isLoginResponse(resp)).toBe(true);
      });

      it('rejects missing player_id', () => {
        const resp = { name: 'Kitty', normalized_name: 'kitty', character_id: 'arctic_fox' };
        expect(isLoginResponse(resp)).toBe(false);
      });

      it('rejects missing normalized_name', () => {
        const resp = { player_id: 'p1', name: 'Kitty', character_id: 'arctic_fox' };
        expect(isLoginResponse(resp)).toBe(false);
      });

      it('rejects missing name', () => {
        const resp = { player_id: 'p1', normalized_name: 'kitty', character_id: 'arctic_fox' };
        expect(isLoginResponse(resp)).toBe(false);
      });

      it('rejects non-string player_id', () => {
        const resp = { player_id: 123, name: 'Kitty', normalized_name: 'kitty', character_id: null };
        expect(isLoginResponse(resp)).toBe(false);
      });

      it('rejects non-string name', () => {
        const resp = { player_id: 'p1', name: 42, normalized_name: 'kitty', character_id: null };
        expect(isLoginResponse(resp)).toBe(false);
      });

      it('rejects null', () => {
        expect(isLoginResponse(null)).toBe(false);
      });

      it('rejects array', () => {
        expect(isLoginResponse([])).toBe(false);
      });

      it('rejects undefined', () => {
        expect(isLoginResponse(undefined)).toBe(false);
      });
    });
  });
});
