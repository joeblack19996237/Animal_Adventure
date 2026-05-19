import * as fs from 'fs';
import * as path from 'path';

import { defineConfig } from 'vitest/config';

export default defineConfig({
  base: '/',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
  plugins: [
    {
      name: 'serve-project-dirs',
      configureServer(server) {
        // Return a function so this middleware runs AFTER Vite's own middleware.
        // This lets Vite transform JSON imports into JS modules first; our handler
        // only fires for direct fetch requests that Vite doesn't serve.
        return () => {
          server.middlewares.use((req, res, next) => {
            const urlPath = (req.url || '').split('?')[0];
            if (urlPath.startsWith('/assets/') || urlPath.startsWith('/config/')) {
              const filePath = path.resolve(process.cwd(), urlPath.slice(1));
              if (!filePath.startsWith(process.cwd() + path.sep)) { next(); return; }
              if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
                const ext = path.extname(filePath).toLowerCase();
                const mimeTypes: Record<string, string> = {
                  '.png': 'image/png',
                  '.jpg': 'image/jpeg',
                  '.jpeg': 'image/jpeg',
                  '.gif': 'image/gif',
                  '.webp': 'image/webp',
                  '.json': 'application/json',
                  '.svg': 'image/svg+xml',
                };
                res.setHeader('Content-Type', mimeTypes[ext] || 'application/octet-stream');
                fs.createReadStream(filePath).pipe(res);
                return;
              }
            }
            next();
          });
        };
      },
    },
  ],
  test: {
    exclude: ['**/node_modules/**', 'tests/e2e/**', 'workspace/**', '.pytest_cache/**', '.tmp/**'],
  },
});
