import assert from 'node:assert/strict';
import { execFile, spawnSync } from 'node:child_process';
import { access, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const cli = join(root, 'scripts/agents/active-task.mjs');

async function fixture(t) {
  const checkout = await mkdtemp(join(tmpdir(), 'active-task-'));
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

test('a worker handoff can be cleared without rewriting a legacy assignment view', async (t) => {
  const checkout = await fixture(t);
  const path = join(checkout, 'context/active_task.md');
  const baseline = await readFile(path, 'utf8');
  let result = run(checkout, 'start', '--role', 'worker', '--owner', 'parent', '--task', 'tracking', '--summary', 'Implement tracking', '--next', 'Verify changes');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(await readFile(path, 'utf8'), baseline);
  assert.match(run(checkout, 'list').stdout, /Implement tracking/);
  assert.equal(run(checkout, 'finish', '--owner', 'parent', '--task', 'tracking', '--result', 'Worker cannot complete contributor work').status, 1);
  result = run(checkout, 'handoff', '--owner', 'parent', '--task', 'tracking', '--result', 'Tests passed; evidence recorded');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(await readFile(path, 'utf8'), baseline);
  assert.equal(JSON.parse(run(checkout, 'list').stdout)[0].status, 'handed-off');
  assert.equal(run(checkout, 'render').status, 0);
  assert.equal(await readFile(path, 'utf8'), baseline);
  result = run(checkout, 'clear', '--owner', 'parent', '--task', 'tracking');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(await readFile(path, 'utf8'), baseline);
  assert.equal(run(checkout, 'render').status, 0);
  assert.equal(await readFile(path, 'utf8'), baseline);
});

test('active-task list keeps full JSON by default and offers compact owner/task/status filters', async (t) => {
  const checkout = await fixture(t);
  for (const owner of ['active-worker', 'blocked-worker']) {
    const result = run(checkout, 'start', '--role', 'worker', '--owner', owner, '--task', 'T001', '--summary', `${owner} assignment`, '--next', 'Run the focused checks');
    assert.equal(result.status, 0, result.stderr);
  }
  assert.equal(run(checkout, 'update', '--owner', 'blocked-worker', '--task', 'T001', '--status', 'blocked').status, 0);

  const full = JSON.parse(run(checkout, 'list').stdout);
  assert.deepEqual(full.map((entry) => entry.owner), ['active-worker', 'blocked-worker']);
  assert.equal(full[0].next, 'Run the focused checks');

  let result = run(checkout, 'list', '--compact');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Assignments: 2/);
  assert.match(result.stdout, /active-worker\/T001 \[active; worker\]/);
  assert.match(result.stdout, /blocked-worker\/T001 \[blocked; worker\]/);
  assert.doesNotMatch(result.stdout, /"verification"/);

  result = run(checkout, 'list', '--compact', '--owner', 'blocked-worker', '--task', 'T001', '--status', 'blocked');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Assignments: 1/);
  assert.match(result.stdout, /blocked-worker\/T001 \[blocked; worker\]/);
  assert.doesNotMatch(result.stdout, /active-worker/);

  result = run(checkout, 'list', '--owner', 'active-worker');
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout).map((entry) => entry.owner), ['active-worker']);
});

test('archive previews without writes then preserves evidence before targeted clearing and safe retries', async (t) => {
  const checkout = await fixture(t);
  await mkdir(join(checkout, 'docs/verification'), { recursive: true });
  for (const owner of ['done', 'busy', 'blocked']) {
    assert.equal(run(checkout, 'start', '--role', 'worker', '--owner', owner, '--task', 'T001', '--summary', `${owner} work`, '--next', 'Verify').status, 0);
  }
  assert.equal(run(checkout, 'update', '--owner', 'blocked', '--task', 'T001', '--status', 'blocked').status, 0);
  assert.equal(run(checkout, 'handoff', '--owner', 'done', '--task', 'T001', '--result', 'Checks passed at revision abc').status, 0);
  const args = ['archive', '--owner', 'done', '--task', 'T001', '--output', 'docs/verification/done.json'];
  const before = run(checkout, 'list').stdout;
  let result = run(checkout, ...args);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).applied, false);
  assert.equal(run(checkout, 'list').stdout, before);
  await assert.rejects(access(join(checkout, 'docs/verification/done.json')), { code: 'ENOENT' });
  result = run(checkout, ...args, '--apply');
  assert.equal(result.status, 0, result.stderr);
  const archived = await readFile(join(checkout, 'docs/verification/done.json'), 'utf8');
  assert.equal(JSON.parse(archived).entries[0].result, 'Checks passed at revision abc');
  assert.deepEqual(JSON.parse(run(checkout, 'list').stdout).map((entry) => entry.owner), ['busy', 'blocked']);
  result = run(checkout, ...args, '--apply');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(await readFile(join(checkout, 'docs/verification/done.json'), 'utf8'), archived);
  for (const owner of ['busy', 'blocked']) assert.equal(run(checkout, 'archive', '--owner', owner, '--task', 'T001', '--output', 'docs/verification/no.json', '--apply').status, 1);
});

