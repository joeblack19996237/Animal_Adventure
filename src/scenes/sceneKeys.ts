export const SCENE_KEYS = {
  BOOT: 'Boot',
  LOGIN: 'Login',
  PRELOAD: 'Preload',
  GAME: 'Game',
  UI: 'UI',
} as const;

export type SceneKey = (typeof SCENE_KEYS)[keyof typeof SCENE_KEYS];

export const REGISTERED_SCENE_KEYS: readonly string[] = [
  SCENE_KEYS.BOOT,
  SCENE_KEYS.LOGIN,
  SCENE_KEYS.PRELOAD,
  SCENE_KEYS.GAME,
  SCENE_KEYS.UI,
];
