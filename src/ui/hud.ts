export type ButtonId = 'interact' | 'shop' | 'inventory';

export interface ButtonState {
  readonly visible: boolean;
}

export interface QuestTimerState {
  readonly active: boolean;
  readonly expiresAt: string | null;
}

export interface ReconnectOverlayState {
  readonly visible: boolean;
  readonly message: string;
}

export interface HudState {
  readonly buttons: Readonly<Record<ButtonId, ButtonState>>;
  readonly questTimer: QuestTimerState;
  readonly reconnect: ReconnectOverlayState;
}

const DEFAULT_BUTTONS: Readonly<Record<ButtonId, ButtonState>> = {
  interact: { visible: false },
  shop: { visible: false },
  inventory: { visible: true },
};

export function createHudState(): HudState {
  return {
    buttons: { ...DEFAULT_BUTTONS },
    questTimer: { active: false, expiresAt: null },
    reconnect: { visible: false, message: '' },
  };
}

export function setButtonVisible(state: HudState, button: ButtonId, visible: boolean): HudState {
  return {
    ...state,
    buttons: {
      ...state.buttons,
      [button]: { visible },
    },
  };
}

export function setQuestTimer(state: HudState, expiresAt: string): HudState {
  return {
    ...state,
    questTimer: { active: true, expiresAt },
  };
}

export function clearQuestTimer(state: HudState): HudState {
  return {
    ...state,
    questTimer: { active: false, expiresAt: null },
  };
}

export function setReconnectOverlay(state: HudState, message: string): HudState {
  return {
    ...state,
    reconnect: { visible: true, message },
  };
}

export function hideReconnectOverlay(state: HudState): HudState {
  return {
    ...state,
    reconnect: { visible: false, message: '' },
  };
}
