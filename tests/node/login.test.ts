import { describe, it, expect, vi } from 'vitest';
import { LoginController } from '../../src/scenes/LoginController';
import type { LoginResult } from '../../src/net/ApiClient';
import type { ApiClient } from '../../src/net/ApiClient';
import type { SessionState } from '../../src/state/SessionState';

function makeSession() {
  const requireCharacterSelect = vi.fn();
  const beginLoading = vi.fn();
  const session = {
    requireCharacterSelect,
    beginLoading,
    setConnected: vi.fn(),
    reset: vi.fn(),
    getPhase: vi.fn().mockReturnValue('name_entry'),
    getPlayerId: vi.fn().mockReturnValue(null),
    getCharacterId: vi.fn().mockReturnValue(null),
    getPlayerName: vi.fn().mockReturnValue(null),
    snapshot: vi.fn(),
  } as unknown as SessionState;
  return { session, requireCharacterSelect, beginLoading };
}

function makeApi(result: LoginResult) {
  const loginFn = vi.fn().mockResolvedValue(result);
  return { api: { login: loginFn } as unknown as ApiClient, loginFn };
}

const OK_RETURNING: LoginResult = {
  kind: 'ok',
  data: { player_id: 'player-1', name: 'Kitty', normalized_name: 'kitty', character_id: 'arctic_fox' },
};
const CHAR_REQUIRED: LoginResult = { kind: 'character_required' };
const OK_NEW: LoginResult = {
  kind: 'ok',
  data: { player_id: 'player-2', name: 'NewPlayer', normalized_name: 'newplayer', character_id: 'penguin' },
};

describe('login_name_only', () => {
  it('controller starts in idle status with no pending name', () => {
    const { session } = makeSession();
    const { api } = makeApi(OK_RETURNING);
    const ctrl = new LoginController(session, api);
    expect(ctrl.status).toBe('idle');
    expect(ctrl.pendingName).toBeNull();
  });

  it('submitName sends only the name to the API on first call', async () => {
    const { session } = makeSession();
    const { api, loginFn } = makeApi(OK_RETURNING);
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('Kitty');
    expect(loginFn).toHaveBeenCalledWith('Kitty');
    expect(loginFn).toHaveBeenCalledTimes(1);
  });

  it('submitName trims surrounding whitespace before sending', async () => {
    const { session } = makeSession();
    const { api, loginFn } = makeApi(OK_RETURNING);
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('  Kitty  ');
    expect(loginFn).toHaveBeenCalledWith('Kitty');
  });

  it('rejects empty name without calling the API', async () => {
    const { session } = makeSession();
    const { api, loginFn } = makeApi(OK_RETURNING);
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('');
    expect(loginFn).not.toHaveBeenCalled();
    expect(ctrl.status).toBe('error');
  });

  it('rejects whitespace-only name without calling the API', async () => {
    const { session } = makeSession();
    const { api, loginFn } = makeApi(OK_RETURNING);
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('   ');
    expect(loginFn).not.toHaveBeenCalled();
  });
});

describe('login_returning_player_skips_character_select', () => {
  it('transitions directly to done when backend returns existing player data', async () => {
    const { session } = makeSession();
    const { api } = makeApi(OK_RETURNING);
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('Kitty');
    expect(ctrl.status).toBe('done');
  });

  it('does not transition to character_select for returning player', async () => {
    const { session } = makeSession();
    const { api } = makeApi(OK_RETURNING);
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('kitty');
    expect(ctrl.status).not.toBe('character_select');
  });

  it('calls session.beginLoading with backend player data for returning player', async () => {
    const { session, beginLoading } = makeSession();
    const { api } = makeApi(OK_RETURNING);
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('Kitty');
    expect(beginLoading).toHaveBeenCalledWith('player-1', 'arctic_fox', 'Kitty');
  });

  it('does not call session.requireCharacterSelect for returning player', async () => {
    const { session, requireCharacterSelect } = makeSession();
    const { api } = makeApi(OK_RETURNING);
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('Kitty');
    expect(requireCharacterSelect).not.toHaveBeenCalled();
  });
});

