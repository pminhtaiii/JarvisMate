import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const cli = join(root, 'scripts/agents/active-task.mjs');

async function fixture(t) {
  const checkout = await mkdtemp(join(tmpdir(), 'active-task-reassignment-'));
  t.after(() => rm(checkout, { recursive: true, force: true }));
  await mkdir(join(checkout, 'context'));
  await writeFile(join(checkout, 'context/active_task.md'), '# Active task\nPermanent instructions.\n<!-- active-task:start -->\n```json\n[]\n```\n<!-- active-task:end -->\nPermanent footer.\n');
  const initialized = spawnSync('git', ['init', '--quiet', checkout], { encoding: 'utf8', windowsHide: true });
  assert.equal(initialized.status, 0, initialized.stderr);
  return checkout;
}

function run(checkout, ...args) {
  if (args[0] === 'start') {
    if (!args.includes('--session')) args.push('--session', '2026-10-15/test');
    const roleIndex = args.indexOf('--role');
    if (roleIndex !== -1 && args[roleIndex + 1] === 'worker' && !args.includes('--owned-path')) args.push('--owned-path', 'src/example.ts');
  }
  return spawnSync(process.execPath, [cli, ...args, '--root', checkout], {
    encoding: 'utf8', windowsHide: true, timeout: 10_000,
  });
}

test('explicit reassignment preserves the original owner and evidence while creating a linked active assignment', async (t) => {
  const checkout = await fixture(t);
  await mkdir(join(checkout, 'docs/verification'), { recursive: true });
  run(checkout, 'start', '--role', 'worker', '--owner', 'interrupted', '--task', 'T001', '--session', '2026-10-15/old', '--summary', 'Implement feature', '--next', 'Resume from checkpoint', '--owned-path', 'src/feature.ts');
  run(checkout, 'update', '--owner', 'interrupted', '--task', 'T001', '--verification', 'First test passed');
  const result = run(checkout, 'reassign', '--owner', 'interrupted', '--task', 'T001', '--new-owner', 'successor', '--session', '2026-10-15/new', '--reason', 'Human-directed recovery after interruption');
  assert.equal(result.status, 0, result.stderr);
  const entries = JSON.parse(run(checkout, 'list').stdout);
  const original = entries.find((entry) => entry.owner === 'interrupted');
  const successor = entries.find((entry) => entry.owner === 'successor');
  assert.equal(original.status, 'reassigned');
  assert.equal(original.session, '2026-10-15/old');
  assert.equal(original.next, 'Resume from checkpoint');
  assert.equal(original.verification, 'First test passed');
  assert.equal(original.reassignments[0].owner, 'successor');
  assert.equal(successor.status, 'active');
  assert.equal(successor.session, '2026-10-15/new');
  assert.equal(successor.checkout, original.checkout);
  assert.deepEqual(successor.ownedPaths, ['src/feature.ts']);
  assert.equal(successor.reassignedFrom.owner, 'interrupted');
  assert.equal(successor.reassignedFrom.task, 'T001');
  assert.equal(successor.reassignedFrom.session, '2026-10-15/old');
  assert.equal(successor.reassignedFrom.status, 'active');
  assert.equal(successor.reassignedFrom.next, 'Resume from checkpoint');
  assert.equal(successor.reassignedFrom.verification, 'First test passed');
  assert.equal(successor.reassignedFrom.reason, 'Human-directed recovery after interruption');
  assert.equal(typeof successor.reassignedFrom.updatedAt, 'string');

  const compact = run(checkout, 'list', '--compact');
  assert.equal(compact.status, 0, compact.stderr);
  assert.match(compact.stdout, /successor\/T001 \[active; worker\]/);
  assert.doesNotMatch(compact.stdout, /interrupted/);
  const reassigned = run(checkout, 'list', '--status', 'reassigned');
  assert.equal(reassigned.status, 0, reassigned.stderr);
  assert.deepEqual(JSON.parse(reassigned.stdout).map((entry) => entry.owner), ['interrupted']);

  const archiveArgs = ['archive', '--owner', 'interrupted', '--task', 'T001', '--output', 'docs/verification/reassigned.json'];
  const preview = run(checkout, ...archiveArgs);
  assert.equal(preview.status, 0, preview.stderr);
  assert.equal(JSON.parse(preview.stdout).entry.status, 'reassigned');
  const archived = run(checkout, ...archiveArgs, '--apply');
  assert.equal(archived.status, 0, archived.stderr);
  const archivedSource = JSON.parse(await readFile(join(checkout, 'docs/verification/reassigned.json'), 'utf8')).entries[0];
  assert.equal(archivedSource.status, 'reassigned');
  assert.deepEqual(archivedSource.reassignments, original.reassignments);
  assert.equal(archivedSource.reassignments[0].owner, successor.owner);
  const retainedSuccessor = JSON.parse(run(checkout, 'list').stdout)[0];
  assert.equal(retainedSuccessor.owner, 'successor');
  assert.equal(retainedSuccessor.reassignedFrom.owner, archivedSource.owner);
  assert.equal(retainedSuccessor.reassignedFrom.task, archivedSource.task);
});

