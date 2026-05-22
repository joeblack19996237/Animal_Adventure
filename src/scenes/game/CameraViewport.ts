export function chooseCameraZoom(): number {
  const nav = globalThis.navigator;
  const isTouchViewport =
    nav !== undefined &&
    (nav.maxTouchPoints > 0 || /iPad|iPhone|Android/i.test(nav.userAgent));
  return isTouchViewport ? 0.65 : 0.75;
}