describe('login_new_player_character_select', () => {
  it('transitions to character_select when backend requires character selection', async () => {
    const { session } = makeSession();
    const { api } = makeApi(CHAR_REQUIRED);
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('NewPlayer');
    expect(ctrl.status).toBe('character_select');
  });

  it('stores the pending name for the character selection step', async () => {
    const { session } = makeSession();
    const { api } = makeApi(CHAR_REQUIRED);
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('NewPlayer');
    expect(ctrl.pendingName).toBe('NewPlayer');
  });

  it('calls session.requireCharacterSelect for new player', async () => {
    const { session, requireCharacterSelect } = makeSession();
    const { api } = makeApi(CHAR_REQUIRED);
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('NewPlayer');
    expect(requireCharacterSelect).toHaveBeenCalledWith('NewPlayer');
  });

  it('selectCharacter calls API with pending name and chosen character_id', async () => {
    const { session } = makeSession();
    const loginFn = vi.fn().mockResolvedValueOnce(CHAR_REQUIRED).mockResolvedValueOnce(OK_NEW);
    const api = { login: loginFn } as unknown as ApiClient;
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('NewPlayer');
    await ctrl.selectCharacter('penguin');
    expect(loginFn).toHaveBeenCalledWith('NewPlayer', 'penguin');
  });

  it.each(['penguin', 'arctic_fox', 'cat_snowman'])(
    'accepts MVP character %s without error',
    async (charId) => {
      const okResult: LoginResult = {
        kind: 'ok',
        data: { player_id: 'p1', name: 'N', normalized_name: 'n', character_id: charId },
      };
      const { session } = makeSession();
      const loginFn = vi.fn().mockResolvedValueOnce(CHAR_REQUIRED).mockResolvedValueOnce(okResult);
      const api = { login: loginFn } as unknown as ApiClient;
      const ctrl = new LoginController(session, api);
      await ctrl.submitName('N');
      await ctrl.selectCharacter(charId);
      expect(ctrl.status).toBe('done');
    },
  );

  it('transitions to done after successful character selection', async () => {
    const { session } = makeSession();
    const loginFn = vi.fn().mockResolvedValueOnce(CHAR_REQUIRED).mockResolvedValueOnce(OK_NEW);
    const api = { login: loginFn } as unknown as ApiClient;
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('NewPlayer');
    await ctrl.selectCharacter('penguin');
    expect(ctrl.status).toBe('done');
  });

  it('calls session.beginLoading after successful character selection', async () => {
    const { session, beginLoading } = makeSession();
    const loginFn = vi.fn().mockResolvedValueOnce(CHAR_REQUIRED).mockResolvedValueOnce(OK_NEW);
    const api = { login: loginFn } as unknown as ApiClient;
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('NewPlayer');
    await ctrl.selectCharacter('penguin');
    expect(beginLoading).toHaveBeenCalledWith('player-2', 'penguin', 'NewPlayer');
  });

  it('selectCharacter is a no-op when no pending name exists', async () => {
    const { session } = makeSession();
    const { api, loginFn } = makeApi(OK_RETURNING);
    const ctrl = new LoginController(session, api);
    await ctrl.selectCharacter('penguin');
    expect(loginFn).not.toHaveBeenCalled();
  });

  it('remains in character_select and shows error when selection API fails', async () => {
    const errResult: LoginResult = { kind: 'error', message: 'Server unavailable' };
    const { session } = makeSession();
    const loginFn = vi.fn().mockResolvedValueOnce(CHAR_REQUIRED).mockResolvedValueOnce(errResult);
    const api = { login: loginFn } as unknown as ApiClient;
    const ctrl = new LoginController(session, api);
    await ctrl.submitName('NewPlayer');
    await ctrl.selectCharacter('penguin');
    expect(ctrl.status).toBe('character_select');
    expect(ctrl.message).toBe('Server unavailable');
  });
});
