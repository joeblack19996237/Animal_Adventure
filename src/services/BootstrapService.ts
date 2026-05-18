export interface BootstrapConfig {
  map: unknown;
  map_tiles: unknown;
  npcs: unknown;
  quests: unknown;
  items: unknown;
  shop: unknown;
  characters: unknown;
  preset_phrases: unknown;
  progression: unknown;
  assets: unknown;
}

export type BootstrapResult =
  | { kind: 'ok'; config: BootstrapConfig }
  | { kind: 'error'; message: string };

const REQUIRED_KEYS: readonly (keyof BootstrapConfig)[] = [
  'map',
  'map_tiles',
  'npcs',
  'quests',
  'items',
  'shop',
  'characters',
  'preset_phrases',
  'progression',
  'assets',
];

type FetchFn = (url: string) => Promise<Response>;

export class BootstrapService {
  private readonly baseUrl: string;
  private readonly fetchFn: FetchFn;

  constructor(baseUrl: string, fetchFn?: FetchFn) {
    this.baseUrl = baseUrl;
    this.fetchFn = fetchFn ?? ((url) => globalThis.fetch(url));
  }

  async fetchConfig(): Promise<BootstrapResult> {
    let response: Response;
    try {
      response = await this.fetchFn(`${this.baseUrl}/api/v1/config/bootstrap`);
    } catch (err) {
      return {
        kind: 'error',
        message: err instanceof Error ? err.message : 'Network error',
      };
    }

    if (!response.ok) {
      return {
        kind: 'error',
        message: `Bootstrap config unavailable (status ${response.status})`,
      };
    }

    let data: unknown;
    try {
      data = await response.json();
    } catch {
      return { kind: 'error', message: 'Bootstrap response is not valid JSON' };
    }

    if (data === null || typeof data !== 'object' || Array.isArray(data)) {
      return { kind: 'error', message: 'Bootstrap response has unexpected format' };
    }

    const record = data as Record<string, unknown>;
    const missingKeys = REQUIRED_KEYS.filter((key) => !(key in record));

    if (missingKeys.length > 0) {
      return {
        kind: 'error',
        message: `Bootstrap config missing required keys: ${missingKeys.join(', ')}`,
      };
    }

    return {
      kind: 'ok',
      config: {
        map: record['map'],
        map_tiles: record['map_tiles'],
        npcs: record['npcs'],
        quests: record['quests'],
        items: record['items'],
        shop: record['shop'],
        characters: record['characters'],
        preset_phrases: record['preset_phrases'],
        progression: record['progression'],
        assets: record['assets'],
      },
    };
  }
}
