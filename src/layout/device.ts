export interface TouchDeviceNavigator {
  readonly maxTouchPoints?: number;
  readonly userAgent?: string;
}

export interface TouchDeviceEnvironment {
  readonly navigator?: TouchDeviceNavigator;
  readonly hasTouchStart?: boolean;
}

export function isTouchDevice(env: TouchDeviceEnvironment = defaultTouchDeviceEnvironment()): boolean {
  const nav = env.navigator;
  return Boolean(
    env.hasTouchStart ||
      (nav?.maxTouchPoints ?? 0) > 0 ||
      /iPad|iPhone|Android/i.test(nav?.userAgent ?? ''),
  );
}

function defaultTouchDeviceEnvironment(): TouchDeviceEnvironment {
  const globalRecord = globalThis as unknown as Record<string, unknown>;
  const nav = globalRecord['navigator'] as TouchDeviceNavigator | undefined;
  return {
    navigator: nav,
    hasTouchStart: 'ontouchstart' in globalThis,
  };
}
