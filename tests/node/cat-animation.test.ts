import { describe, expect, it } from 'vitest';
import charactersConfig from '../../config/characters.json';

interface CharacterConfig {
  id: string;
  states: {
    walk: Record<string, string | string[] | boolean>;
  };
}

const characters = charactersConfig as CharacterConfig[];

describe('cat snowman directional walk animation config', () => {
  it('uses six frames per walk direction', () => {
    const cat = characters.find((character) => character.id === 'cat_snowman');
    expect(cat).toBeDefined();
    if (cat === undefined) return;

    for (const direction of ['front', 'back', 'left', 'right']) {
      const frames = cat.states.walk[direction];
      expect(Array.isArray(frames), `${direction} should use frame array`).toBe(true);
      expect(frames).toHaveLength(6);
      expect(frames).toEqual(
        Array.from({ length: 6 }, (_, index) => `character_cat_snowman_walk_${direction}_${index + 1}`),
      );
    }
  });

  it('does not mirror cat right movement now that right-facing frames exist', () => {
    const cat = characters.find((character) => character.id === 'cat_snowman');
    expect(cat?.states.walk['right_mirror']).toBe(false);
  });

  it('keeps non-cat characters compatible with single walk texture keys', () => {
    for (const id of ['penguin', 'arctic_fox']) {
      const character = characters.find((item) => item.id === id);
      expect(character).toBeDefined();
      expect(typeof character?.states.walk['front']).toBe('string');
    }
  });
});
