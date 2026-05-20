export type LoginPhase = 'name_entry' | 'character_select' | 'loading' | 'connected';

export interface SessionSnapshot {
  readonly phase: LoginPhase;
  readonly playerId: string | null;
  readonly characterId: string | null;
  readonly playerName: string | null;
}

export interface Storage {
  get(key: string): string | null;
  set(key: string, value: string): void;
  remove(key: string): void;
}

const PLAYER_ID_KEY = 'animal_adventure_player_id';

const localStorageAdapter: Storage = {
  get: (key) => {
    try {
      return globalThis.localStorage?.getItem(key) ?? null;
    } catch (e: unknown) {
      console.warn('localStorage.getItem failed', e);
      return null;
    }
  },
  set: (key, value) => {
    try {
      globalThis.localStorage?.setItem(key, value);
    } catch (e: unknown) {
      console.warn('localStorage.setItem failed', e);
    }
  },
  remove: (key) => {
    try {
      globalThis.localStorage?.removeItem(key);
    } catch (e: unknown) {
      console.warn('localStorage.removeItem failed', e);
    }
  },
};

export class SessionState {
  private phase: LoginPhase = 'name_entry';
  private playerId: string | null = null;
  private characterId: string | null = null;
  private playerName: string | null = null;
  private readonly storage: Storage;

  constructor(storage: Storage = localStorageAdapter) {
    this.storage = storage;
    const stored = this.storage.get(PLAYER_ID_KEY);
    if (stored !== null) {
      this.playerId = stored;
    }
  }

  getPhase(): LoginPhase {
    return this.phase;
  }

  getPlayerId(): string | null {
    return this.playerId;
  }

  getCharacterId(): string | null {
    return this.characterId;
  }

  getPlayerName(): string | null {
    return this.playerName;
  }

  snapshot(): SessionSnapshot {
    return {
      phase: this.phase,
      playerId: this.playerId,
      characterId: this.characterId,
      playerName: this.playerName,
    };
  }

  requireCharacterSelect(name: string): void {
    this.playerName = name;
    this.phase = 'character_select';
  }

  beginLoading(playerId: string, characterId: string | null, playerName: string): void {
    this.playerId = playerId;
    this.characterId = characterId;
    this.playerName = playerName;
    this.phase = 'loading';
    this.storage.set(PLAYER_ID_KEY, playerId);
  }

  setConnected(): void {
    this.phase = 'connected';
  }

  reset(): void {
    this.phase = 'name_entry';
    this.playerId = null;
    this.characterId = null;
    this.playerName = null;
    this.storage.remove(PLAYER_ID_KEY);
  }
}
