import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, realpath, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const sessionCli = join(root, 'scripts/agents/agent-work.mjs');
const taskCli = join(root, 'scripts/agents/active-task.mjs');

async function fixture(t) {
  const checkout = await realpath(await mkdtemp(join(tmpdir(), 'session-lifecycle-')));
  t.after(() => rm(checkout, { recursive: true, force: true }));
  await mkdir(join(checkout, 'context'));
  await writeFile(join(checkout, 'context/active_task.md'), '# Active task\n<!-- active-task:start -->\n```json\n[]\n```\n<!-- active-task:end -->\n');
  const initialized = spawnSync('git', ['init', '--quiet', '-b', 'main', checkout], { encoding: 'utf8', windowsHide: true });
  assert.equal(initialized.status, 0, initialized.stderr);
  return checkout;
}

function run(cli, checkout, ...args) {
  return spawnSync(process.execPath, [cli, ...args, '--root', checkout], {
    encoding: 'utf8', windowsHide: true, timeout: 10_000,
  });
}

function startSession(checkout, id) {
  const result = run(sessionCli, checkout, 'start', '--session', id, '--date', '2026-10-21');
  assert.equal(result.status, 0, result.stderr);
}

test('new assignments require explicit sessions and workers must declare owned paths', async (t) => {
  const checkout = await fixture(t);
  const missingSession = run(taskCli, checkout, 'start', '--owner', 'coordinator', '--task', 'T001', '--summary', 'Work', '--next', 'Verify');
  assert.equal(missingSession.status, 1);
  assert.match(missingSession.stderr, /Session must be date\/id/);
  const missingPaths = run(taskCli, checkout, 'start', '--owner', 'worker', '--task', 'T002', '--role', 'worker', '--session', '2026-10-21/worker', '--summary', 'Work', '--next', 'Verify');
  assert.equal(missingPaths.status, 1);
  assert.match(missingPaths.stderr, /requires at least one --owned-path/);
});

test('finishing one session ignores another explicit session assignment in the same checkout', async (t) => {
  const checkout = await fixture(t);
  startSession(checkout, 'target');
  const assignment = run(taskCli, checkout, 'start', '--owner', 'other-worker', '--task', 'T002', '--session', '2026-10-21/other', '--summary', 'Other session work', '--next', 'Continue in its session');
  assert.equal(assignment.status, 0, assignment.stderr);

  const finished = run(sessionCli, checkout, 'finish', '--session', '2026-10-21/target');
  assert.equal(finished.status, 0, finished.stderr);
  const tasks = JSON.parse(await readFile(join(checkout, '.agent-work/state/active-tasks.json'), 'utf8'));
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].session, '2026-10-21/other');
  assert.equal(tasks[0].status, 'active');
});

