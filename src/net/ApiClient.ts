import { isLoginResponse, LoginResponse } from './protocol';

export interface LoginOkResult {
  kind: 'ok';
  data: LoginResponse;
}

export interface CharacterRequiredResult {
  kind: 'character_required';
}

export interface LoginErrorResult {
  kind: 'error';
  message: string;
}

export type LoginResult = LoginOkResult | CharacterRequiredResult | LoginErrorResult;

function isObj(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchFn: (url: string, init?: RequestInit) => Promise<Response>;

  constructor(
    baseUrl: string,
    fetchFn?: (url: string, init?: RequestInit) => Promise<Response>,
  ) {
    this.baseUrl = baseUrl;
    this.fetchFn = fetchFn ?? ((url, init) => globalThis.fetch(url, init));
  }

  async login(name: string, characterId?: string): Promise<LoginResult> {
    const trimmedName = name.trim();
    if (!trimmedName) {
      return { kind: 'error', message: 'Name must not be empty' };
    }

    const body: Record<string, string> = { name: trimmedName };
    if (characterId !== undefined) {
      body['character_id'] = characterId;
    }

    let response: Response;
    try {
      response = await this.fetchFn(`${this.baseUrl}/api/v1/players`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch (err) {
      return {
        kind: 'error',
        message: err instanceof Error ? err.message : 'Network error',
      };
    }

    let data: unknown;
    try {
      data = await response.json();
    } catch {
      return { kind: 'error', message: 'Invalid response format' };
    }

    if (response.ok) {
      if (isObj(data) && data['status'] === 'character_required') {
        return { kind: 'character_required' };
      }
      if (isLoginResponse(data)) {
        return { kind: 'ok', data };
      }
      return { kind: 'error', message: 'Unexpected response format' };
    }

    if (isObj(data) && data['detail'] === 'character_required') {
      return { kind: 'character_required' };
    }

    const message =
      isObj(data) && typeof data['detail'] === 'string'
        ? data['detail']
        : `Request failed with status ${response.status}`;
    return { kind: 'error', message };
  }
}
