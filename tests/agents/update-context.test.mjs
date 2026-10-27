import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const cli = new URL('../../scripts/agents/update-context.mjs', import.meta.url);
const hash = (text) => createHash('sha256').update(text).digest('hex');
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'context-update-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, 'context'));
  await mkdir(join(root, 'docs'));
  await writeFile(join(root, 'AGENTS.md'), '[Context](context/README.md)\n');
  await writeFile(join(root, 'docs/progress-checker-matrices.md'), '# Criteria\n');
  await writeFile(join(root, 'context/contract.json'), JSON.stringify({ requiredDocuments: ['context/README.md'], facts: {}, authorizationReferences: [] }));
  await writeFile(join(root, 'context/README.md'), '[Architecture](architecture.md)\n[Progress](progress_checker.md)\n');
  const source = '# Architecture\r\n\r\n## Runtime\r\n\r\nPlanned runtime.\r\n';
  await writeFile(join(root, 'context/architecture.md'), source);
  await writeFile(join(root, 'context/progress_checker.md'), '# Progress\n\n| Area | Observation |\n|---|---|\n| Helpers | Old evidence |\n');
  const updates = [{ file: 'context/architecture.md', sha256: hash(source), edits: [{ oldText: 'Planned runtime.', newText: 'Implemented boundary; verification remains incomplete.' }] }];
  const plan = join(root, 'updates.json');
  const run = (apply = false) => spawnSync(process.execPath, [fileURLToPath(cli), '--root', root, '--updates', plan, ...(apply ? ['--apply'] : [])], { encoding: 'utf8', windowsHide: true });
  return { root, source, updates, run, save: () => writeFile(plan, JSON.stringify({ updates })) };
}

test('preview is read-only; apply updates architecture and progress while preserving their format', async (t) => {
  const f = await fixture(t);
  const path = join(f.root, 'context/progress_checker.md');
  const progress = await readFile(path, 'utf8');
  f.updates.push({ file: 'context/progress_checker.md', sha256: hash(progress), edits: [{ oldText: 'Old evidence', newText: 'CLI test passed; tests/agents/update-context.test.mjs' }] });
  await f.save();
  const preview = f.run();
  assert.equal(preview.status, 0, preview.stderr);
  assert.equal(await readFile(join(f.root, 'context/architecture.md'), 'utf8'), f.source);
  const applied = f.run(true);
  assert.equal(applied.status, 0, applied.stderr);
  assert.equal(await readFile(join(f.root, 'context/architecture.md'), 'utf8'), f.source.replace('Planned runtime.', 'Implemented boundary; verification remains incomplete.'));
  assert.equal(await readFile(path, 'utf8'), progress.replace('Old evidence', 'CLI test passed; tests/agents/update-context.test.mjs'));
  assert.notEqual(f.run(true).status, 0, 'reusing stale edits must fail');
});

test('invalid links roll back every file written by the run', async (t) => {
  const f = await fixture(t);
  const progressPath = join(f.root, 'context/progress_checker.md');
  const progress = await readFile(progressPath, 'utf8');
  f.updates.push({ file: 'context/progress_checker.md', sha256: hash(progress), edits: [{ oldText: 'Old evidence', newText: '[Missing](missing.md)' }] });
  await f.save();
  const result = f.run(true);
  assert.equal(result.status, 1, result.stderr);
  assert.match(result.stderr, /missing\.md/);
  assert.equal(await readFile(join(f.root, 'context/architecture.md'), 'utf8'), f.source);
  assert.equal(await readFile(progressPath, 'utf8'), progress);
});

test('stale, ambiguous, structural, and out-of-scope updates fail without changing context', async (t) => {
  for (const change of [
    (u) => { u.sha256 = '0'.repeat(64); },
    (u) => { u.edits[0].oldText = '\n'; },
    (u) => { u.edits[0] = { oldText: '## Runtime', newText: '## Replaced heading' }; },
    (u) => { u.file = '../AGENTS.md'; },
    (u) => { u.file = 'context/active_task.md'; },
  ]) {
    const f = await fixture(t);
    change(f.updates[0]);
    await f.save();
    const result = f.run(true);
    assert.equal(result.status, 1, result.stderr);
    assert.equal(await readFile(join(f.root, 'context/architecture.md'), 'utf8'), f.source);
  }
});

test('an empty update plan validates context and an existing updater lock is retained', async (t) => {
  const f = await fixture(t);
  f.updates.length = 0;
  await f.save();
  assert.equal(f.run(true).status, 0);
  const lock = join(f.root, 'context/.context-update.lock');
  await writeFile(lock, 'another writer');
  const busy = f.run(true);
  assert.equal(busy.status, 1);
  assert.match(busy.stderr, /busy/);
  assert.equal(await readFile(lock, 'utf8'), 'another writer');
});
