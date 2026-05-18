export const WASD_KEYS = ['w', 'a', 's', 'd'] as const;
export const ARROW_KEYS = ['ArrowUp', 'ArrowLeft', 'ArrowDown', 'ArrowRight'] as const;

export type WasdKey = (typeof WASD_KEYS)[number];
export type ArrowKey = (typeof ARROW_KEYS)[number];

export interface JoystickState {
  readonly active: boolean;
  readonly dx: number;
  readonly dy: number;
}

export interface InputState {
  readonly keysDown: ReadonlySet<string>;
  readonly joystick: JoystickState;
}

export interface MovementVector {
  readonly dx: number;
  readonly dy: number;
}

export function createInputState(): InputState {
  return {
    keysDown: new Set<string>(),
    joystick: createJoystickState(),
  };
}

export function applyKeyDown(state: InputState, key: string): InputState {
  const keysDown = new Set<string>(state.keysDown);
  keysDown.add(key);
  return { ...state, keysDown };
}

export function applyKeyUp(state: InputState, key: string): InputState {
  const keysDown = new Set<string>(state.keysDown);
  keysDown.delete(key);
  return { ...state, keysDown };
}

export function getMovementVector(state: InputState): MovementVector {
  if (state.joystick.active) {
    return { dx: state.joystick.dx, dy: state.joystick.dy };
  }
  let dx = 0;
  let dy = 0;
  if (state.keysDown.has('a') || state.keysDown.has('ArrowLeft')) dx -= 1;
  if (state.keysDown.has('d') || state.keysDown.has('ArrowRight')) dx += 1;
  if (state.keysDown.has('w') || state.keysDown.has('ArrowUp')) dy -= 1;
  if (state.keysDown.has('s') || state.keysDown.has('ArrowDown')) dy += 1;
  return { dx, dy };
}

export function createJoystickState(): JoystickState {
  return { active: false, dx: 0, dy: 0 };
}

export function applyJoystickMove(state: InputState, dx: number, dy: number): InputState {
  return { ...state, joystick: { active: true, dx, dy } };
}

export function applyJoystickRelease(state: InputState): InputState {
  return { ...state, joystick: createJoystickState() };
}
