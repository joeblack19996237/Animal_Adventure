export interface Phrase {
  id: string;
  text: string;
}

export interface PresetChatMessage {
  type: 'preset_chat';
  player_id: string;
  phrase_id: string;
}

export interface PresetChatPanelOptions {
  phrases: Phrase[];
  playerId: string;
  onSend: (msg: PresetChatMessage) => void;
}

export class PresetChatPanel {
  private readonly phrases: readonly Phrase[];
  private readonly playerId: string;
  private readonly onSend: (msg: PresetChatMessage) => void;
  private visible = false;

  constructor(options: PresetChatPanelOptions) {
    this.phrases = [...options.phrases];
    this.playerId = options.playerId;
    this.onSend = options.onSend;
  }

  getPhrases(): readonly Phrase[] {
    return this.phrases;
  }

  sendPhrase(phraseId: string): void {
    const phrase = this.phrases.find((p) => p.id === phraseId);
    if (phrase === undefined) return;
    this.onSend({ type: 'preset_chat', player_id: this.playerId, phrase_id: phraseId });
  }

  show(): void {
    this.visible = true;
  }

  hide(): void {
    this.visible = false;
  }

  isVisible(): boolean {
    return this.visible;
  }
}
