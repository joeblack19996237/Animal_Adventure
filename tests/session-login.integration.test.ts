import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { spawn } from 'child_process';
import type { ChildProcess } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { ApiClient } from '../src/net/ApiClient';

const TEST_PORT = 18090;
const INITIAL_COINS = 25;
const BASE_URL = `http://127.0.0.1:${TEST_PORT}`;

let serverProcess: ChildProcess | undefined;
let testDbDir = '';

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

async function waitForBackend(timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const resp = await fetch(`${BASE_URL}/health`);
      if (resp.ok) return;
    } catch (_err) {
      // connection refused — server not ready, retry
    }
    await new Promise<void>((resolve) => setTimeout(() => resolve(), 250));
  }
  throw new Error(`Backend did not start within ${timeoutMs}ms`);
}

async function initDb(dbPath: string): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const proc = spawn(
      'python',
      [
        '-c',
        'import sys; from app.db import init_db; from pathlib import Path; init_db(Path(sys.argv[1]))',
        dbPath,
      ],
      { stdio: 'pipe' },
    );
    proc.on('close', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`DB init exited with code ${code}`));
      }
    });
    proc.on('error', reject);
  });
}

async function postPlayer(name: string, characterId?: string): Promise<unknown> {
  const body: Record<string, string> = { name };
  if (characterId !== undefined) {
    body['character_id'] = characterId;
  }
  const resp = await fetch(`${BASE_URL}/api/v1/players`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return resp.json();
}

beforeAll(async () => {
  testDbDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aa-session-'));
  const dbPath = path.join(testDbDir, 'test.sqlite3');
  await initDb(dbPath);
  serverProcess = spawn(
    'python',
    [
      '-m',
      'uvicorn',
      'app.main:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(TEST_PORT),
      '--log-level',
      'warning',
      '--no-access-log',
    ],
    { env: { ...process.env, DATABASE_PATH: dbPath }, stdio: 'pipe' },
  );
  await waitForBackend(20000);
}, 30000);

afterAll(() => {
  serverProcess?.kill();
  if (testDbDir) {
    fs.rmSync(testDbDir, { recursive: true, force: true });
  }
});

describe('e2e_name_login_creates_player', () => {
  it(
    'ApiClient login for new player first gets character_required then creates player with player_id',
    async () => {
      const client = new ApiClient(BASE_URL);

      // New player with name only must signal character selection is required
      const firstResult = await client.login('CreatePlayerTest');
      expect(firstResult.kind).toBe('character_required');

      // Second call with character_id creates the player in the backend
      const secondResult = await client.login('CreatePlayerTest', 'penguin');
      expect(secondResult.kind).toBe('ok');
      if (secondResult.kind === 'ok') {
        expect(typeof secondResult.data.player_id).toBe('string');
        expect(secondResult.data.player_id.length).toBeGreaterThan(0);
        expect(secondResult.data.name).toBe('CreatePlayerTest');
        expect(secondResult.data.character_id).toBe('penguin');
        expect(secondResult.data.normalized_name).toBe('createplayertest');
      }
    },
    15000,
  );
});

describe('e2e_return_login_case_insensitive', () => {
  it(
    'returning login with different name casing loads the same player',
    async () => {
      // Set up a known player directly via REST to isolate this test from ApiClient behaviour
      const setupData = await postPlayer('CasePlayer', 'arctic_fox');
      if (!isRecord(setupData) || typeof setupData['player_id'] !== 'string') {
        throw new Error('Setup failed: player creation returned unexpected shape');
      }
      const originalId = setupData['player_id'];

      const client = new ApiClient(BASE_URL);

      // Uppercase variant must resolve to the same player
      const upperResult = await client.login('CASEPLAYER');
      expect(upperResult.kind).toBe('ok');
      if (upperResult.kind === 'ok') {
        expect(upperResult.data.player_id).toBe(originalId);
      }

      // Lowercase variant must also resolve to the same player
      const lowerResult = await client.login('caseplayer');
      expect(lowerResult.kind).toBe('ok');
      if (lowerResult.kind === 'ok') {
        expect(lowerResult.data.player_id).toBe(originalId);
      }
    },
    15000,
  );
});

describe('e2e_reload_restores_session', () => {
  it(
    'backend serves durable session snapshot after reconnect with position, coins, and character',
    async () => {
      // Create player via REST API
      const setupData = await postPlayer('ReloadPlayer', 'cat_snowman');
      if (!isRecord(setupData) || typeof setupData['player_id'] !== 'string') {
        throw new Error('Setup failed: player creation returned unexpected shape');
      }
      const playerId = setupData['player_id'];

      // Simulate "page reload / WebSocket reconnect" by fetching the durable snapshot.
      // The GET /api/v1/players/:id endpoint returns the same persisted fields that
      // state_sync sends on WebSocket reconnect (position, coins, level, character_id).
      const snapResp = await fetch(`${BASE_URL}/api/v1/players/${playerId}`);
      expect(snapResp.ok).toBe(true);

      const snapshot: unknown = await snapResp.json();
      expect(isRecord(snapshot)).toBe(true);
      if (!isRecord(snapshot)) return;

      // Position is persisted at spawn coordinates
      expect(typeof snapshot['x']).toBe('number');
      expect(typeof snapshot['y']).toBe('number');

      // Coins are persisted at initial balance
      expect(snapshot['coins']).toBe(INITIAL_COINS);

      // Level is persisted
      expect(typeof snapshot['level']).toBe('number');

      // Character selection is durable
      expect(snapshot['character_id']).toBe('cat_snowman');

      // player_id is stable across reconnects
      expect(snapshot['player_id']).toBe(playerId);
    },
    15000,
  );
});
