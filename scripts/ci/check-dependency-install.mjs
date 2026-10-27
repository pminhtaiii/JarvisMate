import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
let cache;
try {
  if (process.argv.length !== 2) throw new Error('Usage: node scripts/ci/check-dependency-install.mjs');
  cache = mkdtempSync(join(tmpdir(), 'jarvismate-pnpm-metadata-'));
  const env = { ...process.env, PNPM_CONFIG_CACHE_DIR: cache };
  // pnpm v12 reads PNPM_CONFIG_ variables; npm_config_ no longer configures it.
  const options = { cwd: root, env, windowsHide: true, timeout: 600_000 };
  const windows = process.platform === 'win32';
  const location = spawnSync(windows ? 'cmd.exe' : 'pnpm', windows ? ['/d', '/s', '/c', 'pnpm cache path'] : ['cache', 'path'], { ...options, encoding: 'utf8' });
  if (location.error || location.status !== 0 || resolve(location.stdout.trim()) !== resolve(cache)) throw new Error('pnpm did not select the fresh metadata cache.');
  console.log('Dependency gate: frozen install with fresh metadata and lockfile policy verification');
  const result = spawnSync(windows ? 'cmd.exe' : 'pnpm', windows ? ['/d', '/s', '/c', 'pnpm install --frozen-lockfile --no-trust-lockfile'] : ['install', '--frozen-lockfile', '--no-trust-lockfile'], { ...options, stdio: 'inherit' });
  if (result.error || result.status !== 0) throw new Error(result.error?.message || `Fresh dependency install failed (${result.status})`);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  // Only remove the unique directory created by this invocation, never a shared cache.
  if (cache && dirname(resolve(cache)) === resolve(tmpdir())) rmSync(cache, { recursive: true, force: true });
}
