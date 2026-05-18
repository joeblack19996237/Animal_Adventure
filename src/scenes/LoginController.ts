import type { ApiClient } from '../net/ApiClient';
import type { SessionState } from '../state/SessionState';

export type LoginStatus = 'idle' | 'loading' | 'character_select' | 'done' | 'error';

export interface LoginControllerState {
  readonly status: LoginStatus;
  readonly message: string;
  readonly pendingName: string | null;
}

type OnStateChange = (state: LoginControllerState) => void;

export class LoginController {
  private _status: LoginStatus = 'idle';
  private _message: string = '';
  private _pendingName: string | null = null;

  constructor(
    private readonly session: SessionState,
    private readonly api: ApiClient,
    private readonly _onStateChange: OnStateChange = () => {},
  ) {}

  get status(): LoginStatus {
    return this._status;
  }

  get message(): string {
    return this._message;
  }

  get pendingName(): string | null {
    return this._pendingName;
  }

  snapshot(): LoginControllerState {
    return {
      status: this._status,
      message: this._message,
      pendingName: this._pendingName,
    };
  }

  async submitName(name: string): Promise<void> {
    const trimmed = name.trim();
    if (!trimmed) {
      this._status = 'error';
      this._message = 'Please enter your name';
      this._onStateChange(this.snapshot());
      return;
    }

    this._status = 'loading';
    this._message = '';
    this._onStateChange(this.snapshot());

    const result = await this.api.login(trimmed);

    if (result.kind === 'character_required') {
      this._pendingName = trimmed;
      this._status = 'character_select';
      this._message = '';
      this.session.requireCharacterSelect(trimmed);
    } else if (result.kind === 'ok') {
      this._pendingName = null;
      this.session.beginLoading(result.data.player_id, result.data.character_id, result.data.name);
      this._status = 'done';
      this._message = '';
    } else {
      this._status = 'error';
      this._message = result.message;
    }

    this._onStateChange(this.snapshot());
  }

  async selectCharacter(charId: string): Promise<void> {
    if (this._pendingName === null) return;

    const nameToSend = this._pendingName;
    this._status = 'loading';
    this._message = '';
    this._onStateChange(this.snapshot());

    const result = await this.api.login(nameToSend, charId);

    if (result.kind === 'ok') {
      this._pendingName = null;
      this.session.beginLoading(result.data.player_id, result.data.character_id, result.data.name);
      this._status = 'done';
      this._message = '';
    } else if (result.kind === 'character_required') {
      this._status = 'character_select';
      this._message = 'Character selection required';
    } else {
      this._status = 'character_select';
      this._message = result.message;
    }

    this._onStateChange(this.snapshot());
  }
}
