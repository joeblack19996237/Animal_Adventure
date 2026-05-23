export type GamePanelName = 'friends' | 'shop' | 'inventory' | 'map';

export interface PanelLayoutMetrics {
  readonly width: string;
  readonly minHeight: string;
  readonly padding: string;
  readonly bodyMaxHeight: string;
}

export function menuButtonSize(isTouch: boolean): number {
  return isTouch ? 80 : 88;
}

export function closeButtonSize(isTouch: boolean): number {
  return isTouch ? 48 : 56;
}

export function panelLayout(name: GamePanelName, isTouch: boolean): PanelLayoutMetrics {
  if (name === 'shop') {
    return {
      width: isTouch ? 'min(560px,92vw)' : 'min(600px,86vw)',
      minHeight: isTouch ? '390px' : '420px',
      padding: isTouch ? '116px 58px 72px' : '126px 66px 78px',
      bodyMaxHeight: isTouch ? 'min(250px,32vh)' : '270px',
    };
  }

  if (name === 'map') {
    return {
      width: isTouch ? 'min(500px,88vw)' : 'min(560px,80vw)',
      minHeight: '360px',
      padding: isTouch ? '64px 58px 54px' : '68px 64px 56px',
      bodyMaxHeight: isTouch ? 'min(282px,38vh)' : '292px',
    };
  }

  return {
    width: isTouch ? 'min(520px,90vw)' : 'min(560px,86vw)',
    minHeight: '360px',
    padding: isTouch ? '64px 58px 54px' : '68px 64px 56px',
    bodyMaxHeight: isTouch ? 'min(292px,38vh)' : '292px',
  };
}

export function questDialogWidth(isTouch: boolean): string {
  return isTouch ? 'min(480px,88vw)' : 'min(540px,78vw)';
}
