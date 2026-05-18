import { describe, it, expect } from 'vitest';
import { SessionState } from '../../src/state/SessionState';
import type { Storage } from '../../src/state/SessionState';

function makeStorage(initial: Record<string, string> = {}): Storage {
  const store: Record<string, string> = { ...initial };
  return {
    get: (key) => store[key] ?? null,
    set: (key, value) => {
      store[key] = value;
    },
    remove: (key) => {
      delete store[key];
    },
  };
}

describe('SessionState', () => {
  describe('initial state', () => {
    it('starts in name_entry phase', () => {
      const state = new SessionState(makeStorage());
      expect(state.getPhase()).toBe('name_entry');
    });

    it('has no player_id initially when storage is empty', () => {
      const state = new SessionState(makeStorage());
      expect(state.getPlayerId()).toBeNull();
    });

    it('has no character_id initially', () => {
      const state = new SessionState(makeStorage());
      expect(state.getCharacterId()).toBeNull();
    });

    it('has no player name initially', () => {
      const state = new SessionState(makeStorage());
      expect(state.getPlayerName()).toBeNull();
    });

    it('restores player_id from storage on construction', () => {
      const storage = makeStorage({ animal_adventure_player_id: 'player-123' });
      const state = new SessionState(storage);
      expect(state.getPlayerId()).toBe('player-123');
    });
  });

  describe('new player flow', () => {
    it('transitions to character_select phase when backend requires character selection', () => {
      const state = new SessionState(makeStorage());
      state.requireCharacterSelect('Alice');
      expect(state.getPhase()).toBe('character_select');
    });

    it('stores player name when requiring character select', () => {
      const state = new SessionState(makeStorage());
      state.requireCharacterSelect('Alice');
      expect(state.getPlayerName()).toBe('Alice');
    });

    it('transitions to loading after character selection', () => {
      const state = new SessionState(makeStorage());
      state.requireCharacterSelect('Alice');
      state.beginLoading('player-uuid', 'penguin', 'Alice');
      expect(state.getPhase()).toBe('loading');
    });

    it('stores player_id after beginLoading', () => {
      const state = new SessionState(makeStorage());
      state.beginLoading('player-uuid', 'penguin', 'Alice');
      expect(state.getPlayerId()).toBe('player-uuid');
    });

    it('stores character_id after beginLoading', () => {
      const state = new SessionState(makeStorage());
      state.beginLoading('player-uuid', 'penguin', 'Alice');
      expect(state.getCharacterId()).toBe('penguin');
    });

    it('persists player_id to storage in beginLoading', () => {
      const storage = makeStorage();
      const state = new SessionState(storage);
      state.beginLoading('player-uuid', 'penguin', 'Alice');
      expect(storage.get('animal_adventure_player_id')).toBe('player-uuid');
    });

    it('transitions to connected after setConnected', () => {
      const state = new SessionState(makeStorage());
      state.beginLoading('player-uuid', 'penguin', 'Alice');
      state.setConnected();
      expect(state.getPhase()).toBe('connected');
    });

    it('supports all three MVP character ids', () => {
      for (const charId of ['penguin', 'arctic_fox', 'cat_snowman']) {
        const state = new SessionState(makeStorage());
        state.beginLoading('player-uuid', charId, 'Player');
        expect(state.getCharacterId()).toBe(charId);
      }
    });
  });

  describe('returning player flow', () => {
    it('skips character_select and goes directly to loading when player exists', () => {
      const state = new SessionState(makeStorage());
      state.beginLoading('existing-player-id', 'arctic_fox', 'Kitty');
      expect(state.getPhase()).toBe('loading');
    });

    it('stores name from server response', () => {
      const state = new SessionState(makeStorage());
      state.beginLoading('existing-player-id', 'arctic_fox', 'Kitty');
      expect(state.getPlayerName()).toBe('Kitty');
    });

    it('loads persisted player_id from storage as a hint for returning players', () => {
      const storage = makeStorage({ animal_adventure_player_id: 'returning-player-id' });
      const state = new SessionState(storage);
      expect(state.getPlayerId()).toBe('returning-player-id');
    });

    it('overwrites stored player_id when a new session begins', () => {
      const storage = makeStorage({ animal_adventure_player_id: 'old-player-id' });
      const state = new SessionState(storage);
      state.beginLoading('new-player-id', 'arctic_fox', 'Alice');
      expect(state.getPlayerId()).toBe('new-player-id');
      expect(storage.get('animal_adventure_player_id')).toBe('new-player-id');
    });
  });

  describe('snapshot', () => {
    it('returns full session snapshot with all fields', () => {
      const state = new SessionState(makeStorage());
      state.beginLoading('player-1', 'cat_snowman', 'Bob');
      const snap = state.snapshot();
      expect(snap.phase).toBe('loading');
      expect(snap.playerId).toBe('player-1');
      expect(snap.characterId).toBe('cat_snowman');
      expect(snap.playerName).toBe('Bob');
    });

    it('snapshot reflects initial state', () => {
      const state = new SessionState(makeStorage());
      const snap = state.snapshot();
      expect(snap.phase).toBe('name_entry');
      expect(snap.playerId).toBeNull();
      expect(snap.characterId).toBeNull();
      expect(snap.playerName).toBeNull();
    });
  });

  describe('reset', () => {
    it('resets phase to name_entry', () => {
      const state = new SessionState(makeStorage());
      state.beginLoading('player-uuid', 'penguin', 'Alice');
      state.setConnected();
      state.reset();
      expect(state.getPhase()).toBe('name_entry');
    });

    it('clears player_id on reset', () => {
      const state = new SessionState(makeStorage());
      state.beginLoading('player-uuid', 'penguin', 'Alice');
      state.reset();
      expect(state.getPlayerId()).toBeNull();
    });

    it('clears character_id on reset', () => {
      const state = new SessionState(makeStorage());
      state.beginLoading('player-uuid', 'penguin', 'Alice');
      state.reset();
      expect(state.getCharacterId()).toBeNull();
    });

    it('clears player name on reset', () => {
      const state = new SessionState(makeStorage());
      state.requireCharacterSelect('Alice');
      state.reset();
      expect(state.getPlayerName()).toBeNull();
    });

    it('removes player_id from storage on reset', () => {
      const storage = makeStorage();
      const state = new SessionState(storage);
      state.beginLoading('player-uuid', 'penguin', 'Alice');
      state.reset();
      expect(storage.get('animal_adventure_player_id')).toBeNull();
    });
  });
});
