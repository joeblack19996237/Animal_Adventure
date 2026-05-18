export interface CanvasDimensions {
  readonly width: number;
  readonly height: number;
}

export const ZOOM_MIN = 0.5;
export const ZOOM_MAX = 2.0;

export function calcCanvasDimensions(
  viewportWidth: number,
  viewportHeight: number,
): CanvasDimensions {
  return {
    width: Math.max(1, Math.floor(viewportWidth)),
    height: Math.max(1, Math.floor(viewportHeight)),
  };
}

export function calcCameraZoom(
  canvasWidth: number,
  canvasHeight: number,
  worldWidth: number,
  worldHeight: number,
): number {
  const rawZoom = Math.min(canvasWidth / worldWidth, canvasHeight / worldHeight);
  return Math.min(Math.max(rawZoom, ZOOM_MIN), ZOOM_MAX);
}
