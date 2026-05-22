import { formatCountdown } from './gameRecords';

export class QuestTimerController {
  private deadlineMs: number | null = null;
  private totalMs: number | null = null;
  private interval: ReturnType<typeof setInterval> | null = null;

  constructor(
    private readonly render: (text: string, ratio: number) => void,
    private readonly hide: () => void,
  ) {}

  start(expiresAtISO: string, serverTimeISO: string | null, serverTimeOffsetMs: number): void {
    this.clearIntervalOnly();
    this.totalMs = null;
    const expiresMs = new Date(expiresAtISO).getTime();
    if (serverTimeISO !== null) {
      const remainingMs = expiresMs - new Date(serverTimeISO).getTime();
      this.deadlineMs = Date.now() + remainingMs;
      this.totalMs = Math.max(remainingMs, 1);
    } else {
      this.deadlineMs = expiresMs + serverTimeOffsetMs;
      this.totalMs = Math.max(this.deadlineMs - Date.now(), 1);
    }
    this.tick();
    this.interval = setInterval(() => this.tick(), 1000);
  }

  stop(): void {
    this.clearIntervalOnly();
    this.deadlineMs = null;
    this.totalMs = null;
    this.hide();
  }

  private tick(): void {
    if (this.deadlineMs === null) return;
    const remainingMs = this.deadlineMs - Date.now();
    const ratio = this.totalMs === null ? 1 : Math.max(0, Math.min(1, remainingMs / this.totalMs));
    this.render(formatCountdown(remainingMs), ratio);
  }

  private clearIntervalOnly(): void {
    if (this.interval !== null) {
      clearInterval(this.interval);
      this.interval = null;
    }
  }
}
