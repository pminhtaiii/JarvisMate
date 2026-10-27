import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, realpath, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const cli = resolve(dirname(fileURLToPath(import.meta.url)), '../../scripts/agents/agent-worktree.mjs');
function git(root, args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim();
}
function run(root, ...args) {
  return spawnSync(process.execPath, [cli, ...args, '--root', root], { encoding: 'utf8', windowsHide: true, timeout: 15_000 });
}
function alternateCase(path) {
  const start = path.indexOf('\\', 2) + 1;
  const offset = path.slice(start).search(/[a-z]/i);
  if (offset === -1) return path;
  const index = start + offset;
  const letter = path[index];
  return path.slice(0, index) + (letter === letter.toLowerCase() ? letter.toUpperCase() : letter.toLowerCase()) + path.slice(index + 1);
}
function shortPath(path) {
  if (process.platform !== 'win32') return null;
  const typeDefinition = [
    'using System.Runtime.InteropServices;',
    'using System.Text;',
    'public static class NativePathAlias {',
    '  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]',
    '  public static extern uint GetShortPathName(string longPath, StringBuilder shortPath, uint length);',
    '}',
  ].join('\n');
  const command = `Add-Type -TypeDefinition @'\n${typeDefinition}\n'@\n$buffer = New-Object System.Text.StringBuilder(32768)\n[void][NativePathAlias]::GetShortPathName($env:WORKTREE_PATH_FOR_TEST, $buffer, [uint32]$buffer.Capacity)\n$buffer.ToString()`;
  const result = spawnSync('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command], {
    encoding: 'utf8', windowsHide: true, env: { ...process.env, WORKTREE_PATH_FOR_TEST: path },
  });
  const candidate = result.status === 0 ? result.stdout.trim() : '';
  return candidate && candidate.toLowerCase() !== path.toLowerCase() ? candidate : null;
}
async function fixture(t, { externalWorker = false } = {}) {
  const directory = await realpath(await mkdtemp(join(tmpdir(), 'agent-worktree-')));
  const root = join(directory, 'repo');
  await mkdir(root);
  t.after(() => rm(directory, { recursive: true, force: true }));
  git(root, ['init', '--quiet', '-b', 'main']);
  git(root, ['config', 'core.autocrlf', 'false']);
  await mkdir(join(root, 'docs'));
  await writeFile(join(root, 'docs/evidence.md'), 'Acceptance checks passed.\n');
  await writeFile(join(root, '.gitignore'), '.agent-work/\n');
  git(root, ['add', '.']);
  git(root, ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '-m', 'fixture']);
  const base = git(root, ['rev-parse', 'HEAD']);
  git(root, ['update-ref', 'refs/remotes/origin/development', base]);
  const worker = externalWorker ? join(directory, 't3-app', 'worker') : join(root, '.agent-work/worktrees/worker');
  await mkdir(dirname(worker), { recursive: true });
  git(root, ['worktree', 'add', '-b', 'worker', worker]);
  await mkdir(join(root, '.agent-work/2026-10-15/run'), { recursive: true });
  await writeFile(join(root, '.agent-work/2026-10-15/run/session.json'), JSON.stringify({
    schemaVersion: 1, workspace: 'project', date: '2026-10-15', id: 'run', status: 'active', startedAt: new Date().toISOString(),
  }));
  await mkdir(join(root, '.agent-work/state'));
  await writeFile(join(root, '.agent-work/state/active-tasks.json'), JSON.stringify([
    { owner: 'worker', task: 'T001', checkout: worker, summary: 'Work', next: 'Review', status: 'completed' },
  ]));
  return { root, worker, base };
}
function register(root, worker) {
  const result = run(root, 'register', '--id', 'worker', '--path', worker, '--integration-ref', 'main', '--session', '2026-10-15/run', '--owner', 'worker', '--task', 'T001');
  assert.equal(result.status, 0, result.stderr);
}
function accept(root, id = 'worker') {
  const result = run(root, 'accept', '--id', id, '--evidence', 'docs/evidence.md', '--workers-stopped');
  assert.equal(result.status, 0, result.stderr);
}

test('retirement previews by default and applies only to an accepted, clean, merged owned worktree', async (t) => {
  const { root, worker } = await fixture(t);
  register(root, worker);
  accept(root);
  let result = run(root, 'cleanup', '--id', 'worker');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).eligible, true);
  assert.equal(await readFile(join(worker, 'docs/evidence.md'), 'utf8'), 'Acceptance checks passed.\n');
  result = run(root, 'cleanup', '--id', 'worker', '--apply');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).removed, true);
  assert.equal(git(root, ['branch', '--show-current']), 'main');
  git(root, ['show-ref', '--verify', 'refs/heads/worker']);
});

test('unmerged commits remain even when the worker is clean and its handoff accepted', async (t) => {
  const { root, worker } = await fixture(t);
  register(root, worker);
  await writeFile(join(worker, 'unmerged.txt'), 'preserve this change\n');
  git(worker, ['add', 'unmerged.txt']);
  git(worker, ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '-m', 'unmerged']);
  accept(root);
  const result = run(root, 'cleanup', '--id', 'worker', '--apply');
  assert.equal(result.status, 0, result.stderr);
  assert.match(JSON.parse(result.stdout).reason, /not integrated/);
  assert.equal(await readFile(join(worker, 'unmerged.txt'), 'utf8'), 'preserve this change\n');
});