test('an assignment in its own session blocks finish and names the exact owner/task', async (t) => {
  const checkout = await fixture(t);
  startSession(checkout, 'owned');
  const assignment = run(taskCli, checkout, 'start', '--owner', 'own-worker', '--task', 'T003', '--session', '2026-10-21/owned', '--summary', 'Owned work', '--next', 'Finish tests');
  assert.equal(assignment.status, 0, assignment.stderr);

  const finished = run(sessionCli, checkout, 'finish', '--session', '2026-10-21/owned');
  assert.equal(finished.status, 1);
  assert.match(finished.stderr, /own-worker\/T003 \[active; session=2026-10-21\/owned; checkout=/);
  const tasks = JSON.parse(await readFile(join(checkout, '.agent-work/state/active-tasks.json'), 'utf8'));
  assert.equal(tasks[0].status, 'active');
});

test('reassignment retires the source session while active or blocked successor work still blocks', async (t) => {
  const checkout = await fixture(t);
  startSession(checkout, 'source');
  startSession(checkout, 'successor');
  let result = run(taskCli, checkout, 'start', '--owner', 'interrupted', '--task', 'T007', '--role', 'worker', '--session', '2026-10-21/source', '--summary', 'Continue the feature', '--next', 'Resume from checkpoint', '--owned-path', 'src/feature.ts');
  assert.equal(result.status, 0, result.stderr);
  result = run(taskCli, checkout, 'reassign', '--owner', 'interrupted', '--task', 'T007', '--new-owner', 'successor', '--session', '2026-10-21/successor', '--reason', 'Human-directed recovery');
  assert.equal(result.status, 0, result.stderr);
  let tasks = JSON.parse(await readFile(join(checkout, '.agent-work/state/active-tasks.json'), 'utf8'));
  const predecessor = tasks.find((entry) => entry.owner === 'interrupted');
  const successor = tasks.find((entry) => entry.owner === 'successor');
  assert.equal(predecessor.status, 'reassigned');
  assert.deepEqual(predecessor.binding.identity, { owner: 'interrupted', task: 'T007', session: '2026-10-21/source' });
  assert.equal(successor.checkout, checkout);
  assert.deepEqual(successor.binding.identity, { owner: 'successor', task: 'T007', session: '2026-10-21/successor' });
  assert.equal(successor.binding.base.ref, 'existing-checkout');
  assert.equal(successor.reservation, undefined, 'reassignment must not copy reservation authority');
  assert.equal(successor.readiness, undefined, 'reassignment must not copy readiness authority');

  result = run(sessionCli, checkout, 'finish', '--session', '2026-10-21/source');
  assert.equal(result.status, 0, result.stderr);

  result = run(sessionCli, checkout, 'finish', '--session', '2026-10-21/successor');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /successor\/T007 \[active; session=2026-10-21\/successor; checkout=/);

  result = run(taskCli, checkout, 'update', '--owner', 'successor', '--task', 'T007', '--status', 'blocked');
  assert.equal(result.status, 0, result.stderr);
  result = run(sessionCli, checkout, 'finish', '--session', '2026-10-21/successor');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /successor\/T007 \[blocked; session=2026-10-21\/successor; checkout=/);

  result = run(taskCli, checkout, 'handoff', '--owner', 'successor', '--task', 'T007', '--result', 'Successor work handed off');
  assert.equal(result.status, 0, result.stderr);
  tasks = JSON.parse(await readFile(join(checkout, '.agent-work/state/active-tasks.json'), 'utf8'));
  assert.equal(tasks.find((entry) => entry.owner === 'interrupted').status, 'reassigned', 'predecessor history remains retained');
  result = run(sessionCli, checkout, 'finish', '--session', '2026-10-21/successor');
  assert.equal(result.status, 0, result.stderr);
});

test('legacy assignments with unknown session remain conservative blockers', async (t) => {
  const checkout = await fixture(t);
  startSession(checkout, 'legacy-target');
  await mkdir(join(checkout, '.agent-work/state'), { recursive: true });
  await writeFile(join(checkout, '.agent-work/state/active-tasks.json'), JSON.stringify([
    { owner: 'legacy-worker', task: 'T004', checkout, summary: 'Older record', next: 'Recover evidence', status: 'blocked' },
    { owner: 'malformed-worker', task: 'T005', checkout, session: 'not-a-session', summary: 'Damaged record', next: 'Inspect the state', status: 'active' },
  ]));

  const finished = run(sessionCli, checkout, 'finish', '--session', '2026-10-21/legacy-target');
  assert.equal(finished.status, 1);
  assert.match(finished.stderr, /legacy-worker\/T004 \[blocked; session=unknown; checkout=/);
  assert.match(finished.stderr, /malformed-worker\/T005 \[active; session=not-a-session; checkout=/);
  const marker = JSON.parse(await readFile(join(checkout, '.agent-work/2026-10-21/legacy-target/session.json'), 'utf8'));
  assert.equal(marker.status, 'active');
});

test('legacy assignment checkout aliases still block session finish', async (t) => {
  const checkout = await fixture(t);
  startSession(checkout, 'legacy-alias');
  const aliases = await mkdtemp(join(tmpdir(), 'session-alias-'));
  t.after(() => rm(aliases, { recursive: true, force: true }));
  const alias = join(aliases, 'checkout');
  await symlink(checkout, alias, process.platform === 'win32' ? 'junction' : 'dir');
  await mkdir(join(checkout, '.agent-work/state'), { recursive: true });
  await writeFile(join(checkout, '.agent-work/state/active-tasks.json'), JSON.stringify([
    { owner: 'legacy-worker', task: 'T006', checkout: alias, session: 'unknown', summary: 'Older record', next: 'Recover evidence', status: 'active' },
  ]));

  const finished = run(sessionCli, checkout, 'finish', '--session', '2026-10-21/legacy-alias');
  assert.equal(finished.status, 1);
  assert.match(finished.stderr, /legacy-worker\/T006 \[active; session=unknown; checkout=/);
});
