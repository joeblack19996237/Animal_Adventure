import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

interface PackageJson {
  scripts?: Record<string, string>;
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
}

const REQUIRED_SCRIPTS = ['typecheck', 'test', 'build', 'test:e2e'] as const;

const REQUIRED_DEPENDENCY_PATTERNS: Record<string, string> = {
  Phaser: 'phaser',
  Vite: 'vite',
  TypeScript: 'typescript',
  Vitest: 'vitest',
  Playwright: '@playwright/test',
  ESLint: 'eslint',
  Prettier: 'prettier',
};

let pkg: PackageJson;

function readRootPackageJson(): PackageJson {
  const raw = readFileSync(join(process.cwd(), 'package.json'), 'utf-8');
  try {
    return JSON.parse(raw) as PackageJson;
  } catch (err) {
    throw new Error(`Failed to parse root package.json: ${String(err)}`);
  }
}

beforeAll(() => {
  pkg = readRootPackageJson();
});

describe('package_config_has_root_scripts', () => {
  it('exposes typecheck script', () => {
    expect(pkg.scripts).toBeDefined();
    expect(pkg.scripts?.['typecheck']).toBeDefined();
  });

  it('exposes test script', () => {
    expect(pkg.scripts).toBeDefined();
    expect(pkg.scripts?.['test']).toBeDefined();
  });

  it('exposes build script', () => {
    expect(pkg.scripts).toBeDefined();
    expect(pkg.scripts?.['build']).toBeDefined();
  });

  it('exposes test:e2e script', () => {
    expect(pkg.scripts).toBeDefined();
    expect(pkg.scripts?.['test:e2e']).toBeDefined();
  });

  it('exposes all required scripts', () => {
    const scripts = pkg.scripts ?? {};
    const missing = REQUIRED_SCRIPTS.filter((name) => scripts[name] === undefined);
    expect(missing).toEqual([]);
  });
});

describe('tooling_config_files_exist', () => {
  const ROOT = process.cwd();

  function rootFile(...segments: string[]): string {
    return join(ROOT, ...segments);
  }

  function eslintConfigExists(): boolean {
    return (
      existsSync(rootFile('.eslintrc.js')) ||
      existsSync(rootFile('.eslintrc.cjs')) ||
      existsSync(rootFile('.eslintrc.json')) ||
      existsSync(rootFile('.eslintrc.yml')) ||
      existsSync(rootFile('.eslintrc.yaml')) ||
      existsSync(rootFile('eslint.config.js')) ||
      existsSync(rootFile('eslint.config.mjs')) ||
      existsSync(rootFile('eslint.config.cjs'))
    );
  }

  function prettierConfigExists(): boolean {
    return (
      existsSync(rootFile('.prettierrc')) ||
      existsSync(rootFile('.prettierrc.js')) ||
      existsSync(rootFile('.prettierrc.json')) ||
      existsSync(rootFile('.prettierrc.yml')) ||
      existsSync(rootFile('.prettierrc.yaml')) ||
      existsSync(rootFile('prettier.config.js')) ||
      existsSync(rootFile('prettier.config.mjs'))
    );
  }

  it('tsconfig.json exists', () => {
    expect(existsSync(rootFile('tsconfig.json'))).toBe(true);
  });

  it('vite.config.ts exists', () => {
    expect(existsSync(rootFile('vite.config.ts'))).toBe(true);
  });

  it('playwright.config.ts exists', () => {
    expect(existsSync(rootFile('playwright.config.ts'))).toBe(true);
  });

  it('an ESLint config exists', () => {
    expect(eslintConfigExists()).toBe(true);
  });

  it('a Prettier config exists', () => {
    expect(prettierConfigExists()).toBe(true);
  });
});

describe('package_config_has_required_dependencies', () => {
  function isPresent(packageName: string): boolean {
    const deps = pkg.dependencies ?? {};
    const devDeps = pkg.devDependencies ?? {};
    return packageName in deps || packageName in devDeps;
  }

  it('includes Phaser dependency', () => {
    expect(isPresent(REQUIRED_DEPENDENCY_PATTERNS['Phaser'])).toBe(true);
  });

  it('includes Vite dependency', () => {
    expect(isPresent(REQUIRED_DEPENDENCY_PATTERNS['Vite'])).toBe(true);
  });

  it('includes TypeScript dependency', () => {
    expect(isPresent(REQUIRED_DEPENDENCY_PATTERNS['TypeScript'])).toBe(true);
  });

  it('includes Vitest dependency', () => {
    expect(isPresent(REQUIRED_DEPENDENCY_PATTERNS['Vitest'])).toBe(true);
  });

  it('includes Playwright dependency', () => {
    expect(isPresent(REQUIRED_DEPENDENCY_PATTERNS['Playwright'])).toBe(true);
  });

  it('includes ESLint dependency', () => {
    expect(isPresent(REQUIRED_DEPENDENCY_PATTERNS['ESLint'])).toBe(true);
  });

  it('includes Prettier dependency', () => {
    expect(isPresent(REQUIRED_DEPENDENCY_PATTERNS['Prettier'])).toBe(true);
  });

  it('includes all required tooling dependencies', () => {
    const missing = Object.entries(REQUIRED_DEPENDENCY_PATTERNS)
      .filter(([, packageName]) => !isPresent(packageName))
      .map(([label]) => label);
    expect(missing).toEqual([]);
  });
});