test('archive refuses unsafe destinations, collisions, and a busy store without clearing evidence', async (t) => {
  const checkout = await fixture(t);
  await mkdir(join(checkout, 'docs/verification'), { recursive: true });
  run(checkout, 'start', '--role', 'worker', '--owner', 'done', '--task', 'T001', '--summary', 'Work', '--next', 'Verify');
  run(checkout, 'handoff', '--owner', 'done', '--task', 'T001', '--result', 'Original result');
  const before = run(checkout, 'list').stdout;
  const args = ['archive', '--owner', 'done', '--task', 'T001'];
  await writeFile(join(checkout, 'docs/verification/collision.json'), '{"unrelated":"retain"}\n');
  for (const output of ['../escape.json', '.agent-work/archive.json', 'context/active_task.md', 'docs/verification/collision.json']) {
    assert.equal(run(checkout, ...args, '--output', output, '--apply').status, 1);
    assert.equal(run(checkout, 'list').stdout, before);
  }
  await writeFile(join(checkout, '.agent-work/state/active-task.lock'), 'other writer');
  assert.equal(run(checkout, ...args, '--output', 'docs/verification/new.json', '--apply').status, 1);
  await assert.rejects(access(join(checkout, 'docs/verification/new.json')), { code: 'ENOENT' });
  await rm(join(checkout, '.agent-work/state/active-task.lock'));
  const outside = await fixture(t);
  await rm(join(checkout, 'docs/verification'), { recursive: true });
  await symlink(outside, join(checkout, 'docs/verification'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.equal(run(checkout, ...args, '--output', 'docs/verification/escape.json', '--apply').status, 1);
  assert.equal(run(checkout, 'list').stdout, before);
});

test('archive resumes after saving evidence and refuses a later task that reused the same ID', async (t) => {
  const checkout = await fixture(t);
  await mkdir(join(checkout, 'docs/verification'), { recursive: true });
  run(checkout, 'start', '--role', 'worker', '--owner', 'worker', '--task', 'T001', '--summary', 'First task', '--next', 'Verify');
  run(checkout, 'handoff', '--owner', 'worker', '--task', 'T001', '--result', 'First result');
  const entry = JSON.parse(run(checkout, 'list').stdout)[0];
  const file = join(checkout, 'docs/verification/resume.json');
  await writeFile(file, JSON.stringify({ schemaVersion: 1, entries: [entry] }));
  const args = ['archive', '--owner', 'worker', '--task', 'T001', '--output', 'docs/verification/resume.json', '--apply'];
  assert.equal(run(checkout, ...args).status, 0);
  assert.deepEqual(JSON.parse(run(checkout, 'list').stdout), []);
  run(checkout, 'start', '--role', 'worker', '--owner', 'worker', '--task', 'T001', '--summary', 'Second task', '--next', 'Verify');
  run(checkout, 'handoff', '--owner', 'worker', '--task', 'T001', '--result', 'Second result');
  const before = run(checkout, 'list').stdout;
  assert.equal(run(checkout, ...args).status, 1);
  assert.equal(run(checkout, 'list').stdout, before);
  assert.equal(JSON.parse(await readFile(file, 'utf8')).entries[0].result, 'First result');
});

test('worker cleanup preserves the parent entry and active or blocked work', async (t) => {
  const checkout = await fixture(t);
  const path = join(checkout, 'context/active_task.md');
  for (const owner of ['parent', 'worker']) {
    const result = run(checkout, 'start', '--role', 'worker', '--owner', owner, '--task', 'T001', '--summary', `${owner} assignment`, '--next', 'Implement');
    assert.equal(result.status, 0, result.stderr);
  }
  let result = run(checkout, 'clear', '--owner', 'worker', '--task', 'T001');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Only completed, handed-off, or reassigned entries/);
  result = run(checkout, 'update', '--owner', 'worker', '--task', 'T001', '--status', 'blocked', '--next', 'Wait for required input', '--verification', 'Focused check not run');
  assert.equal(result.status, 0, result.stderr);
  const blocked = await readFile(path, 'utf8');
  assert.match(run(checkout, 'list').stdout, /Wait for required input/);
  result = run(checkout, 'clear', '--owner', 'worker', '--task', 'T001');
  assert.equal(result.status, 1);
  assert.equal(await readFile(path, 'utf8'), blocked);
  result = run(checkout, 'handoff', '--owner', 'worker', '--task', 'T001', '--result', 'Assignment complete; handoff in evidence.md');
  assert.equal(result.status, 0, result.stderr);
  assert.match(run(checkout, 'list').stdout, /Assignment complete/);
  result = run(checkout, 'clear', '--owner', 'worker', '--task', 'T001');
  assert.equal(result.status, 0, result.stderr);
  const retained = run(checkout, 'list').stdout;
  assert.match(retained, /parent assignment/);
  assert.doesNotMatch(retained, /worker assignment/);
});

test('damaged markers and malformed data fail without overwriting the file', async (t) => {
  const checkout = await fixture(t);
  const path = join(checkout, 'context/active_task.md');
  for (const source of [
    '# Preserve this\n<!-- active-task:start -->\n',
    '# Preserve this\n<!-- active-task:start -->\n```json\nnot json\n```\n<!-- active-task:end -->\n',
  ]) {
    await writeFile(path, source);
    const result = run(checkout, 'start', '--role', 'worker', '--owner', 'parent', '--task', 'T001', '--summary', 'Work', '--next', 'Verify');
    assert.equal(result.status, 1);
    assert.equal(await readFile(path, 'utf8'), source);
  }
});

test('a busy lock is retained and prevents any task-file mutation', async (t) => {
  const checkout = await fixture(t);
  const path = join(checkout, 'context/active_task.md');
  const baseline = await readFile(path, 'utf8');
  await mkdir(join(checkout, '.agent-work', 'state'), { recursive: true });
  const lock = join(checkout, '.agent-work/state/active-task.lock');
  await writeFile(lock, 'another writer');
  const result = run(checkout, 'start', '--role', 'worker', '--owner', 'parent', '--task', 'T001', '--summary', 'Work', '--next', 'Verify');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /file is busy/);
  assert.equal(await readFile(path, 'utf8'), baseline);
  assert.equal(await readFile(lock, 'utf8'), 'another writer');
});

