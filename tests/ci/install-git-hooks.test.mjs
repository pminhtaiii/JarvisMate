import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { installGitHooks } from '../../scripts/agents/install-git-hooks.mjs';

test('Git hook installation skips cleanly when the Git executable is unavailable', () => {
  const root = mkdtempSync(join(tmpdir(), 'git-hooks-no-git-'));
  const emptyPath = join(root, 'empty-bin');
  mkdirSync(emptyPath);
  const env = { ...process.env };
  const pathKey = Object.keys(env).find((key) => key.toLowerCase() === 'path') ?? 'PATH';
  env[pathKey] = emptyPath;

  try {
    assert.deepEqual(installGitHooks(root, env), { status: 'outside-git' });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
