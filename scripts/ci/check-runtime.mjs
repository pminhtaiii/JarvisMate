import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
try {
  if (process.argv.length !== 2) throw new Error('Usage: node scripts/ci/check-runtime.mjs');
  const windows = process.platform === 'win32';
  const result = spawnSync(windows ? 'cmd.exe' : 'pnpm', windows ? ['/d', '/s', '/c', 'pnpm run lint'] : ['run', 'lint'], { cwd: root, stdio: 'inherit', windowsHide: true, timeout: 600_000 });
  if (result.error || result.status !== 0) throw new Error(result.error?.message || `Legacy runtime gate (repository lint) failed (${result.status})`);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
