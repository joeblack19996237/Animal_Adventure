export interface QuestReward {
  itemId: string;
  quantity: number;
}

export interface QuestOffer {
  npcId: string;
  questId: string;
  title: string;
  timeLimitSeconds: number;
  rewards: readonly QuestReward[];
}

export type QuestPanelState =
  | { readonly kind: 'idle' }
  | { readonly kind: 'offer'; readonly offer: QuestOffer }
  | { readonly kind: 'already_active' }
  | { readonly kind: 'active'; readonly questId: string; readonly expiresAt: string }
  | { readonly kind: 'completed'; readonly questId: string; readonly coinsAwarded: number }
  | { readonly kind: 'failed'; readonly questId: string };

export interface QuestPanelOptions {
  onAccept?: (questId: string) => void;
  nowMs?: () => number;
}

const ALREADY_ACTIVE_MESSAGE = 'You already have an active quest.';

export class QuestPanel {
  private state: QuestPanelState = { kind: 'idle' };

  private readonly onAccept: ((questId: string) => void) | undefined;

  private readonly nowMs: () => number;

  constructor(options: QuestPanelOptions = {}) {
    this.onAccept = options.onAccept;
    this.nowMs = options.nowMs ?? (() => Date.now());
  }

  getState(): QuestPanelState {
    return this.state;
  }

  isVisible(): boolean {
    return this.state.kind !== 'idle';
  }

  showOffer(offer: QuestOffer): void {
    this.state = { kind: 'offer', offer };
  }

  showAlreadyActive(): void {
    this.state = { kind: 'already_active' };
  }

  acceptOffer(): void {
    if (this.state.kind !== 'offer') return;
    this.onAccept?.(this.state.offer.questId);
  }

  startActive(questId: string, expiresAt: string): void {
    this.state = { kind: 'active', questId, expiresAt };
  }

  showCompleted(questId: string, coinsAwarded: number): void {
    this.state = { kind: 'completed', questId, coinsAwarded };
  }

  showFailed(questId: string): void {
    this.state = { kind: 'failed', questId };
  }

  dismiss(): void {
    this.state = { kind: 'idle' };
  }

  getCountdownSeconds(): number | null {
    if (this.state.kind !== 'active') return null;
    const expiresMs = new Date(this.state.expiresAt).getTime();
    return Math.max(0, Math.ceil((expiresMs - this.nowMs()) / 1000));
  }

  getDisplayMessage(): string | null {
    switch (this.state.kind) {
      case 'already_active':
        return ALREADY_ACTIVE_MESSAGE;
      case 'completed':
        return `Quest complete! You earned $${this.state.coinsAwarded}.`;
      case 'failed':
        return 'Quest failed.';
      default:
        return null;
    }
  }
}