test('modified, untracked, and ignored content each prevent worktree retirement', async (t) => {
  for (const mode of ['modified', 'untracked', 'ignored']) {
    const { root, worker } = await fixture(t);
    register(root, worker);
    accept(root);
    const file = mode === 'modified' ? join(worker, 'docs/evidence.md') : mode === 'ignored' ? join(worker, '.agent-work/cache.txt') : join(worker, 'notes.txt');
    if (mode === 'ignored') await mkdir(join(worker, '.agent-work'));
    await writeFile(file, 'retained content\n');
    const result = run(root, 'cleanup', '--id', 'worker', '--apply');
    assert.equal(result.status, 0, result.stderr);
    assert.equal(JSON.parse(result.stdout).removed, false);
    assert.match(JSON.parse(result.stdout).reason, /modified, untracked, or ignored/);
    assert.equal(await readFile(file, 'utf8'), 'retained content\n');
  }
});

test('checkout-wide active assignments, changed evidence, and locked worktrees invalidate retirement', async (t) => {
  for (const mode of ['resumed', 'unrelated-session', 'evidence', 'locked']) {
    const { root, worker } = await fixture(t);
    register(root, worker);
    accept(root);
    if (mode === 'resumed') await writeFile(join(root, '.agent-work/state/active-tasks.json'), JSON.stringify([{ owner: 'worker', task: 'T001', checkout: worker, status: 'active' }]));
    if (mode === 'unrelated-session') await writeFile(join(root, '.agent-work/state/active-tasks.json'), JSON.stringify([{ owner: 'another-worker', task: 'T099', checkout: worker, session: '2026-10-21/another-session', status: 'active' }]));
    if (mode === 'evidence') await writeFile(join(root, 'docs/evidence.md'), 'Changed after acceptance\n');
    if (mode === 'locked') git(root, ['worktree', 'lock', worker]);
    const result = run(root, 'cleanup', '--id', 'worker', '--apply');
    assert.equal(result.status, 0, result.stderr);
    assert.equal(JSON.parse(result.stdout).removed, false);
    assert.equal(JSON.parse(result.stdout).eligible, false);
    if (mode === 'unrelated-session') assert.match(JSON.parse(result.stdout).reason, /active or blocked assignments/);
    await readFile(join(worker, 'docs/evidence.md'));
  }
});

test('a reassigned predecessor does not block retirement after its successor finishes', async (t) => {
  for (const successorStatus of ['completed', 'active', 'blocked']) {
    const { root, worker } = await fixture(t);
    register(root, worker);
    accept(root);
    await writeFile(join(root, '.agent-work/state/active-tasks.json'), JSON.stringify([
      {
        owner: 'interrupted', task: 'T001', checkout: worker, session: '2026-10-15/source',
        summary: 'Work', next: 'Transferred to successor', status: 'reassigned',
        reassignments: [{ owner: 'worker', task: 'T001', session: '2026-10-15/successor', reason: 'Recovery', at: '2026-10-15T00:00:00.000Z' }],
      },
      {
        owner: 'worker', task: 'T001', checkout: worker, session: '2026-10-15/successor',
        summary: 'Work', next: 'Finish verification', status: successorStatus,
        reassignedFrom: { owner: 'interrupted', task: 'T001', session: '2026-10-15/source' },
      },
    ]));

    const result = run(root, 'cleanup', '--id', 'worker');
    assert.equal(result.status, 0, result.stderr);
    const report = JSON.parse(result.stdout);
    if (successorStatus === 'completed') assert.equal(report.eligible, true, JSON.stringify(report));
    else {
      assert.equal(report.eligible, false);
      assert.match(report.reason, /active or blocked assignments/);
    }
  }
});

test('unknown workers and attempts to register the primary checkout are rejected', async (t) => {
  const { root } = await fixture(t);
  let result = run(root, 'cleanup', '--id', 'unknown', '--apply');
  assert.equal(result.status, 1);
  result = run(root, 'register', '--id', 'primary', '--path', root, '--integration-ref', 'main', '--session', '2026-10-15/run', '--owner', 'worker', '--task', 'T001');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /inside the managed worktree area/);
});

test('external app-owned registration rejects a case-variant primary path on Windows', async (t) => {
  if (process.platform !== 'win32') return t.skip('Windows path casing is required for this regression.');
  const { root } = await fixture(t);
  const result = run(root, 'register', '--id', 'primary-case', '--path', alternateCase(root), '--integration-ref', 'main', '--session', '2026-10-15/run', '--owner', 'worker', '--task', 'T001', '--external-app-owned');
  assert.equal(result.status, 1, `case-variant primary path unexpectedly registered: ${result.stdout}`);
  assert.match(result.stderr, /invoking and primary checkouts/i);
  await assert.rejects(readFile(join(root, '.agent-work/worktree-receipts/primary-case.json')), { code: 'ENOENT' });
});

