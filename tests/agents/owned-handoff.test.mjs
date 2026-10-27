import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { captureOwnedHandoff, validateOwnedPaths, validateSessionRef, verifyOwnedHandoff } from '../../scripts/agents/owned-handoff.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const cli = join(root, 'scripts/agents/active-task.mjs');

function git(checkout, args) {
  const result = spawnSync('git', args, { cwd: checkout, encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 0, result.stderr);
}

async function repositoryFixture(t) {
  const checkout = await mkdtemp(join(tmpdir(), 'owned-handoff-'));
  t.after(() => rm(checkout, { recursive: true, force: true }));
  git(checkout, ['init', '--quiet', '-b', 'main']);
  git(checkout, ['config', 'core.autocrlf', 'false']);
  await mkdir(join(checkout, 'src'));
  await writeFile(join(checkout, 'src/feature.ts'), 'export const feature = 1;\n');
  await writeFile(join(checkout, 'notes.md'), 'Original note.\n');
  git(checkout, ['add', '.']);
  git(checkout, ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '-m', 'fixture']);
  return checkout;
}

test('owned-path validation rejects traversal, metadata, drive, and separator paths', () => {
  for (const path of ['../secret.txt', 'src/../../secret.txt', '.git/config', '.AGENT-WORK/state', 'C:/secret.txt', 'src/CON.txt', 'COM1', '\\\\server\\share\\secret.txt', 'src\\feature.ts', 'src/with\u0001control.ts']) {
    assert.throws(() => validateOwnedPaths([path]), /Unsafe owned path/);
  }
  assert.throws(() => validateOwnedPaths(['src/feature.ts', 'src/feature.ts']), /unique/);
  assert.throws(() => validateSessionRef('2026-10-21/CON'), /reserved/);
});

test('scoped snapshot separates index and worktree hashes and ignores unrelated edits', async (t) => {
  const checkout = await repositoryFixture(t);
  const assignment = { checkout, ownedPaths: ['src/feature.ts'] };
  await writeFile(join(checkout, 'src/feature.ts'), 'export const feature = 2;\n');
  git(checkout, ['add', 'src/feature.ts']);
  await writeFile(join(checkout, 'src/feature.ts'), 'export const feature = 3;\n');
  const evidence = await captureOwnedHandoff(assignment);
  assert.equal(evidence.status, 'verified');
  assert.notEqual(evidence.files[0].index[0].sha256, evidence.files[0].worktree.sha256);

  await writeFile(join(checkout, 'notes.md'), 'Unrelated staged edit.\n');
  git(checkout, ['add', 'notes.md']);
  await writeFile(join(checkout, 'unrelated.txt'), 'Untracked unrelated edit.\n');
  git(checkout, ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--only', '--quiet', '-m', 'unrelated change', '--', 'notes.md']);
  assert.equal((await verifyOwnedHandoff({ ...assignment, handoffEvidence: evidence })).verified, true);

  await writeFile(join(checkout, 'src/feature.ts'), 'export const feature = 4;\n');
  const changed = await verifyOwnedHandoff({ ...assignment, handoffEvidence: evidence });
  assert.equal(changed.verified, false);
  assert.equal(changed.status, 'changed');
  assert.deepEqual(changed.changedPaths, ['src/feature.ts']);
});

test('verification accepts staging the exact captured worktree bytes without rewriting index evidence', async (t) => {
  const checkout = await repositoryFixture(t);
  const assignment = { checkout, ownedPaths: ['src/feature.ts'] };
  await writeFile(join(checkout, 'src/feature.ts'), 'export const feature = 2;\n');
  const evidence = await captureOwnedHandoff(assignment);
  const originalIndex = structuredClone(evidence.files[0].index);
  assert.notEqual(originalIndex[0].sha256, evidence.files[0].worktree.sha256);

  git(checkout, ['add', 'src/feature.ts']);
  const verification = await verifyOwnedHandoff({ ...assignment, handoffEvidence: evidence });
  assert.equal(verification.verified, true);
  assert.deepEqual(verification.acceptedStagingPaths, ['src/feature.ts']);
  assert.deepEqual(evidence.files[0].index, originalIndex);
});

test('verification rejects altered staged bytes and changed worktree content', async (t) => {
  const checkout = await repositoryFixture(t);
  const assignment = { checkout, ownedPaths: ['src/feature.ts'] };
  await writeFile(join(checkout, 'src/feature.ts'), 'export const feature = 2;\n');
  const evidence = await captureOwnedHandoff(assignment);
  const handoff = { ...assignment, handoffEvidence: evidence };

  await writeFile(join(checkout, 'src/feature.ts'), 'export const feature = 3;\n');
  git(checkout, ['add', 'src/feature.ts']);
  await writeFile(join(checkout, 'src/feature.ts'), 'export const feature = 2;\n');
  const alteredIndex = await verifyOwnedHandoff(handoff);
  assert.equal(alteredIndex.verified, false);
  assert.deepEqual(alteredIndex.changedPaths, ['src/feature.ts']);
  assert.deepEqual(alteredIndex.acceptedStagingPaths, []);

  git(checkout, ['add', 'src/feature.ts']);
  const exactStaging = await verifyOwnedHandoff(handoff);
  assert.equal(exactStaging.verified, true);
  assert.deepEqual(exactStaging.acceptedStagingPaths, ['src/feature.ts']);

  await writeFile(join(checkout, 'src/feature.ts'), 'export const feature = 4;\n');
  const changedWorktree = await verifyOwnedHandoff(handoff);
  assert.equal(changedWorktree.verified, false);
  assert.deepEqual(changedWorktree.changedPaths, ['src/feature.ts']);
});

test('worker handoff records evidence and verify-handoff detects post-handoff edits', async (t) => {
  const checkout = await mkdtemp(join(tmpdir(), 'active-handoff-'));
  t.after(() => rm(checkout, { recursive: true, force: true }));
  await mkdir(join(checkout, 'context'));
  await mkdir(join(checkout, 'src'));
  await writeFile(join(checkout, 'context/active_task.md'), '# Active task\n<!-- active-task:start -->\n```json\n[]\n```\n<!-- active-task:end -->\n');
  await writeFile(join(checkout, 'src/owned.ts'), 'export const owned = true;\n');
  git(checkout, ['init', '--quiet', '-b', 'main']);
  const run = (...args) => spawnSync(process.execPath, [cli, ...args, '--root', checkout], { encoding: 'utf8', windowsHide: true, timeout: 10_000 });
  let result = run('start', '--owner', 'worker', '--task', 'T001', '--role', 'worker', '--session', '2026-10-21/worker', '--owned-path', 'src/owned.ts', '--summary', 'Implement owned file', '--next', 'Run focused check');
  assert.equal(result.status, 0, result.stderr);
  result = run('handoff', '--owner', 'worker', '--task', 'T001', '--result', 'Focused check passed');
  assert.equal(result.status, 0, result.stderr);
  result = run('verify-handoff', '--owner', 'worker', '--task', 'T001');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).verified, true);

  await writeFile(join(checkout, 'src/owned.ts'), 'export const owned = false;\n');
  result = run('verify-handoff', '--owner', 'worker', '--task', 'T001');
  assert.equal(result.status, 1);
  const verification = JSON.parse(result.stdout);
  assert.equal(verification.status, 'changed');
  assert.deepEqual(verification.changedPaths, ['src/owned.ts']);
});

