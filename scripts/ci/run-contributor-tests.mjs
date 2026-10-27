import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { contributorTestFiles } from './test-selection.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
try {
  const files = contributorTestFiles(root);
  const result = spawnSync(process.execPath, ['--test', ...files], { cwd: root, stdio: 'inherit', windowsHide: true });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exitCode = result.status ?? 1;
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
