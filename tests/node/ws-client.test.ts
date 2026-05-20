import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WSClient, RECONNECT_TIMEOUT_MESSAGE, type WebSocketConstructor, type WebSocketLike } from '../../src/net/WSClient';

class MockWebSocket implements WebSocketLike {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static instances: MockWebSocket[] = [];
  static autoFail = false;

  readyState = MockWebSocket.CONNECTING;
  onopen: ((event: unknown) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  readonly sentMessages: string[] = [];

  constructor(public readonly url: string) {
    MockWebSocket.instances.push(this);
    if (MockWebSocket.autoFail) {
      setTimeout(() => this.triggerClose(), 0);
    }
  }

  triggerOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.({});
  }

  triggerClose(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({});
  }

  triggerMessage(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  send(data: string): void {
    this.sentMessages.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
  }

  static reset(autoFail = false): void {
    MockWebSocket.instances = [];
    MockWebSocket.autoFail = autoFail;
  }
}

function makeClient(overrides: {
  onMessage?: (msg: Record<string, unknown>) => void;
  onReconnectTimeout?: () => void;
  onDuplicateSession?: () => void;
} = {}): WSClient {
  return new WSClient({
    playerId: 'p1',
    wsUrl: 'ws://localhost/ws/p1',
    WebSocketCtor: MockWebSocket as unknown as WebSocketConstructor,
    ...overrides,
  });
}

describe('WSClient', () => {
  beforeEach(() => {
    MockWebSocket.reset();
  });

  afterEach(() => {
    vi.useRealTimers();
    MockWebSocket.reset();
  });

  describe('connect and state_sync', () => {
    it('opens a WebSocket to the configured URL on connect', () => {
      const client = makeClient();
      client.connect();
      expect(MockWebSocket.instances).toHaveLength(1);
      expect(MockWebSocket.instances[0].url).toBe('ws://localhost/ws/p1');
    });

    it('calls onMessage handler when server sends state_sync', () => {
      const received: Record<string, unknown>[] = [];
      const client = makeClient({ onMessage: (msg) => received.push(msg) });
      client.connect();
      const ws = MockWebSocket.instances[0];
      ws.triggerOpen();
      ws.triggerMessage({ type: 'state_sync', server_time: '2026-05-10T12:00:00Z', player: {}, progress: {}, inventory: [], equipment: [], quests: [], online_players: {}, world_items: [] });
      expect(received).toHaveLength(1);
      expect(received[0]['type']).toBe('state_sync');
    });

    it('does not open a second socket if already connected', () => {
      const client = makeClient();
      client.connect();
      MockWebSocket.instances[0].triggerOpen();
      client.connect();
      expect(MockWebSocket.instances).toHaveLength(1);
    });

    it('calls onDuplicateSession and does not reconnect when duplicate_session received', async () => {
      vi.useFakeTimers();
      let duplicateCalled = false;
      const client = makeClient({ onDuplicateSession: () => { duplicateCalled = true; } });
      client.connect();
      const ws = MockWebSocket.instances[0];
      ws.triggerOpen();
      ws.triggerMessage({ type: 'error', code: 'duplicate_session', message: 'Duplicate session.' });
      await vi.advanceTimersByTimeAsync(5000);
      expect(duplicateCalled).toBe(true);
      expect(MockWebSocket.instances).toHaveLength(1);
    });
  });

  describe('movement throttle at 20Hz', () => {
    const moveMsg = { type: 'player_move', player_id: 'p1', x: 100, y: 200, direction: 'right', client_tick: 1 };

    it('sends the first player_move message immediately', () => {
      vi.useFakeTimers();
      const client = makeClient();
      client.connect();
      MockWebSocket.instances[0].triggerOpen();
      client.sendMove(moveMsg);
      expect(MockWebSocket.instances[0].sentMessages).toHaveLength(1);
    });

    it('drops player_move messages within the 50ms throttle window', () => {
      vi.useFakeTimers();
      const client = makeClient();
      client.connect();
      MockWebSocket.instances[0].triggerOpen();
      for (let i = 0; i < 5; i++) client.sendMove(moveMsg);
      expect(MockWebSocket.instances[0].sentMessages).toHaveLength(1);
    });

    it('allows a second player_move after 50ms have elapsed', () => {
      vi.useFakeTimers();
      const client = makeClient();
      client.connect();
      MockWebSocket.instances[0].triggerOpen();
      client.sendMove(moveMsg);
      vi.advanceTimersByTime(50);
      client.sendMove({ ...moveMsg, client_tick: 2 });
      expect(MockWebSocket.instances[0].sentMessages).toHaveLength(2);
    });

    it('does not send player_move when socket is not open', () => {
      const client = makeClient();
      client.connect();
      client.sendMove(moveMsg);
      expect(MockWebSocket.instances[0].sentMessages).toHaveLength(0);
    });
  });

  describe('reliable command sends', () => {
    const questTurnIn = { type: 'quest_turn_in', player_id: 'p1', quest_id: 'quest_hopper_blanket' };

    it('queues command messages until the socket opens', () => {
      const client = makeClient();
      client.connect();
      client.send(questTurnIn);

      expect(MockWebSocket.instances[0].sentMessages).toHaveLength(0);

      MockWebSocket.instances[0].triggerOpen();
      expect(MockWebSocket.instances[0].sentMessages).toHaveLength(1);
      expect(JSON.parse(MockWebSocket.instances[0].sentMessages[0])).toEqual(questTurnIn);
    });

    it('flushes queued command messages after reconnect', async () => {
      vi.useFakeTimers();
      const client = makeClient();
      client.connect();
      const ws0 = MockWebSocket.instances[0];
      ws0.triggerOpen();
      ws0.triggerClose();

      client.send(questTurnIn);
      await vi.advanceTimersByTimeAsync(1100);

      const ws1 = MockWebSocket.instances[1];
      expect(ws1.sentMessages).toHaveLength(0);
      ws1.triggerOpen();
      expect(ws1.sentMessages).toHaveLength(1);
      expect(JSON.parse(ws1.sentMessages[0])).toEqual(questTurnIn);
    });

    it('reports open state accurately', () => {
      const client = makeClient();
      client.connect();
      expect(client.isOpen()).toBe(false);
      MockWebSocket.instances[0].triggerOpen();
      expect(client.isOpen()).toBe(true);
      MockWebSocket.instances[0].triggerClose();
      expect(client.isOpen()).toBe(false);
    });
  });

  describe('reconnect with exponential backoff', () => {
    it('opens a new socket after close with initial 1s delay', async () => {
      vi.useFakeTimers();
      const client = makeClient();
      client.connect();
      MockWebSocket.instances[0].triggerOpen();
      MockWebSocket.instances[0].triggerClose();
      await vi.advanceTimersByTimeAsync(1100);
      expect(MockWebSocket.instances).toHaveLength(2);
    });

    it('delivers state_sync through onMessage after successful reconnect', async () => {
      vi.useFakeTimers();
      const received: Record<string, unknown>[] = [];
      const client = makeClient({ onMessage: (msg) => received.push(msg) });
      client.connect();
      MockWebSocket.instances[0].triggerOpen();
      MockWebSocket.instances[0].triggerClose();
      await vi.advanceTimersByTimeAsync(1100);
      const ws1 = MockWebSocket.instances[1];
      ws1.triggerOpen();
      ws1.triggerMessage({ type: 'state_sync', server_time: '2026-05-10T12:01:00Z', player: {}, progress: {}, inventory: [], equipment: [], quests: [], online_players: {}, world_items: [] });
      expect(received.some((m) => m['type'] === 'state_sync')).toBe(true);
    });

    it('calls onReconnectTimeout after 120 seconds with no successful connection', async () => {
      vi.useFakeTimers();
      MockWebSocket.reset(true);
      let timedOut = false;
      const client = makeClient({ onReconnectTimeout: () => { timedOut = true; } });
      client.connect();
      await vi.advanceTimersByTimeAsync(125_000);
      expect(timedOut).toBe(true);
    });

    it('RECONNECT_TIMEOUT_MESSAGE matches the required user-facing string', () => {
      expect(RECONNECT_TIMEOUT_MESSAGE).toBe('Server is temporarily unavailable. Please refresh the page.');
    });

    it('stops creating sockets after 120-second timeout', async () => {
      vi.useFakeTimers();
      MockWebSocket.reset(true);
      const client = makeClient({ onReconnectTimeout: () => { /* no-op */ } });
      client.connect();
      await vi.advanceTimersByTimeAsync(125_000);
      const countAfterTimeout = MockWebSocket.instances.length;
      await vi.advanceTimersByTimeAsync(30_000);
      expect(MockWebSocket.instances.length).toBe(countAfterTimeout);
    });
  });

  describe('duplicate reconnect protection', () => {
    it('does not open duplicate sockets when close fires multiple times', async () => {
      vi.useFakeTimers();
      const client = makeClient();
      client.connect();
      MockWebSocket.instances[0].triggerOpen();
      MockWebSocket.instances[0].triggerClose();
      MockWebSocket.instances[0].triggerClose();
      MockWebSocket.instances[0].triggerClose();
      await vi.advanceTimersByTimeAsync(1100);
      expect(MockWebSocket.instances).toHaveLength(2);
    });

    it('resets reconnect state after a successful reconnect', async () => {
      vi.useFakeTimers();
      const client = makeClient();
      client.connect();
      MockWebSocket.instances[0].triggerOpen();
      MockWebSocket.instances[0].triggerClose();
      await vi.advanceTimersByTimeAsync(1100);
      MockWebSocket.instances[1].triggerOpen();
      MockWebSocket.instances[1].triggerClose();
      await vi.advanceTimersByTimeAsync(1100);
      expect(MockWebSocket.instances).toHaveLength(3);
    });
  });
});
