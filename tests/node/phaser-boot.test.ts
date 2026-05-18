import { describe, it, expect } from 'vitest';
import { REGISTERED_SCENE_KEYS, SCENE_KEYS } from '../../src/scenes/sceneKeys';

describe('phaser_boot_has_required_scenes', () => {
  it('includes Boot in registered scene keys', () => {
    expect(REGISTERED_SCENE_KEYS).toContain(SCENE_KEYS.BOOT);
  });

  it('includes Preload in registered scene keys', () => {
    expect(REGISTERED_SCENE_KEYS).toContain(SCENE_KEYS.PRELOAD);
  });

  it('includes Game in registered scene keys', () => {
    expect(REGISTERED_SCENE_KEYS).toContain(SCENE_KEYS.GAME);
  });

  it('includes UI in registered scene keys', () => {
    expect(REGISTERED_SCENE_KEYS).toContain(SCENE_KEYS.UI);
  });

  it('includes Login in registered scene keys', () => {
    expect(REGISTERED_SCENE_KEYS).toContain(SCENE_KEYS.LOGIN);
  });

  it('registers exactly five scenes', () => {
    expect(REGISTERED_SCENE_KEYS).toHaveLength(5);
  });

  it('Login key resolves to the string Login', () => {
    expect(SCENE_KEYS.LOGIN).toBe('Login');
  });

  it('Boot key resolves to the string Boot', () => {
    expect(SCENE_KEYS.BOOT).toBe('Boot');
  });

  it('Preload key resolves to the string Preload', () => {
    expect(SCENE_KEYS.PRELOAD).toBe('Preload');
  });

  it('Game key resolves to the string Game', () => {
    expect(SCENE_KEYS.GAME).toBe('Game');
  });

  it('UI key resolves to the string UI', () => {
    expect(SCENE_KEYS.UI).toBe('UI');
  });
});
