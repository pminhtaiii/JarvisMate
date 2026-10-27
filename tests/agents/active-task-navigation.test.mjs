import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { access, mkdir, mkdtemp, readFile, readdir, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const cli = join(root, 'scripts/agents/active-task.mjs');
const workCli = join(root, 'scripts/agents/agent-work.mjs');

function legacyPage(entries) {
  return `# Active task\n<!-- active-task:start -->\n\`\`\`json\n${JSON.stringify(entries, null, 2)}\n\`\`\`\n<!-- active-task:end -->\n`;
}

async function fixture(t, page = legacyPage([])) {
  const checkout = await mkdtemp(join(tmpdir(), 'active-task-nav-'));
  t.after(() => rm(checkout, { recursive: true, force: true }));
  await mkdir(join(checkout, 'context'));
  await writeFile(join(checkout, 'context/active_task.md'), page);
  const initialized = spawnSync('git', ['init', '--quiet', checkout], { encoding: 'utf8', windowsHide: true });
  assert.equal(initialized.status, 0, initialized.stderr);
  return checkout;
}

function run(checkout, ...args) {
  if (args[0] === 'start') {
    if (!args.includes('--session')) args.push('--session', '2026-10-15/test');
    if (args.includes('--role') && args[args.indexOf('--role') + 1] === 'worker' && !args.includes('--owned-path')) args.push('--owned-path', 'src/example.ts');
  }
  return spawnSync(process.execPath, [cli, ...args, '--root', checkout], { encoding: 'utf8', windowsHide: true, timeout: 10_000 });
}

function runWork(checkout, ...args) {
  return spawnSync(process.execPath, [workCli, ...args, '--root', checkout], { encoding: 'utf8', windowsHide: true, timeout: 10_000 });
}

async function addLegacyWorktree(t, checkout, entries) {
  const linked = join(dirname(checkout), `${basename(checkout)}-legacy`);
  const add = spawnSync('git', ['add', 'context/active_task.md'], { cwd: checkout, encoding: 'utf8', windowsHide: true });
  assert.equal(add.status, 0, add.stderr);
  const commit = spawnSync('git', ['-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '--quiet', '-m', 'legacy task view'], { cwd: checkout, encoding: 'utf8', windowsHide: true });
  assert.equal(commit.status, 0, commit.stderr);
  const added = spawnSync('git', ['worktree', 'add', '--quiet', '-b', `legacy-${basename(checkout)}`, linked, 'HEAD'], { cwd: checkout, encoding: 'utf8', windowsHide: true });
  assert.equal(added.status, 0, added.stderr);
  t.after(async () => {
    spawnSync('git', ['worktree', 'remove', '--force', linked], { cwd: checkout, encoding: 'utf8', windowsHide: true });
    await rm(linked, { recursive: true, force: true });
  });
  await writeFile(join(linked, 'context/active_task.md'), legacyPage(entries));
  return linked;
}

test('routine lifecycle commands work with a navigation-only page and never rewrite it', async (t) => {
  const navigation = '# Active task\n\nUse `active-task.mjs list --compact` for current work.\n';
  const checkout = await fixture(t, navigation);
  const path = join(checkout, 'context/active_task.md');
  await mkdir(join(checkout, 'docs/verification'), { recursive: true });

  let result = run(checkout, 'start', '--role', 'worker', '--owner', 'first-worker', '--task', 'T001', '--summary', 'Implement navigation', '--next', 'Run focused checks');
  assert.equal(result.status, 0, result.stderr);
  result = run(checkout, 'update', '--owner', 'first-worker', '--task', 'T001', '--next', 'Verify migration', '--verification', 'Focused checks are ready');
  assert.equal(result.status, 0, result.stderr);
  assert.match(run(checkout, 'list', '--compact').stdout, /first-worker\/T001/);
  result = run(checkout, 'finish', '--owner', 'first-worker', '--task', 'T001', '--result', 'Worker handoff');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Workers return results with handoff/);

  result = run(checkout, 'reassign', '--owner', 'first-worker', '--task', 'T001', '--new-owner', 'second-worker', '--session', '2026-10-16/successor', '--reason', 'Continue the assigned work');
  assert.equal(result.status, 0, result.stderr);
  result = run(checkout, 'handoff', '--owner', 'second-worker', '--task', 'T001', '--result', 'Focused checks passed');
  assert.equal(result.status, 0, result.stderr);
  result = run(checkout, 'archive', '--owner', 'second-worker', '--task', 'T001', '--output', 'docs/verification/second-worker.json');
  assert.equal(result.status, 0, result.stderr);
  result = run(checkout, 'archive', '--owner', 'second-worker', '--task', 'T001', '--output', 'docs/verification/second-worker.json', '--apply');
  assert.equal(result.status, 0, result.stderr);
  result = run(checkout, 'render');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /first-worker\/T001/);
  assert.equal(await readFile(path, 'utf8'), navigation);
});

test('session progress initializes and refreshes only its generated view from shared assignments', async (t) => {
  const navigation = '# Active task\n\nUse `active-task.mjs list --compact` for current work.\n';
  const checkout = await fixture(t, navigation);
  const page = join(checkout, 'context/active_task.md');
  const output = '.agent-work/2026-10-15/progress-run/progress.md';
  const view = join(checkout, output);
  const session = runWork(checkout, 'start', '--session', 'progress-run', '--date', '2026-10-15');
  assert.equal(session.status, 0, session.stderr);

  let result = run(checkout, 'render', '--output', output);
  assert.equal(result.status, 0, result.stderr);
  assert.match(await readFile(view, 'utf8'), /Status: ready/);
  assert.match(await readFile(view, 'utf8'), /Canonical ledger: \[shared active-task registry\]\(file:/);
  assert.equal(await readFile(page, 'utf8'), navigation);

  await mkdir(join(checkout, 'src'));
  await writeFile(join(checkout, 'src/example.ts'), 'export const example = true;\n');
  result = run(checkout, 'start', '--role', 'worker', '--owner', 'progress-owner', '--task', 'T003', '--session', '2026-10-15/progress-run', '--summary', 'Implement the task', '--next', 'Run focused checks');
  assert.equal(result.status, 0, result.stderr);
  result = run(checkout, 'update', '--owner', 'progress-owner', '--task', 'T003', '--status', 'blocked', '--next', 'Resolve the fixture issue', '--verification', 'The focused check identifies the missing fixture');
  assert.equal(result.status, 0, result.stderr);
  result = run(checkout, 'handoff', '--owner', 'progress-owner', '--task', 'T003', '--result', 'Focused checks passed');
  assert.equal(result.status, 0, result.stderr);

  const ledger = join(checkout, '.agent-work/state/active-tasks.json');
  const ledgerBeforeRender = await readFile(ledger, 'utf8');
  result = run(checkout, 'render', '--output', output);
  assert.equal(result.status, 0, result.stderr);
  const refreshed = await readFile(view, 'utf8');
  assert.match(refreshed, /Status: handed-off/);
  assert.match(refreshed, /Next action: Coordinator must verify owned paths/);
  assert.match(refreshed, /Evidence: The focused check identifies the missing fixture/);
  assert.match(refreshed, /Result: Focused checks passed/);
  assert.match(refreshed, /Handoff evidence: verified/);
  assert.doesNotMatch(refreshed, /Next action: Run focused checks/);
  assert.equal(await readFile(ledger, 'utf8'), ledgerBeforeRender);
  assert.equal(await readFile(page, 'utf8'), navigation);

  result = run(checkout, 'start', '--owner', 'other-session', '--task', 'T004', '--session', '2026-10-16/other-run', '--summary', 'Separate work', '--next', 'Keep moving');
  assert.equal(result.status, 0, result.stderr);
  const ledgerAfterSecondStart = await readFile(ledger, 'utf8');
  const otherOutput = '.agent-work/2026-10-16/other-run/progress.md';
  result = run(checkout, 'render', '--output', otherOutput);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(await readFile(ledger, 'utf8'), ledgerAfterSecondStart);
  const otherBefore = await readFile(join(checkout, otherOutput), 'utf8');
  result = run(checkout, 'render', '--output', output);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(await readFile(join(checkout, otherOutput), 'utf8'), otherBefore);
  assert.equal(await readFile(ledger, 'utf8'), ledgerAfterSecondStart);
  assert.equal(await readFile(page, 'utf8'), navigation);
});

test('session progress rejects traversal, manual files, and symlinked directories', async (t) => {
  const checkout = await fixture(t, '# Active task\n');
  let result = run(checkout, 'render', '--output', '../outside.md');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /must be \.agent-work/);

  const session = runWork(checkout, 'start', '--session', 'safe-view', '--date', '2026-10-15');
  assert.equal(session.status, 0, session.stderr);
  const dateDirectory = join(checkout, '.agent-work/2026-10-15');
  const manualView = join(dateDirectory, 'safe-view/progress.md');
  await writeFile(manualView, 'Keep this manually written file.\n');
  result = run(checkout, 'render', '--output', '.agent-work/2026-10-15/safe-view/progress.md');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /not this session's generated view/);
  assert.equal(await readFile(manualView, 'utf8'), 'Keep this manually written file.\n');

  const outside = await mkdtemp(join(tmpdir(), 'active-task-outside-'));
  t.after(() => rm(outside, { recursive: true, force: true }));
  await rm(dateDirectory, { recursive: true });
  try {
    await symlink(outside, dateDirectory, process.platform === 'win32' ? 'junction' : 'dir');
  } catch (error) {
    if (['EPERM', 'EACCES', 'ENOTSUP'].includes(error.code)) return t.skip(`Directory symlinks are unavailable: ${error.code}`);
    throw error;
  }
  result = run(checkout, 'render', '--output', '.agent-work/2026-10-15/safe-view/progress.md');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /directories must be regular directories, not links/);
  assert.equal(await access(join(outside, 'safe-view/progress.md')).then(() => true, () => false), false);
});

