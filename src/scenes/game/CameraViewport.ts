import { isTouchDevice } from '../../layout/device';

export function chooseCameraZoom(): number {
  return isTouchDevice() ? 0.58 : 0.66;
}
