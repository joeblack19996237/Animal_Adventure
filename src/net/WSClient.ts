export interface WebSocketLike {
  readyState: number;
  onopen: ((event: unknown) => void) | null;
  onclose: ((event: unknown) => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onerror: ((event: unknown) => void) | null;
  send(data: string): void;
  close(): void;
}

export type WebSocketConstructor = new (url: string) => WebSocketLike;

export interface WSClientOptions {
  playerId: string;
  wsUrl?: string;
  WebSocketCtor?: WebSocketConstructor;
  onMessage?: (msg: Record<string, unknown>) => void;
  onReconnectTimeout?: () => void;
  onDuplicateSession?: () => void;
}

const MOVE_INTERVAL_MS = 50;
const RECONNECT_TIMEOUT_MS = 120_000;
const MAX_BACKOFF_MS = 30_000;

export const RECONNECT_TIMEOUT_MESSAGE = 'Server is temporarily unavailable. Please refresh the page.';

function isRecord(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

function deriveWsUrl(playerId: string): string {
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  if (origin.startsWith('https://')) {
    return `wss://${origin.slice(8)}/ws/${playerId}`;
  }
  if (origin.startsWith('http://')) {
    return `ws://${origin.slice(7)}/ws/${playerId}`;
  }
  throw new Error(`Unsupported origin protocol: ${origin}`);
}

export class WSClient {
  private readonly wsUrl: string;
  private readonly WebSocketCtor: WebSocketConstructor;
  private readonly onMessageHandler: (msg: Record<string, unknown>) => void;
  private readonly onReconnectTimeoutHandler: () => void;
  private readonly onDuplicateSessionHandler: () => void;

  private ws: WebSocketLike | null = null;
  private stopped = false;
  private reconnecting = false;
  private reconnectStartTime: number | null = null;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private lastMoveSentAt = -Infinity;

  constructor(options: WSClientOptions) {
    this.wsUrl = options.wsUrl ?? deriveWsUrl(options.playerId);
    // justified: native WebSocket ctor signature includes optional protocols param not in minimal WebSocketLike
    this.WebSocketCtor = options.WebSocketCtor ?? (globalThis.WebSocket as unknown as WebSocketConstructor);
    this.onMessageHandler = options.onMessage ?? (() => { /* no-op */ });
    this.onReconnectTimeoutHandler = options.onReconnectTimeout ?? (() => { /* no-op */ });
    this.onDuplicateSessionHandler = options.onDuplicateSession ?? (() => { /* no-op */ });
  }

  connect(): void {
    if (this.ws !== null && (this.ws.readyState === 0 || this.ws.readyState === 1)) {
      return;
    }
    this.openSocket();
  }

  sendMove(msg: Record<string, unknown>): void {
    const now = Date.now();
    if (now - this.lastMoveSentAt < MOVE_INTERVAL_MS) return;
    if (this.ws === null || this.ws.readyState !== 1) return;
    this.lastMoveSentAt = now;
    try {
      this.ws.send(JSON.stringify(msg));
    } catch {
      // justified: send is best-effort; dropped messages on close are normal WebSocket behavior
    }
  }

  send(msg: Record<string, unknown>): void {
    if (this.ws === null || this.ws.readyState !== 1) return;
    try {
      this.ws.send(JSON.stringify(msg));
    } catch {
      // justified: send is best-effort; dropped messages on close are normal WebSocket behavior
    }
  }

  private openSocket(): void {
    const ws = new this.WebSocketCtor(this.wsUrl);
    this.ws = ws;

    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.reconnecting = false;
      this.reconnectStartTime = null;
      this.reconnectAttempt = 0;
      if (this.reconnectTimer !== null) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
    };

    ws.onmessage = (event) => {
      if (this.ws !== ws) return;
      let data: unknown;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!isRecord(data)) return;
      if (data['type'] === 'error' && data['code'] === 'duplicate_session') {
        this.stopped = true;
        this.reconnecting = false;
        this.reconnectStartTime = null;
        this.reconnectAttempt = 0;
        if (this.reconnectTimer !== null) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
        ws.close();
        this.ws = null;
        this.onDuplicateSessionHandler();
        return;
      }
      this.onMessageHandler(data);
    };

    ws.onerror = () => {
      // onclose fires after onerror; reconnect logic lives in onclose
    };

    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnecting || this.stopped) return;
    this.reconnecting = true;

    if (this.reconnectStartTime === null) {
      this.reconnectStartTime = Date.now();
      this.reconnectAttempt = 0;
    }

    const elapsed = Date.now() - this.reconnectStartTime;
    if (elapsed >= RECONNECT_TIMEOUT_MS) {
      this.reconnecting = false;
      this.reconnectStartTime = null;
      this.reconnectAttempt = 0;
      this.onReconnectTimeoutHandler();
      return;
    }

    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempt), MAX_BACKOFF_MS);
    this.reconnectAttempt++;

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnecting = false;

      const elapsed2 = Date.now() - (this.reconnectStartTime ?? 0);
      if (elapsed2 >= RECONNECT_TIMEOUT_MS) {
        this.reconnectStartTime = null;
        this.reconnectAttempt = 0;
        this.onReconnectTimeoutHandler();
        return;
      }

      this.openSocket();
    }, delay);
  }
}