test('registration accepts a valid case-variant worktree path on Windows', async (t) => {
  if (process.platform !== 'win32') return t.skip('Windows path casing is required for this regression.');
  const { root, worker } = await fixture(t);
  const result = run(root, 'register', '--id', 'worker-case', '--path', alternateCase(worker), '--integration-ref', 'main', '--session', '2026-10-15/run', '--owner', 'worker', '--task', 'T001');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(await readFile(join(root, '.agent-work/worktree-receipts/worker-case.json'), 'utf8')).path.toLowerCase(), (await realpath(worker)).toLowerCase());
});

test('registration accepts a valid Windows 8.3 short-name worktree path when available', async (t) => {
  if (process.platform !== 'win32') return t.skip('Windows 8.3 alias not run locally; Windows CI validation is required.');
  const { root, worker } = await fixture(t);
  const alias = shortPath(worker);
  if (!alias) return t.skip('No local 8.3 alias is available; Windows CI validation is required.');
  const result = run(root, 'register', '--id', 'worker-short', '--path', alias, '--integration-ref', 'main', '--session', '2026-10-15/run', '--owner', 'worker', '--task', 'T001');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(await readFile(join(root, '.agent-work/worktree-receipts/worker-short.json'), 'utf8')).path.toLowerCase(), (await realpath(worker)).toLowerCase());
});

test('registration rejects final and intermediate junction paths', async (t) => {
  for (const kind of ['final', 'intermediate']) {
    const { root, worker } = await fixture(t);
    const link = join(root, '.agent-work/worktrees', kind === 'final' ? 'worker-final-link' : 'worker-intermediate-link');
    const path = kind === 'final' ? link : join(link, 'worktrees', 'worker');
    await symlink(kind === 'final' ? worker : join(root, '.agent-work'), link, process.platform === 'win32' ? 'junction' : 'dir');
    const result = run(root, 'register', '--id', `worker-${kind}-link`, '--path', path, '--integration-ref', 'main', '--session', '2026-10-15/run', '--owner', 'worker', '--task', 'T001');
    assert.equal(result.status, 1, result.stdout);
    assert.match(result.stderr, /symbolic link|without links/i);
    await assert.rejects(readFile(join(root, `.agent-work/worktree-receipts/worker-${kind}-link.json`)), { code: 'ENOENT' });
  }
});

test('external app-owned worktrees require explicit registration and are never cleaned up by the helper', async (t) => {
  const { root, worker, base } = await fixture(t, { externalWorker: true });
  const statePath = join(root, '.agent-work/state/active-tasks.json');
  const entries = JSON.parse(await readFile(statePath, 'utf8'));
  const checkout = await realpath(worker);
  const repository = await realpath(join(root, '.git'));
  const identity = { owner: 'worker', task: 'T001', session: '2026-10-15/run' };
  const originBase = { ref: 'refs/remotes/origin/development', sha: base };
  entries[0] = {
    ...entries[0], session: identity.session, checkout,
    reservation: { schemaVersion: 1, identity, repository, base: originBase },
    binding: { schemaVersion: 1, identity, checkout, repository, branch: 'refs/heads/worker', base: originBase, boundAt: '2026-10-15T00:00:00.000Z' },
  };
  await writeFile(statePath, JSON.stringify(entries));
  await writeFile(join(worker, 'later.txt'), 'committed after the reserved base\n');
  git(worker, ['add', 'later.txt']);
  git(worker, ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '-m', 'later worker change']);
  const head = git(worker, ['rev-parse', 'HEAD']);
  assert.notEqual(head, base);

  let result = run(root, 'register', '--id', 'external', '--path', worker, '--integration-ref', 'main', '--session', '2026-10-15/run', '--owner', 'worker', '--task', 'T001');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /managed worktree area|external-app-owned/i);

  result = run(root, 'register', '--id', 'external', '--path', worker, '--integration-ref', 'main', '--session', '2026-10-15/run', '--owner', 'worker', '--task', 'T001', '--external-app-owned');
  assert.equal(result.status, 0, result.stderr);
  const receiptPath = join(root, '.agent-work/worktree-receipts/external.json');
  let receipt = JSON.parse(await readFile(receiptPath, 'utf8'));
  assert.equal(receipt.externalAppOwned, true);
  assert.equal(receipt.base, base);
  assert.equal(receipt.head, head);

  accept(root, 'external');
  result = run(root, 'cleanup', '--id', 'external');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).eligible, false);
  assert.match(JSON.parse(result.stdout).reason, /app-owned|external/i);
  result = run(root, 'cleanup', '--id', 'external', '--apply');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).removed, false);
  assert.match(JSON.parse(result.stdout).reason, /app-owned|external/i);
  await readFile(join(worker, 'later.txt'));
  receipt = JSON.parse(await readFile(receiptPath, 'utf8'));
  assert.equal(receipt.status, 'accepted');
  assert.match(git(root, ['worktree', 'list', '--porcelain']), /t3-app[\\/]worker/);
});