test('explicit migration backs up and imports distinct owners from all linked worktrees', async (t) => {
  const active = { owner: 'legacy-active', task: 'T001', summary: 'Active legacy work', next: 'Resume active work', status: 'active', updatedAt: '2026-10-16T00:00:00.000Z' };
  const checkout = await fixture(t, legacyPage([active]));
  const currentPath = join(checkout, 'context/active_task.md');
  const currentSnapshot = await readFile(currentPath, 'utf8');
  const completed = { owner: 'legacy-completed', task: 'T002', summary: 'Completed legacy work', next: 'Retain completion record', status: 'completed', result: 'Completed evidence', updatedAt: '2026-10-16T00:01:00.000Z' };
  const linked = await addLegacyWorktree(t, checkout, [completed]);
  const linkedPath = join(linked, 'context/active_task.md');
  const linkedSnapshot = await readFile(linkedPath, 'utf8');

  const listed = run(checkout, 'list');
  assert.equal(listed.status, 0, listed.stderr);
  assert.deepEqual(JSON.parse(listed.stdout).map((entry) => entry.owner), ['legacy-active', 'legacy-completed']);
  const statePath = join(checkout, '.agent-work/state/active-tasks.json');
  assert.equal(await access(statePath).then(() => true, () => false), false);

  const migrated = run(linked, 'migrate-legacy');
  assert.equal(migrated.status, 0, migrated.stderr);
  const entries = JSON.parse(await readFile(statePath, 'utf8'));
  assert.deepEqual(entries.map((entry) => entry.owner), ['legacy-active', 'legacy-completed']);
  assert.equal(entries[1].result, 'Completed evidence');
  const backups = join(checkout, '.agent-work/state/legacy-active-task');
  assert.equal((await readdir(backups)).length, 2);
  assert.equal(await readFile(currentPath, 'utf8'), currentSnapshot);
  assert.equal(await readFile(linkedPath, 'utf8'), linkedSnapshot);

  const repeated = run(checkout, 'migrate-legacy');
  assert.equal(repeated.status, 0, repeated.stderr);
  assert.equal((await readdir(backups)).length, 2);
});

