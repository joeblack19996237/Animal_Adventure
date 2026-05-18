import { describe, it, expect } from 'vitest';
import {
  calcCanvasDimensions,
  calcCameraZoom,
  ZOOM_MIN,
  ZOOM_MAX,
} from '../../src/layout/responsive';

const VIEWPORTS = [
  { label: 'laptop', width: 1280, height: 800 },
  { label: 'iPad landscape', width: 1024, height: 768 },
  { label: 'iPad portrait', width: 768, height: 1024 },
  { label: 'small viewport', width: 360, height: 640 },
] as const;

describe('responsive_canvas_fits_viewport', () => {
  it.each(VIEWPORTS)(
    'canvas width does not exceed viewport width on $label',
    ({ width, height }) => {
      const dims = calcCanvasDimensions(width, height);
      expect(dims.width).toBeLessThanOrEqual(width);
    },
  );

  it.each(VIEWPORTS)(
    'canvas height does not exceed viewport height on $label',
    ({ width, height }) => {
      const dims = calcCanvasDimensions(width, height);
      expect(dims.height).toBeLessThanOrEqual(height);
    },
  );

  it.each(VIEWPORTS)(
    'canvas dimensions are positive on $label',
    ({ width, height }) => {
      const dims = calcCanvasDimensions(width, height);
      expect(dims.width).toBeGreaterThan(0);
      expect(dims.height).toBeGreaterThan(0);
    },
  );

  it('laptop canvas fills viewport exactly', () => {
    const dims = calcCanvasDimensions(1280, 800);
    expect(dims.width).toBe(1280);
    expect(dims.height).toBe(800);
  });

  it('iPad landscape canvas fills viewport exactly', () => {
    const dims = calcCanvasDimensions(1024, 768);
    expect(dims.width).toBe(1024);
    expect(dims.height).toBe(768);
  });

  it('small viewport canvas fills viewport exactly', () => {
    const dims = calcCanvasDimensions(360, 640);
    expect(dims.width).toBe(360);
    expect(dims.height).toBe(640);
  });
});

describe('camera_zoom_bounds', () => {
  it('ZOOM_MIN is 0.5', () => {
    expect(ZOOM_MIN).toBe(0.5);
  });

  it('ZOOM_MAX is 2.0', () => {
    expect(ZOOM_MAX).toBe(2.0);
  });

  it('zoom equals 1.0 when canvas matches world exactly', () => {
    const zoom = calcCameraZoom(800, 600, 800, 600);
    expect(zoom).toBeCloseTo(1.0);
  });

  it('zoom is clamped to ZOOM_MIN for a very large world', () => {
    const zoom = calcCameraZoom(360, 640, 100_000, 100_000);
    expect(zoom).toBe(ZOOM_MIN);
  });

  it('zoom is clamped to ZOOM_MAX for a very small world', () => {
    const zoom = calcCameraZoom(1280, 800, 10, 10);
    expect(zoom).toBe(ZOOM_MAX);
  });

  it('zoom is at least ZOOM_MIN when world is much larger than canvas', () => {
    const zoom = calcCameraZoom(360, 640, 10_000, 10_000);
    expect(zoom).toBeGreaterThanOrEqual(ZOOM_MIN);
  });

  it('zoom is at most ZOOM_MAX when world is much smaller than canvas', () => {
    const zoom = calcCameraZoom(1280, 800, 100, 100);
    expect(zoom).toBeLessThanOrEqual(ZOOM_MAX);
  });

  it('zoom fits the narrower canvas axis against the world', () => {
    // canvas 400x300, world 800x800: zoom = min(400/800, 300/800) = 0.375, clamped to 0.5
    const zoom = calcCameraZoom(400, 300, 800, 800);
    expect(zoom).toBe(ZOOM_MIN);
  });
});
