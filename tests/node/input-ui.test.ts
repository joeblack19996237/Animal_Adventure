import { describe, it, expect } from 'vitest';
import {
  createInputState,
  applyKeyDown,
  applyKeyUp,
  getMovementVector,
  applyJoystickMove,
  applyJoystickRelease,
  WASD_KEYS,
  ARROW_KEYS,
} from '../../src/state/input';
import {
  createHudState,
  setButtonVisible,
  setQuestTimer,
  clearQuestTimer,
  setReconnectOverlay,
  hideReconnectOverlay,
} from '../../src/ui/hud';

describe('input_ui_state', () => {
  describe('keyboard input', () => {
    it('creates fresh state with no keys down', () => {
      const state = createInputState();
      expect(state.keysDown.size).toBe(0);
    });

    it('applyKeyDown registers a key', () => {
      const state = applyKeyDown(createInputState(), 'w');
      expect(state.keysDown.has('w')).toBe(true);
    });

    it('applyKeyUp removes a registered key', () => {
      const s1 = applyKeyDown(createInputState(), 'w');
      const s2 = applyKeyUp(s1, 'w');
      expect(s2.keysDown.has('w')).toBe(false);
    });

    it('WASD_KEYS contains all four wasd characters', () => {
      expect(WASD_KEYS).toContain('w');
      expect(WASD_KEYS).toContain('a');
      expect(WASD_KEYS).toContain('s');
      expect(WASD_KEYS).toContain('d');
    });

    it('ARROW_KEYS contains all four arrow key names', () => {
      expect(ARROW_KEYS).toContain('ArrowUp');
      expect(ARROW_KEYS).toContain('ArrowDown');
      expect(ARROW_KEYS).toContain('ArrowLeft');
      expect(ARROW_KEYS).toContain('ArrowRight');
    });

    it.each([
      { key: 'w', dx: 0, dy: -1 },
      { key: 'ArrowUp', dx: 0, dy: -1 },
      { key: 's', dx: 0, dy: 1 },
      { key: 'ArrowDown', dx: 0, dy: 1 },
      { key: 'a', dx: -1, dy: 0 },
      { key: 'ArrowLeft', dx: -1, dy: 0 },
      { key: 'd', dx: 1, dy: 0 },
      { key: 'ArrowRight', dx: 1, dy: 0 },
    ])('key $key produces movement dx=$dx dy=$dy', ({ key, dx, dy }) => {
      const state = applyKeyDown(createInputState(), key);
      const vec = getMovementVector(state);
      expect(vec.dx).toBe(dx);
      expect(vec.dy).toBe(dy);
    });

    it('no keys pressed returns zero movement vector', () => {
      const vec = getMovementVector(createInputState());
      expect(vec.dx).toBe(0);
      expect(vec.dy).toBe(0);
    });

    it('opposite horizontal keys cancel each other', () => {
      let state = applyKeyDown(createInputState(), 'a');
      state = applyKeyDown(state, 'd');
      expect(getMovementVector(state).dx).toBe(0);
    });

    it('opposite vertical keys cancel each other', () => {
      let state = applyKeyDown(createInputState(), 'w');
      state = applyKeyDown(state, 's');
      expect(getMovementVector(state).dy).toBe(0);
    });

    it('applyKeyDown does not mutate original state', () => {
      const original = createInputState();
      applyKeyDown(original, 'w');
      expect(original.keysDown.size).toBe(0);
    });
  });

  describe('touch joystick', () => {
    it('initial joystick state is inactive with zero deltas', () => {
      const state = createInputState();
      expect(state.joystick.active).toBe(false);
      expect(state.joystick.dx).toBe(0);
      expect(state.joystick.dy).toBe(0);
    });

    it('applyJoystickMove marks joystick active and stores deltas', () => {
      const state = applyJoystickMove(createInputState(), 0.5, -0.5);
      expect(state.joystick.active).toBe(true);
      expect(state.joystick.dx).toBe(0.5);
      expect(state.joystick.dy).toBe(-0.5);
    });

    it('applyJoystickRelease resets joystick to inactive zero state', () => {
      let state = applyJoystickMove(createInputState(), 1, 0);
      state = applyJoystickRelease(state);
      expect(state.joystick.active).toBe(false);
      expect(state.joystick.dx).toBe(0);
      expect(state.joystick.dy).toBe(0);
    });

    it('active joystick overrides keyboard in movement vector', () => {
      let state = applyKeyDown(createInputState(), 'w');
      state = applyJoystickMove(state, 0.7, 0.3);
      const vec = getMovementVector(state);
      expect(vec.dx).toBe(0.7);
      expect(vec.dy).toBe(0.3);
    });
  });

  describe('HUD button state', () => {
    it('interact button is hidden by default', () => {
      expect(createHudState().buttons.interact.visible).toBe(false);
    });

    it('shop button is hidden by default', () => {
      expect(createHudState().buttons.shop.visible).toBe(false);
    });

    it('inventory button is visible by default', () => {
      expect(createHudState().buttons.inventory.visible).toBe(true);
    });

    it('setButtonVisible shows a hidden button', () => {
      const state = setButtonVisible(createHudState(), 'interact', true);
      expect(state.buttons.interact.visible).toBe(true);
    });

    it('setButtonVisible hides a visible button', () => {
      const state = setButtonVisible(createHudState(), 'inventory', false);
      expect(state.buttons.inventory.visible).toBe(false);
    });

    it('setButtonVisible does not mutate original state', () => {
      const original = createHudState();
      setButtonVisible(original, 'shop', true);
      expect(original.buttons.shop.visible).toBe(false);
    });
  });

  describe('quest timer state', () => {
    it('quest timer is inactive with null expiresAt by default', () => {
      const state = createHudState();
      expect(state.questTimer.active).toBe(false);
      expect(state.questTimer.expiresAt).toBeNull();
    });

    it('setQuestTimer activates timer and stores expiresAt', () => {
      const expiresAt = '2026-05-16T12:00:00Z';
      const state = setQuestTimer(createHudState(), expiresAt);
      expect(state.questTimer.active).toBe(true);
      expect(state.questTimer.expiresAt).toBe(expiresAt);
    });

    it('clearQuestTimer deactivates timer and clears expiresAt', () => {
      let state = setQuestTimer(createHudState(), '2026-05-16T12:00:00Z');
      state = clearQuestTimer(state);
      expect(state.questTimer.active).toBe(false);
      expect(state.questTimer.expiresAt).toBeNull();
    });
  });

  describe('reconnect overlay state', () => {
    it('reconnect overlay is hidden with empty message by default', () => {
      const state = createHudState();
      expect(state.reconnect.visible).toBe(false);
      expect(state.reconnect.message).toBe('');
    });

    it('setReconnectOverlay shows overlay with the given message', () => {
      const msg = 'Server is temporarily unavailable. Please refresh the page.';
      const state = setReconnectOverlay(createHudState(), msg);
      expect(state.reconnect.visible).toBe(true);
      expect(state.reconnect.message).toBe(msg);
    });

    it('hideReconnectOverlay hides overlay and clears message', () => {
      let state = setReconnectOverlay(createHudState(), 'Reconnecting...');
      state = hideReconnectOverlay(state);
      expect(state.reconnect.visible).toBe(false);
      expect(state.reconnect.message).toBe('');
    });
  });
});
