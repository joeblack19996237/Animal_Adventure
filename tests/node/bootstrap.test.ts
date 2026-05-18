import { describe, expect, it } from 'vitest';
import { BootstrapService } from '../../src/services/BootstrapService';

type FetchFn = (url: string) => Promise<Response>;

function makeOkFetch(body: unknown): FetchFn {
  return async () =>
    ({ ok: true, status: 200, json: async () => body }) as unknown as Response;
}

function makeErrorFetch(status: number): FetchFn {
  return async () =>
    ({ ok: false, status, json: async () => ({}) }) as unknown as Response;
}

function makeNetworkErrorFetch(message: string): FetchFn {
  return async () => {
    throw new Error(message);
  };
}

function makeJsonErrorFetch(): FetchFn {
  return async () =>
    ({
      ok: true,
      status: 200,
      json: async () => {
        throw new Error('invalid json');
      },
    }) as unknown as Response;
}

const VALID_CONFIG = {
  map: { width: 5430, height: 7240 },
  map_tiles: { tiles: [] },
  npcs: [],
  quests: [],
  items: [],
  shop: { items: [] },
  characters: [],
  preset_phrases: [],
  progression: { l3: { unique_completed_quests: 2, used_potions: 2 } },
  assets: {},
};

const REQUIRED_KEY_NAMES = [
  'map',
  'map_tiles',
  'npcs',
  'quests',
  'items',
  'shop',
  'characters',
  'preset_phrases',
  'progression',
  'assets',
] as const;

describe('BootstrapService', () => {
  describe('bootstrap_failure_blocks_game_start', () => {
    it('returns error result when fetch throws a network error', async () => {
      const service = new BootstrapService(
        'http://localhost:8000',
        makeNetworkErrorFetch('fetch failed'),
      );
      const result = await service.fetchConfig();
      expect(result.kind).toBe('error');
      if (result.kind === 'error') {
        expect(result.message).toBe('fetch failed');
      }
    });

    it('returns error result when bootstrap endpoint returns a non-ok status', async () => {
      const service = new BootstrapService('http://localhost:8000', makeErrorFetch(503));
      const result = await service.fetchConfig();
      expect(result.kind).toBe('error');
      if (result.kind === 'error') {
        expect(result.message).toContain('503');
      }
    });

    it('returns error result when response body is not valid JSON', async () => {
      const service = new BootstrapService('http://localhost:8000', makeJsonErrorFetch());
      const result = await service.fetchConfig();
      expect(result.kind).toBe('error');
    });

    it('does not signal game-ready when bootstrap fails', async () => {
      const service = new BootstrapService(
        'http://localhost:8000',
        makeNetworkErrorFetch('offline'),
      );
      const result = await service.fetchConfig();
      let gameReady = false;
      if (result.kind === 'ok') {
        gameReady = true;
      }
      expect(gameReady).toBe(false);
    });

    it('allows manual retry — second fetchConfig call succeeds after initial failure', async () => {
      let callCount = 0;
      const retryFetch: FetchFn = async () => {
        callCount += 1;
        if (callCount === 1) throw new Error('first attempt failed');
        return {
          ok: true,
          status: 200,
          json: async () => VALID_CONFIG,
        } as unknown as Response;
      };
      const service = new BootstrapService('http://localhost:8000', retryFetch);
      const first = await service.fetchConfig();
      expect(first.kind).toBe('error');
      const second = await service.fetchConfig();
      expect(second.kind).toBe('ok');
    });
  });

  describe('bootstrap_success_requires_schema', () => {
    it('returns ok result when all required config keys are present', async () => {
      const service = new BootstrapService('http://localhost:8000', makeOkFetch(VALID_CONFIG));
      const result = await service.fetchConfig();
      expect(result.kind).toBe('ok');
    });

    it.each(REQUIRED_KEY_NAMES)(
      'returns error when required key "%s" is absent',
      async (key) => {
        const partial = Object.fromEntries(
          Object.entries(VALID_CONFIG).filter(([k]) => k !== key),
        );
        const service = new BootstrapService('http://localhost:8000', makeOkFetch(partial));
        const result = await service.fetchConfig();
        expect(result.kind).toBe('error');
        if (result.kind === 'error') {
          expect(result.message).toContain(key);
        }
      },
    );

    it('exposes all required config fields on ok result', async () => {
      const service = new BootstrapService('http://localhost:8000', makeOkFetch(VALID_CONFIG));
      const result = await service.fetchConfig();
      if (result.kind === 'ok') {
        expect(result.config.map).toBeDefined();
        expect(result.config.map_tiles).toBeDefined();
        expect(result.config.characters).toBeDefined();
        expect(result.config.preset_phrases).toBeDefined();
      }
    });

    it('requests the correct bootstrap endpoint URL', async () => {
      let capturedUrl = '';
      const captureFetch: FetchFn = async (url) => {
        capturedUrl = url;
        return {
          ok: true,
          status: 200,
          json: async () => VALID_CONFIG,
        } as unknown as Response;
      };
      const service = new BootstrapService('http://localhost:8000', captureFetch);
      await service.fetchConfig();
      expect(capturedUrl).toBe('http://localhost:8000/api/v1/config/bootstrap');
    });
  });
});
