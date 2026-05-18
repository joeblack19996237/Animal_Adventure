export interface ClientConfig {
  apiUrl: string;
  wsUrl: string;
  assetBasePath: string;
}

export function buildClientConfig(origin: string, explicitWsUrl?: string): ClientConfig {
  const protocol = new URL(origin).protocol;
  if (protocol !== 'http:' && protocol !== 'https:') {
    throw new Error(`Unsupported protocol: ${protocol}`);
  }

  const wsUrl =
    explicitWsUrl !== undefined && explicitWsUrl !== ''
      ? explicitWsUrl
      : origin.replace(/^http:\/\//, 'ws://').replace(/^https:\/\//, 'wss://');

  return {
    apiUrl: origin,
    wsUrl,
    assetBasePath: `${origin}/assets`,
  };
}

export function getClientConfig(): ClientConfig {
  const origin = window.location.origin;
  const raw: unknown = import.meta.env['VITE_WS_URL'];
  const explicitWsUrl = typeof raw === 'string' ? raw : undefined;
  return buildClientConfig(origin, explicitWsUrl);
}
