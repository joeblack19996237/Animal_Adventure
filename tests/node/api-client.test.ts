import { describe, it, expect } from 'vitest';
import { ApiClient } from '../../src/net/ApiClient';

type FetchFn = (url: string, init?: RequestInit) => Promise<Response>;

function makeFetch(status: number, body: unknown): FetchFn {
  return async () =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }) as unknown as Response;
}

function makeNetworkErrorFetch(message: string): FetchFn {
  return async () => {
    throw new Error(message);
  };
}

function makeJsonErrorFetch(status: number): FetchFn {
  return async () =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => {
        throw new Error('invalid json');
      },
    }) as unknown as Response;
}

const LOGIN_RESPONSE = {
  player_id: 'player-uuid-1',
  name: 'Kitty',
  normalized_name: 'kitty',
  character_id: 'arctic_fox',
};

describe('ApiClient', () => {
  describe('login', () => {
    describe('returning player', () => {
      it('returns ok result with player data when name matches existing player', async () => {
        const client = new ApiClient('http://localhost:8000', makeFetch(200, LOGIN_RESPONSE));
        const result = await client.login('Kitty');
        expect(result.kind).toBe('ok');
        if (result.kind === 'ok') {
          expect(result.data.player_id).toBe('player-uuid-1');
          expect(result.data.character_id).toBe('arctic_fox');
        }
      });

      it('omits character_id from request body when not provided', async () => {
        let capturedBody = '';
        const captureFetch: FetchFn = async (_url, init) => {
          capturedBody = (init?.body as string) ?? '';
          return { ok: true, status: 200, json: async () => LOGIN_RESPONSE } as unknown as Response;
        };
        const client = new ApiClient('http://localhost:8000', captureFetch);
        await client.login('Kitty');
        expect(JSON.parse(capturedBody)).not.toHaveProperty('character_id');
      });
    });

    describe('new player - character required', () => {
      it('returns character_required when backend signals no player exists', async () => {
        const client = new ApiClient(
          'http://localhost:8000',
          makeFetch(409, { code: 'character_required', message: 'Choose a character' }),
        );
        const result = await client.login('NewPlayer');
        expect(result.kind).toBe('character_required');
      });

      it('keeps compatibility with legacy character_required detail responses', async () => {
        const client = new ApiClient(
          'http://localhost:8000',
          makeFetch(400, { detail: 'character_required' }),
        );
        const result = await client.login('LegacyNewPlayer');
        expect(result.kind).toBe('character_required');
      });
    });

    describe('character selection', () => {
      it('returns ok after POST with name and character_id', async () => {
        const responseWithChar = { ...LOGIN_RESPONSE, character_id: 'penguin' };
        const client = new ApiClient('http://localhost:8000', makeFetch(200, responseWithChar));
        const result = await client.login('NewPlayer', 'penguin');
        expect(result.kind).toBe('ok');
        if (result.kind === 'ok') {
          expect(result.data.character_id).toBe('penguin');
        }
      });

      it('sends character_id in request body', async () => {
        let capturedBody = '';
        const captureFetch: FetchFn = async (_url, init) => {
          capturedBody = (init?.body as string) ?? '';
          const resp = { ...LOGIN_RESPONSE, character_id: 'cat_snowman' };
          return { ok: true, status: 200, json: async () => resp } as unknown as Response;
        };
        const client = new ApiClient('http://localhost:8000', captureFetch);
        await client.login('NewPlayer', 'cat_snowman');
        expect(JSON.parse(capturedBody).character_id).toBe('cat_snowman');
      });

      it('supports all three MVP character ids', async () => {
        const characters = ['penguin', 'arctic_fox', 'cat_snowman'];
        for (const charId of characters) {
          const resp = { ...LOGIN_RESPONSE, character_id: charId };
          const client = new ApiClient('http://localhost:8000', makeFetch(200, resp));
          const result = await client.login('Player', charId);
          expect(result.kind).toBe('ok');
          if (result.kind === 'ok') {
            expect(result.data.character_id).toBe(charId);
          }
        }
      });
    });

    describe('name normalization', () => {
      it('trims surrounding whitespace before sending', async () => {
        let capturedBody = '';
        const captureFetch: FetchFn = async (_url, init) => {
          capturedBody = (init?.body as string) ?? '';
          return { ok: true, status: 200, json: async () => LOGIN_RESPONSE } as unknown as Response;
        };
        const client = new ApiClient('http://localhost:8000', captureFetch);
        await client.login('  Kitty  ');
        expect(JSON.parse(capturedBody).name).toBe('Kitty');
      });

      it('trims tabs and newlines from name', async () => {
        let capturedBody = '';
        const captureFetch: FetchFn = async (_url, init) => {
          capturedBody = (init?.body as string) ?? '';
          return { ok: true, status: 200, json: async () => LOGIN_RESPONSE } as unknown as Response;
        };
        const client = new ApiClient('http://localhost:8000', captureFetch);
        await client.login('\t Alice \n');
        expect(JSON.parse(capturedBody).name).toBe('Alice');
      });

      it('returns error for empty string name without making a request', async () => {
        let fetchCalled = false;
        const trackFetch: FetchFn = async () => {
          fetchCalled = true;
          return { ok: true, status: 200, json: async () => LOGIN_RESPONSE } as unknown as Response;
        };
        const client = new ApiClient('http://localhost:8000', trackFetch);
        const result = await client.login('');
        expect(result.kind).toBe('error');
        expect(fetchCalled).toBe(false);
      });

      it('returns error for whitespace-only name without making a request', async () => {
        let fetchCalled = false;
        const trackFetch: FetchFn = async () => {
          fetchCalled = true;
          return { ok: true, status: 200, json: async () => LOGIN_RESPONSE } as unknown as Response;
        };
        const client = new ApiClient('http://localhost:8000', trackFetch);
        const result = await client.login('   ');
        expect(result.kind).toBe('error');
        expect(fetchCalled).toBe(false);
      });
    });

    describe('request details', () => {
      it('posts to /api/v1/players endpoint', async () => {
        let capturedUrl = '';
        const captureFetch: FetchFn = async (url) => {
          capturedUrl = url;
          return { ok: true, status: 200, json: async () => LOGIN_RESPONSE } as unknown as Response;
        };
        const client = new ApiClient('http://localhost:8000', captureFetch);
        await client.login('Kitty');
        expect(capturedUrl).toBe('http://localhost:8000/api/v1/players');
      });

      it('uses POST method', async () => {
        let capturedMethod = '';
        const captureFetch: FetchFn = async (_url, init) => {
          capturedMethod = init?.method ?? '';
          return { ok: true, status: 200, json: async () => LOGIN_RESPONSE } as unknown as Response;
        };
        const client = new ApiClient('http://localhost:8000', captureFetch);
        await client.login('Kitty');
        expect(capturedMethod).toBe('POST');
      });

      it('sets Content-Type header to application/json', async () => {
        let capturedHeaders: Record<string, string> = {};
        const captureFetch: FetchFn = async (_url, init) => {
          capturedHeaders = (init?.headers as Record<string, string>) ?? {};
          return { ok: true, status: 200, json: async () => LOGIN_RESPONSE } as unknown as Response;
        };
        const client = new ApiClient('http://localhost:8000', captureFetch);
        await client.login('Kitty');
        expect(capturedHeaders['Content-Type']).toBe('application/json');
      });
    });

    describe('error handling', () => {
      it('returns error with message when network request throws', async () => {
        const client = new ApiClient(
          'http://localhost:8000',
          makeNetworkErrorFetch('fetch failed'),
        );
        const result = await client.login('Kitty');
        expect(result.kind).toBe('error');
        if (result.kind === 'error') {
          expect(result.message).toBe('fetch failed');
        }
      });

      it('returns error when response JSON cannot be parsed', async () => {
        const client = new ApiClient('http://localhost:8000', makeJsonErrorFetch(200));
        const result = await client.login('Kitty');
        expect(result.kind).toBe('error');
      });

      it('returns error when 200 response has unexpected shape', async () => {
        const client = new ApiClient('http://localhost:8000', makeFetch(200, { unexpected: true }));
        const result = await client.login('Kitty');
        expect(result.kind).toBe('error');
      });

      it('returns error with server detail on non-character_required failure', async () => {
        const client = new ApiClient(
          'http://localhost:8000',
          makeFetch(500, { detail: 'internal server error' }),
        );
        const result = await client.login('Kitty');
        expect(result.kind).toBe('error');
        if (result.kind === 'error') {
          expect(result.message).toBe('internal server error');
        }
      });

      it('returns error containing status code when failure has no detail field', async () => {
        const client = new ApiClient('http://localhost:8000', makeFetch(503, {}));
        const result = await client.login('Kitty');
        expect(result.kind).toBe('error');
        if (result.kind === 'error') {
          expect(result.message).toContain('503');
        }
      });
    });
  });
});
