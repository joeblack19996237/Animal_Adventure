import { isTouchDevice } from '../../layout/device';

export class JoystickController {
  private el: HTMLDivElement | null = null;
  private active = false;
  private startX = 0;
  private startY = 0;

  constructor(
    private readonly radius: number,
    private readonly onMove: (dx: number, dy: number) => void,
    private readonly onRelease: () => void,
  ) {}

  create(): void {
    const base = document.createElement('div');
    base.id = 'joystick-base';
    const touch = isTouchDevice();
    base.style.cssText =
      `position:fixed;bottom:60px;left:60px;` +
      `width:${this.radius * 2}px;height:${this.radius * 2}px;` +
      `border-radius:50%;touch-action:none;z-index:100;` +
      (touch
        ? 'display:block;background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.25);'
        : 'display:none;background:transparent;border:0;pointer-events:none;');
    document.body.appendChild(base);
    this.el = base;

    base.addEventListener('pointerdown', (e: PointerEvent) => {
      e.preventDefault();
      base.setPointerCapture(e.pointerId);
      this.active = true;
      this.startX = e.clientX;
      this.startY = e.clientY;
      this.onMove(0, 0);
    });
    base.addEventListener('pointermove', (e: PointerEvent) => this.handleMove(e));
    base.addEventListener('pointerup', () => this.stop());
    base.addEventListener('pointercancel', () => this.stop());
  }

  destroy(): void {
    if (this.el?.parentElement) this.el.parentElement.removeChild(this.el);
    this.el = null;
  }

  private handleMove(e: PointerEvent): void {
    if (!this.active) return;
    const rawDx = e.clientX - this.startX;
    const rawDy = e.clientY - this.startY;
    const dist = Math.sqrt(rawDx * rawDx + rawDy * rawDy);
    if (dist === 0) {
      this.onMove(0, 0);
      return;
    }
    const clamp = Math.min(dist, this.radius);
    this.onMove((rawDx / dist) * (clamp / this.radius), (rawDy / dist) * (clamp / this.radius));
  }

  private stop(): void {
    this.active = false;
    this.onRelease();
  }
}