test('explicit migration merges legacy owners into existing shared state without replacing existing rows', async (t) => {
  const active = { owner: 'legacy-active', task: 'T001', summary: 'Active legacy work', next: 'Resume active work', status: 'active', updatedAt: '2026-10-16T00:00:00.000Z' };
  const completed = { owner: 'legacy-completed', task: 'T002', summary: 'Completed legacy work', next: 'Retain completion record', status: 'completed', result: 'Completed evidence', updatedAt: '2026-10-16T00:01:00.000Z' };
  const conflicting = { owner: 'shared-owner', task: 'T003', summary: 'Stale legacy work', next: 'Keep the shared row', status: 'active', updatedAt: '2026-10-16T00:02:00.000Z' };
  const checkout = await fixture(t, legacyPage([active, conflicting]));
  const linked = await addLegacyWorktree(t, checkout, [completed]);
  const independent = { owner: 'shared-owner', task: 'T003', summary: 'Current shared work', next: 'Preserve this row', status: 'blocked', updatedAt: '2026-10-16T00:03:00.000Z' };
  const statePath = join(checkout, '.agent-work/state/active-tasks.json');
  await mkdir(dirname(statePath), { recursive: true });
  await writeFile(statePath, JSON.stringify([independent], null, 2) + '\n');

  const migrated = run(linked, 'migrate-legacy');
  assert.equal(migrated.status, 0, migrated.stderr);
  assert.match(migrated.stdout, /"imported": 2/);
  assert.match(migrated.stdout, /"owner": "shared-owner"/);
  const entries = JSON.parse(await readFile(statePath, 'utf8'));
  assert.deepEqual(entries.map((entry) => entry.owner), ['shared-owner', 'legacy-active', 'legacy-completed']);
  assert.equal(entries[0].next, 'Preserve this row');
  assert.equal(entries[2].result, 'Completed evidence');
});