test('legacy worker handoff remains unverified without inferred hashes', async (t) => {
  const checkout = await mkdtemp(join(tmpdir(), 'legacy-handoff-'));
  t.after(() => rm(checkout, { recursive: true, force: true }));
  await mkdir(join(checkout, 'context'));
  await mkdir(join(checkout, '.agent-work/state'), { recursive: true });
  await writeFile(join(checkout, 'context/active_task.md'), '# Active task\n<!-- active-task:start -->\n```json\n[]\n```\n<!-- active-task:end -->\n');
  await writeFile(join(checkout, '.agent-work/state/active-tasks.json'), JSON.stringify([
    { owner: 'legacy', task: 'T002', checkout, role: 'worker', summary: 'Old record', next: 'Review old changes', status: 'active' },
  ]));
  git(checkout, ['init', '--quiet', '-b', 'main']);
  const run = (...args) => spawnSync(process.execPath, [cli, ...args, '--root', checkout], { encoding: 'utf8', windowsHide: true, timeout: 10_000 });
  const handoff = run('handoff', '--owner', 'legacy', '--task', 'T002', '--result', 'Legacy result retained');
  assert.equal(handoff.status, 0, handoff.stderr);
  const entry = JSON.parse(run('list').stdout)[0];
  assert.equal(Object.hasOwn(entry, 'binding'), false);
  assert.equal(Object.hasOwn(entry, 'reservation'), false);
  assert.equal(entry.handoffEvidence.status, 'unverified');
  assert.equal(Object.hasOwn(entry.handoffEvidence, 'files'), false);
  const verification = run('verify-handoff', '--owner', 'legacy', '--task', 'T002');
  assert.equal(verification.status, 1);
  assert.equal(JSON.parse(verification.stdout).status, 'unverified');
});

test('an unbound reassigned worker cannot use the legacy handoff path', async (t) => {
  const checkout = await mkdtemp(join(tmpdir(), 'unbound-successor-'));
  t.after(() => rm(checkout, { recursive: true, force: true }));
  await mkdir(join(checkout, 'context'));
  await mkdir(join(checkout, '.agent-work/state'), { recursive: true });
  await writeFile(join(checkout, 'context/active_task.md'), '# Active task\n<!-- active-task:start -->\n```json\n[]\n```\n<!-- active-task:end -->\n');
  const path = join(checkout, '.agent-work/state/active-tasks.json');
  await writeFile(path, JSON.stringify([
    { owner: 'successor', task: 'T003', checkout, role: 'worker', session: '2026-10-22/successor', summary: 'Continue recovered work', next: 'Bind before handoff', status: 'active', reassignedFrom: { owner: 'legacy', task: 'T003', reason: 'Recovery' } },
  ]));
  git(checkout, ['init', '--quiet', '-b', 'main']);
  const run = (...args) => spawnSync(process.execPath, [cli, ...args, '--root', checkout], { encoding: 'utf8', windowsHide: true, timeout: 10_000 });
  const before = await readFile(path, 'utf8');
  const handoff = run('handoff', '--owner', 'successor', '--task', 'T003', '--result', 'Must bind first');
  assert.equal(handoff.status, 1);
  assert.match(handoff.stderr, /unbound reassigned|fresh binding/i);
  assert.equal(await readFile(path, 'utf8'), before, 'rejected successor handoff must not mutate the registry');
});
