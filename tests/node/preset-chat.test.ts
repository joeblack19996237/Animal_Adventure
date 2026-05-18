import { describe, expect, it, vi } from 'vitest';
import { PresetChatPanel } from '../../src/ui/PresetChatPanel';

const PHRASES = [
  { id: 'hello', text: 'Hello!' },
  { id: 'thanks', text: 'Thanks!' },
  { id: 'lets_go', text: "Let's go!" },
];

describe('PresetChatPanel', () => {
  describe('getPhrases', () => {
    it('returns all configured phrases', () => {
      const panel = new PresetChatPanel({ phrases: PHRASES, playerId: 'p1', onSend: vi.fn() });
      const phrases = panel.getPhrases();
      expect(phrases).toHaveLength(3);
      expect(phrases[0]).toEqual({ id: 'hello', text: 'Hello!' });
      expect(phrases[1]).toEqual({ id: 'thanks', text: 'Thanks!' });
      expect(phrases[2]).toEqual({ id: 'lets_go', text: "Let's go!" });
    });

    it('returns an empty list when configured with no phrases', () => {
      const panel = new PresetChatPanel({ phrases: [], playerId: 'p1', onSend: vi.fn() });
      expect(panel.getPhrases()).toHaveLength(0);
    });

    it('returns a snapshot unaffected by external mutation of the source array', () => {
      const phrases = [{ id: 'hello', text: 'Hello!' }];
      const panel = new PresetChatPanel({ phrases, playerId: 'p1', onSend: vi.fn() });
      phrases.push({ id: 'injected', text: 'Injected' });
      expect(panel.getPhrases()).toHaveLength(1);
    });
  });

  describe('sendPhrase', () => {
    it('calls onSend with a preset_chat message for a known phrase id', () => {
      const onSend = vi.fn();
      const panel = new PresetChatPanel({ phrases: PHRASES, playerId: 'p1', onSend });
      panel.sendPhrase('hello');
      expect(onSend).toHaveBeenCalledOnce();
      expect(onSend).toHaveBeenCalledWith({ type: 'preset_chat', player_id: 'p1', phrase_id: 'hello' });
    });

    it('sends the correct phrase_id for each configured phrase', () => {
      const onSend = vi.fn();
      const panel = new PresetChatPanel({ phrases: PHRASES, playerId: 'p1', onSend });
      panel.sendPhrase('thanks');
      expect(onSend).toHaveBeenCalledWith({ type: 'preset_chat', player_id: 'p1', phrase_id: 'thanks' });
      panel.sendPhrase('lets_go');
      expect(onSend).toHaveBeenCalledWith({ type: 'preset_chat', player_id: 'p1', phrase_id: 'lets_go' });
    });

    it('does not call onSend for an unknown phrase id', () => {
      const onSend = vi.fn();
      const panel = new PresetChatPanel({ phrases: PHRASES, playerId: 'p1', onSend });
      panel.sendPhrase('unknown_phrase');
      expect(onSend).not.toHaveBeenCalled();
    });

    it('includes the correct player_id in the outgoing message', () => {
      const onSend = vi.fn();
      const panel = new PresetChatPanel({ phrases: PHRASES, playerId: 'player_42', onSend });
      panel.sendPhrase('hello');
      expect(onSend).toHaveBeenCalledWith({ type: 'preset_chat', player_id: 'player_42', phrase_id: 'hello' });
    });
  });

  describe('visibility', () => {
    it('is hidden by default', () => {
      const panel = new PresetChatPanel({ phrases: PHRASES, playerId: 'p1', onSend: vi.fn() });
      expect(panel.isVisible()).toBe(false);
    });

    it('show makes the panel visible', () => {
      const panel = new PresetChatPanel({ phrases: PHRASES, playerId: 'p1', onSend: vi.fn() });
      panel.show();
      expect(panel.isVisible()).toBe(true);
    });

    it('hide makes the panel invisible after show', () => {
      const panel = new PresetChatPanel({ phrases: PHRASES, playerId: 'p1', onSend: vi.fn() });
      panel.show();
      panel.hide();
      expect(panel.isVisible()).toBe(false);
    });

    it('hide is a no-op when already hidden', () => {
      const panel = new PresetChatPanel({ phrases: PHRASES, playerId: 'p1', onSend: vi.fn() });
      panel.hide();
      expect(panel.isVisible()).toBe(false);
    });
  });
});
