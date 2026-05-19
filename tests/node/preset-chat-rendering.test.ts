import { describe, it, expect } from 'vitest';
import { ChatBubbleRenderer } from '../../src/ui/ChatBubbleRenderer';
import type { ChatServerMessage } from '../../src/ui/ChatBubbleRenderer';

const PHRASES = [
  { id: 'hello', text: 'Hello!' },
  { id: 'thanks', text: 'Thanks!' },
  { id: 'lets_go', text: "Let's go!" },
];

function chatMsg(player_id: string, phrase_id: string): ChatServerMessage {
  return { type: 'chat_message', player_id, phrase_id, message: '' };
}

describe('ChatBubbleRenderer — preset_chat_rendering', () => {
  describe('handleChatMessage', () => {
    it('shows phrase text for the correct player after receiving chat_message', () => {
      const renderer = new ChatBubbleRenderer({ phrases: PHRASES });
      renderer.handleChatMessage(chatMsg('p1', 'hello'));
      const bubble = renderer.getActiveBubble('p1');
      expect(bubble).not.toBeNull();
      expect(bubble?.text).toBe('Hello!');
      expect(bubble?.playerId).toBe('p1');
    });

    it('resolves display text from phrase_id lookup, not the raw message field', () => {
      const renderer = new ChatBubbleRenderer({ phrases: PHRASES });
      renderer.handleChatMessage({ type: 'chat_message', player_id: 'p2', phrase_id: 'thanks', message: 'server-text-ignored' });
      const bubble = renderer.getActiveBubble('p2');
      expect(bubble?.text).toBe('Thanks!');
      expect(bubble?.phraseId).toBe('thanks');
    });

    it('does not create a bubble for other players when receiving a targeted chat_message', () => {
      const renderer = new ChatBubbleRenderer({ phrases: PHRASES });
      renderer.handleChatMessage(chatMsg('p1', 'hello'));
      expect(renderer.getActiveBubble('p2')).toBeNull();
      expect(renderer.getActiveBubble('p3')).toBeNull();
    });

    it('ignores chat_message with unknown phrase_id and shows no bubble', () => {
      const renderer = new ChatBubbleRenderer({ phrases: PHRASES });
      renderer.handleChatMessage(chatMsg('p1', 'unknown_phrase'));
      expect(renderer.getActiveBubble('p1')).toBeNull();
    });

    it('supports multiple online players with independent bubbles', () => {
      const renderer = new ChatBubbleRenderer({ phrases: PHRASES });
      renderer.handleChatMessage(chatMsg('p1', 'hello'));
      renderer.handleChatMessage(chatMsg('p2', 'thanks'));
      renderer.handleChatMessage(chatMsg('p3', 'lets_go'));
      expect(renderer.getActiveBubble('p1')?.phraseId).toBe('hello');
      expect(renderer.getActiveBubble('p2')?.phraseId).toBe('thanks');
      expect(renderer.getActiveBubble('p3')?.phraseId).toBe('lets_go');
    });

    it('overwrites an older bubble for the same player on a new chat_message', () => {
      let fakeNow = 1000;
      const renderer = new ChatBubbleRenderer({ phrases: PHRASES, nowMs: () => fakeNow });
      renderer.handleChatMessage(chatMsg('p1', 'hello'));
      fakeNow = 2000;
      renderer.handleChatMessage(chatMsg('p1', 'thanks'));
      expect(renderer.getActiveBubble('p1')?.phraseId).toBe('thanks');
    });
  });

  describe('bubble expiry', () => {
    it('returns null for an expired bubble after duration elapses', () => {
      let fakeNow = 1000;
      const renderer = new ChatBubbleRenderer({ phrases: PHRASES, bubbleDurationMs: 4000, nowMs: () => fakeNow });
      renderer.handleChatMessage(chatMsg('p1', 'hello'));
      expect(renderer.getActiveBubble('p1')).not.toBeNull();
      fakeNow = 5001;
      expect(renderer.getActiveBubble('p1')).toBeNull();
    });

    it('remains active just before the expiry boundary', () => {
      let fakeNow = 1000;
      const renderer = new ChatBubbleRenderer({ phrases: PHRASES, bubbleDurationMs: 4000, nowMs: () => fakeNow });
      renderer.handleChatMessage(chatMsg('p1', 'hello'));
      fakeNow = 4999;
      expect(renderer.getActiveBubble('p1')).not.toBeNull();
    });
  });

  describe('getActivePlayers — online scoping', () => {
    it('returns all player ids with active chat bubbles', () => {
      const renderer = new ChatBubbleRenderer({ phrases: PHRASES });
      renderer.handleChatMessage(chatMsg('p1', 'hello'));
      renderer.handleChatMessage(chatMsg('p2', 'thanks'));
      const active = renderer.getActivePlayers();
      expect(active).toContain('p1');
      expect(active).toContain('p2');
      expect(active).toHaveLength(2);
    });

    it('excludes players whose bubbles have expired', () => {
      let fakeNow = 1000;
      const renderer = new ChatBubbleRenderer({ phrases: PHRASES, bubbleDurationMs: 4000, nowMs: () => fakeNow });
      renderer.handleChatMessage(chatMsg('p1', 'hello'));
      renderer.handleChatMessage(chatMsg('p2', 'thanks'));
      fakeNow = 5001;
      expect(renderer.getActivePlayers()).toHaveLength(0);
    });

    it('returns empty list when no chat messages have been received', () => {
      const renderer = new ChatBubbleRenderer({ phrases: PHRASES });
      expect(renderer.getActivePlayers()).toHaveLength(0);
    });
  });
});