test('linked worktrees share assignments and terminal render leaves the coordinator view alone', async (t) => {
  const checkout = await fixture(t);
  await writeFile(join(checkout, '.gitignore'), '.agent-work/\n');
  for (const args of [
    ['add', '.gitignore', 'context/active_task.md'],
    ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '-m', 'fixture'],
    ['worktree', 'add', '-b', 'worker', join(checkout, '.agent-work/worktrees/worker')],
  ]) {
    const result = spawnSync('git', args, { cwd: checkout, encoding: 'utf8', windowsHide: true });
    assert.equal(result.status, 0, result.stderr);
  }
  const parentView = await readFile(join(checkout, 'context/active_task.md'), 'utf8');
  const worker = join(checkout, '.agent-work/worktrees/worker');
  const workerView = await readFile(join(worker, 'context/active_task.md'), 'utf8');
  let result = run(worker, 'start', '--role', 'worker', '--owner', 'worker', '--task', 'T001', '--summary', 'Shared assignment', '--next', 'Verify');
  assert.equal(result.status, 0, result.stderr);
  result = run(checkout, 'list');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Shared assignment/);
  assert.equal(await readFile(join(checkout, 'context/active_task.md'), 'utf8'), parentView);
  assert.equal(await readFile(join(worker, 'context/active_task.md'), 'utf8'), workerView);
  result = run(checkout, 'render');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /worker\/T001/);
  assert.match(result.stdout, /Verify/);
  assert.equal(await readFile(join(checkout, 'context/active_task.md'), 'utf8'), parentView);
});

test('overlapping writers either serialize or report busy without losing an assignment', async (t) => {
  const checkout = await fixture(t);
  const execute = promisify(execFile);
  const assignments = ['worker-one', 'worker-two'].map((owner) => [
    'start', '--role', 'worker', '--owner', owner, '--task', 'T001', '--session', `2026-10-15/${owner}`, '--owned-path', 'src/example.ts', '--summary', owner, '--next', 'Verify',
  ]);
  const outcomes = await Promise.all(assignments.map((args) => execute(process.execPath, [cli, ...args, '--root', checkout], {
    windowsHide: true, timeout: 10_000,
  }).then(() => ({ status: 0 })).catch((error) => ({ status: error.code, stderr: error.stderr }))));
  for (let index = 0; index < outcomes.length; index += 1) {
    if (outcomes[index].status !== 0) {
      assert.equal(outcomes[index].status, 1, outcomes[index].stderr);
      assert.match(outcomes[index].stderr, /file is busy/);
      const retry = run(checkout, ...assignments[index]);
      assert.equal(retry.status, 0, retry.stderr);
    }
  }
  const source = run(checkout, 'list').stdout;
  assert.match(source, /worker-one/);
  assert.match(source, /worker-two/);
});

test('contributor finish refuses unpublished work and retains the active assignment', async (t) => {
  const checkout = await fixture(t);
  assert.equal(run(checkout, 'start', '--owner', 'coordinator', '--task', 'publish', '--summary', 'Contributor changes', '--next', 'Publish').status, 0);
  const before = run(checkout, 'list').stdout;
  assert.equal(run(checkout, 'handoff', '--owner', 'coordinator', '--task', 'publish', '--result', 'Skip PR').status, 1);
  const result = run(checkout, 'finish', '--owner', 'coordinator', '--task', 'publish', '--result', 'Implementation done');
  assert.equal(result.status, 1, result.stderr);
  assert.equal(run(checkout, 'list').stdout, before);
});