test('legacy rows stay read-only until migration is requested', async (t) => {
  const entry = { owner: 'legacy-owner', task: 'T001', summary: 'Legacy assignment', next: 'Keep this assignment', status: 'active' };
  const checkout = await fixture(t, legacyPage([entry]));
  const page = join(checkout, 'context/active_task.md');
  const snapshot = await readFile(page, 'utf8');

  const started = run(checkout, 'start', '--role', 'worker', '--owner', 'new-owner', '--task', 'T002', '--summary', 'New assignment', '--next', 'Do not overwrite legacy state');
  assert.equal(started.status, 1);
  assert.match(started.stderr, /run active-task\.mjs migrate-legacy/);
  assert.deepEqual(JSON.parse(run(checkout, 'list').stdout).map((row) => row.owner), ['legacy-owner']);
  assert.equal(await access(join(checkout, '.agent-work/state/active-tasks.json')).then(() => true, () => false), false);
  assert.equal(await readFile(page, 'utf8'), snapshot);
});

test('conflicting active and completed legacy rows are backed up without creating partial state', async (t) => {
  const active = { owner: 'same-owner', task: 'T001', summary: 'Active source', next: 'Keep running work', status: 'active', updatedAt: '2026-10-16T00:00:00.000Z' };
  const checkout = await fixture(t, legacyPage([active]));
  const currentPath = join(checkout, 'context/active_task.md');
  const currentSnapshot = await readFile(currentPath, 'utf8');
  const completed = { ...active, summary: 'Completed source', next: 'Retain completion', status: 'completed', result: 'Completed evidence', updatedAt: '2026-10-16T00:01:00.000Z' };
  const linked = await addLegacyWorktree(t, checkout, [completed]);
  const linkedPath = join(linked, 'context/active_task.md');
  const linkedSnapshot = await readFile(linkedPath, 'utf8');

  const result = run(checkout, 'migrate-legacy');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /"owner": "same-owner"/);
  const backups = await Promise.all((await readdir(join(checkout, '.agent-work/state/legacy-active-task'))).map((file) => readFile(join(checkout, '.agent-work/state/legacy-active-task', file), 'utf8')));
  assert.equal(backups.length, 2);
  assert.ok(backups.some((backup) => backup.includes('Keep running work')));
  assert.ok(backups.some((backup) => backup.includes('Completed evidence')));
  assert.equal(await access(join(checkout, '.agent-work/state/active-tasks.json')).then(() => true, () => false), false);
  assert.equal(await readFile(currentPath, 'utf8'), currentSnapshot);
  assert.equal(await readFile(linkedPath, 'utf8'), linkedSnapshot);
});
