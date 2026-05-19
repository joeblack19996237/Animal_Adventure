export interface ChatServerMessage {
  type: 'chat_message';
  player_id: string;
  phrase_id: string;
  message: string;
}

export interface Phrase {
  id: string;
  text: string;
}

export interface ChatBubble {
  readonly playerId: string;
  readonly phraseId: string;
  readonly text: string;
  readonly receivedAt: number;
}

export interface ChatBubbleRendererOptions {
  phrases: Phrase[];
  bubbleDurationMs?: number;
  nowMs?: () => number;
}

const DEFAULT_BUBBLE_DURATION_MS = 4000;

export class ChatBubbleRenderer {
  private readonly phraseMap: ReadonlyMap<string, string>;
  private readonly bubbleDurationMs: number;
  private readonly nowMs: () => number;
  private readonly bubbles: Map<string, ChatBubble> = new Map();

  constructor(options: ChatBubbleRendererOptions) {
    this.phraseMap = new Map(options.phrases.map((p) => [p.id, p.text]));
    this.bubbleDurationMs = options.bubbleDurationMs ?? DEFAULT_BUBBLE_DURATION_MS;
    this.nowMs = options.nowMs ?? (() => Date.now());
  }

  handleChatMessage(msg: ChatServerMessage): void {
    const text = this.phraseMap.get(msg.phrase_id);
    if (text === undefined) return;
    this.bubbles.set(msg.player_id, {
      playerId: msg.player_id,
      phraseId: msg.phrase_id,
      text,
      receivedAt: this.nowMs(),
    });
  }

  getActiveBubble(playerId: string): ChatBubble | null {
    const bubble = this.bubbles.get(playerId);
    if (bubble === undefined) return null;
    if (this.nowMs() - bubble.receivedAt >= this.bubbleDurationMs) {
      this.bubbles.delete(playerId);
      return null;
    }
    return bubble;
  }

  getActivePlayers(): readonly string[] {
    const now = this.nowMs();
    const active: string[] = [];
    for (const [playerId, bubble] of this.bubbles) {
      if (now - bubble.receivedAt < this.bubbleDurationMs) {
        active.push(playerId);
      }
    }
    return active;
  }
}
