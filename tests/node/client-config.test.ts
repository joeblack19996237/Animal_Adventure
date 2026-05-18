import { describe, it, expect } from 'vitest';
import { buildClientConfig } from '../../src/config/clientConfig';

describe('client_config_origin_8080', () => {
  it('derives REST api URL from http localhost:8080 origin', () => {
    const config = buildClientConfig('http://localhost:8080');
    expect(config.apiUrl).toBe('http://localhost:8080');
  });

  it('derives ws URL from http localhost:8080 origin', () => {
    const config = buildClientConfig('http://localhost:8080');
    expect(config.wsUrl).toBe('ws://localhost:8080');
  });

  it('derives asset base path from http localhost:8080 origin', () => {
    const config = buildClientConfig('http://localhost:8080');
    expect(config.assetBasePath).toBe('http://localhost:8080/assets');
  });

  it('VITE_WS_URL override takes precedence over derived ws URL', () => {
    const config = buildClientConfig('http://localhost:8080', 'ws://custom:9000');
    expect(config.wsUrl).toBe('ws://custom:9000');
  });

  it('empty string VITE_WS_URL is ignored and falls back to derived URL', () => {
    const config = buildClientConfig('http://localhost:8080', '');
    expect(config.wsUrl).toBe('ws://localhost:8080');
  });
});

describe('client_config_origin_80', () => {
  it('derives REST api URL from http localhost:80 origin', () => {
    const config = buildClientConfig('http://localhost:80');
    expect(config.apiUrl).toBe('http://localhost:80');
  });

  it('derives ws URL from http localhost:80 origin', () => {
    const config = buildClientConfig('http://localhost:80');
    expect(config.wsUrl).toBe('ws://localhost:80');
  });

  it('derives asset base path from http localhost:80 origin', () => {
    const config = buildClientConfig('http://localhost:80');
    expect(config.assetBasePath).toBe('http://localhost:80/assets');
  });
});

describe('client_config_https', () => {
  it('maps https origin to wss WebSocket URL', () => {
    const config = buildClientConfig('https://example.com');
    expect(config.wsUrl).toBe('wss://example.com');
  });

  it('maps http origin to ws WebSocket URL', () => {
    const config = buildClientConfig('http://example.com');
    expect(config.wsUrl).toBe('ws://example.com');
  });

  it('VITE_WS_URL override wins over https-derived wss URL', () => {
    const config = buildClientConfig('https://example.com', 'wss://override:9000');
    expect(config.wsUrl).toBe('wss://override:9000');
  });

  it('unsupported protocol throws to block connection', () => {
    expect(() => buildClientConfig('ftp://example.com')).toThrow(
      'Unsupported protocol: ftp:',
    );
  });
});