test('legacy blocked reassignment retires only through an explicit reason and keeps transfer evidence', async (t) => {
  const checkout = await fixture(t);
  await mkdir(join(checkout, '.agent-work/state'), { recursive: true });
  const source = {
    owner: 'interrupted', task: 'T001', checkout, session: '2026-10-15/old', role: 'worker',
    summary: 'Implement feature', next: 'Resume from checkpoint', verification: 'First test passed',
    ownedPaths: ['src/feature.ts'], status: 'blocked',
    reassignments: [{ owner: 'successor', task: 'T001', session: '2026-10-15/new', reason: 'Human-directed recovery', at: '2026-10-15T10:00:00.000Z' }],
  };
  const successor = {
    owner: 'successor', task: 'T001', checkout, session: '2026-10-15/new', role: 'worker',
    summary: 'Implement feature', next: 'Resume from checkpoint', verification: '',
    ownedPaths: ['src/feature.ts'], status: 'active',
    reassignedFrom: { owner: 'interrupted', task: 'T001', session: '2026-10-15/old' },
  };
  const ordinaryBlocked = {
    owner: 'blocked', task: 'T002', checkout, session: '2026-10-15/blocked', role: 'worker',
    summary: 'Separate work', next: 'Wait for input', status: 'blocked',
  };
  const statePath = join(checkout, '.agent-work/state/active-tasks.json');
  await writeFile(statePath, JSON.stringify([source, successor, ordinaryBlocked]));

  const missingReason = run(checkout, 'retire-reassigned', '--owner', 'interrupted', '--task', 'T001');
  assert.equal(missingReason.status, 1);
  assert.match(missingReason.stderr, /requires --reason/);
  assert.deepEqual(JSON.parse(await readFile(statePath, 'utf8')), [source, successor, ordinaryBlocked]);

  const unrelated = run(checkout, 'retire-reassigned', '--owner', 'blocked', '--task', 'T002', '--reason', 'No transfer was recorded');
  assert.equal(unrelated.status, 1);
  assert.match(unrelated.stderr, /recorded reassignment/);
  assert.deepEqual(JSON.parse(await readFile(statePath, 'utf8')), [source, successor, ordinaryBlocked]);

  const result = run(checkout, 'retire-reassigned', '--owner', 'interrupted', '--task', 'T001', '--reason', 'Confirm the recorded transfer is the recovery path');
  assert.equal(result.status, 0, result.stderr);
  const entries = JSON.parse(await readFile(statePath, 'utf8'));
  const retired = entries.find((entry) => entry.owner === 'interrupted');
  assert.equal(retired.status, 'reassigned');
  assert.deepEqual(retired.reassignments, source.reassignments);
  assert.equal(retired.reassignmentRetirement.reason, 'Confirm the recorded transfer is the recovery path');
  assert.equal(retired.result, undefined);
  assert.equal(entries.find((entry) => entry.owner === 'successor').status, 'active');
  assert.equal(entries.find((entry) => entry.owner === 'blocked').status, 'blocked');
});
