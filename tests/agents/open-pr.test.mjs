import assert from 'node:assert/strict';
import test from 'node:test';
import { openPr } from '../../scripts/agents/open-pr.mjs';

const args = ['--remote', 'jarvismate', '--base', 'main', '--title', 'Add example feature', '--body-file', 'pr.md'];

function fixture({ failGate = false, existing = [] } = {}) {
  const calls = [];
  const execute = (binary, argv) => {
    calls.push([binary, ...argv]);
    if (binary === 'git' && argv[0] === 'remote') return 'git@github.com:owner/repo.git';
    if (binary === 'git' && argv[0] === 'branch') return 'feat/example-change';
    if (binary === 'git' && argv[0] === 'status') return '';
    if (binary === 'git' && argv[0] === 'rev-parse') return 'a'.repeat(40);
    if (binary === 'git' && argv[0] === 'merge-base') return 'a'.repeat(40);
    if (binary === 'gh') return JSON.stringify(existing);
    if (failGate && (binary === 'pnpm' || binary === 'cmd.exe')) throw new Error('gate failed');
    return '';
  };
  return { calls, execute };
}

test('accepts explicit JarvisMate remote and main base, runs gates, and creates a draft PR', async () => {
  const f = fixture();
  const result = await openPr(args, { root: process.cwd(), execute: f.execute });
  assert.equal(result.status, 'CREATED');
  assert.ok(f.calls.some(call => call.includes('push')));
  assert.ok(f.calls.some(call => call.includes('--draft')));
  assert.ok(f.calls.some(call => call.includes('--body-file')));
});

test('rejects a non-feature branch before any push', async () => {
  const f = fixture();
  const original = f.execute;
  f.execute = (binary, argv, root) => binary === 'git' && argv[0] === 'branch' ? 'main' : original(binary, argv, root);
  await assert.rejects(openPr(args, { root: process.cwd(), execute: f.execute }), /feat\/scope-description/);
  assert.equal(f.calls.some(call => call.includes('push')), false);
});

test('a failed local gate never pushes or creates a PR', async () => {
  const f = fixture({ failGate: true });
  await assert.rejects(openPr(args, { root: process.cwd(), execute: f.execute }), /gate failed/);
  assert.equal(f.calls.some(call => call.includes('push') || call.includes('create')), false);
});

test('a safe retry returns an existing PR without creating another', async () => {
  const f = fixture({ existing: [{ number: 12, url: 'https://github.com/owner/repo/pull/12', headRefName: 'feat/example-change', baseRefName: 'main', isDraft: true }] });
  const result = await openPr(args, { root: process.cwd(), execute: f.execute });
  assert.equal(result.status, 'EXISTING');
  assert.equal(f.calls.some(call => call[0] === 'gh' && call.includes('create')), false);
});

test('rejects a non GitHub remote before pushing', async () => {
  const f = fixture();
  const original = f.execute;
  f.execute = (binary, argv, root) => binary === 'git' && argv[0] === 'remote' ? 'https://example.com/repo.git' : original(binary, argv, root);
  await assert.rejects(openPr(args, { root: process.cwd(), execute: f.execute }), /GitHub repository/);
  assert.equal(f.calls.some(call => call.includes('push')), false);
});
