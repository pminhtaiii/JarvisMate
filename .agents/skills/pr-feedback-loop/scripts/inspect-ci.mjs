#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const helper = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../scripts/agents/pr-workflow.mjs');
const result = spawnSync(process.execPath, [helper, 'status', ...process.argv.slice(2)], {
  stdio: 'inherit',
  windowsHide: true,
});

if (result.error) {
  console.error(`Could not run PR status helper: ${result.error.message}`);
  process.exitCode = 1;
} else {
  process.exitCode = result.status ?? 1;
}
