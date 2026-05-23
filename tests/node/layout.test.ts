import { describe, expect, it } from 'vitest';
import { isTouchDevice } from '../../src/layout/device';
import {
  closeButtonSize,
  menuButtonSize,
  panelLayout,
  questDialogWidth,
} from '../../src/layout/gameUiLayout';

describe('game UI layout metrics', () => {
  it('detects touch devices from maxTouchPoints, user agent, or touch events', () => {
    expect(isTouchDevice({ navigator: { maxTouchPoints: 2, userAgent: '' } })).toBe(true);
    expect(isTouchDevice({ navigator: { maxTouchPoints: 0, userAgent: 'iPad' } })).toBe(true);
    expect(isTouchDevice({ navigator: { maxTouchPoints: 0, userAgent: '' }, hasTouchStart: true })).toBe(true);
    expect(isTouchDevice({ navigator: { maxTouchPoints: 0, userAgent: 'Windows Chrome' } })).toBe(false);
  });

  it('uses stable menu button sizes for desktop and touch', () => {
    expect(menuButtonSize(false)).toBe(88);
    expect(menuButtonSize(true)).toBe(80);
  });

  it('keeps close buttons above the 44px touch target without making them huge', () => {
    expect(closeButtonSize(true)).toBe(48);
    expect(closeButtonSize(false)).toBe(56);
  });

  it('keeps shop body below the large shop sign with panel-specific padding', () => {
    const desktop = panelLayout('shop', false);
    const touch = panelLayout('shop', true);

    expect(desktop.padding).toBe('126px 66px 78px');
    expect(touch.padding).toBe('116px 58px 72px');
    expect(desktop.bodyMaxHeight).toBe('270px');
    expect(touch.bodyMaxHeight).toBe('min(250px,32vh)');
  });

  it('uses narrower quest dialog width on touch viewports', () => {
    expect(questDialogWidth(false)).toBe('min(540px,78vw)');
    expect(questDialogWidth(true)).toBe('min(480px,88vw)');
  });
});
