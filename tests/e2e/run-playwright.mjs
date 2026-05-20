import { spawn } from 'node:child_process';
import { createServer } from 'vite';

const serverUrl = 'http://localhost:5173';

async function isServerAlreadyRunning() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1000);
  try {
    const response = await fetch(serverUrl, { signal: controller.signal });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

async function startViteServer() {
  const server = await createServer({
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
    },
  });
  await server.listen();
  server.printUrls();
  return server;
}

function runPlaywright(args) {
  return new Promise((resolve) => {
    const child = spawn(
      process.execPath,
      ['./node_modules/@playwright/test/cli.js', 'test', ...args],
      { stdio: 'inherit' },
    );
    child.on('exit', (code, signal) => {
      if (typeof code === 'number') {
        resolve(code);
      } else {
        console.error(`Playwright exited from signal ${signal ?? 'unknown'}`);
        resolve(1);
      }
    });
    child.on('error', (err) => {
      console.error(err);
      resolve(1);
    });
  });
}

let server = null;
let exiting = false;

async function shutdown(code) {
  if (exiting) return;
  exiting = true;
  if (server !== null) {
    await server.close();
  }
  process.exit(code);
}

process.on('SIGINT', () => {
  void shutdown(130);
});
process.on('SIGTERM', () => {
  void shutdown(143);
});

if (!(await isServerAlreadyRunning())) {
  server = await startViteServer();
}

const exitCode = await runPlaywright(process.argv.slice(2));
await shutdown(exitCode);
