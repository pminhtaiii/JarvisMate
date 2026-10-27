import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import {
  lstat,
  mkdir,
  mkdtemp,
  open,
  readFile,
  realpath,
  readdir,
  rename,
  rm,
  symlink,
  unlink,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { withOperationLock } from '../../scripts/agents/agent-work.mjs';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const cliPath = resolve(repositoryRoot, 'scripts/agents/agent-work.mjs');
const workspaceName = 'project';
const date = '2026-10-09';
const sessionId = 'chat-123';

async function fixture(t) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'agent-work checkout with spaces-')));
  t.after(async () => rm(root, { recursive: true, force: true }));
  const initialized = spawnSync('git', ['init', '--quiet', root], {
    encoding: 'utf8',
    windowsHide: true,
  });
  assert.equal(initialized.status, 0, initialized.stderr);
  return root;
}

function run(root, args, cwd = repositoryRoot) {
  return spawnSync(process.execPath, [cliPath, ...args, '--root', root], {
    cwd,
    encoding: 'utf8',
    windowsHide: true,
  });
}

function sessionPath(root, selectedDate = date, id = sessionId) {
  return join(root, '.agent-work', selectedDate, id);
}

async function marker(root, selectedDate = date, id = sessionId) {
  return JSON.parse(
    await readFile(join(sessionPath(root, selectedDate, id), 'session.json'), 'utf8'),
  );
}

async function start(root, id = sessionId, selectedDate = date) {
  const result = run(root, ['start', '--session', id, '--date', selectedDate]);
  assert.equal(result.status, 0, result.stderr);
  return result;
}

async function finish(root, selectedDate = date, id = sessionId) {
  const result = run(root, ['finish', '--session', `${selectedDate}/${id}`]);
  assert.equal(result.status, 0, result.stderr);
  return result;
}

async function linkDirectory(t, target, linkPath) {
  try {
    await symlink(target, linkPath, process.platform === 'win32' ? 'junction' : 'dir');
    return true;
  } catch (error) {
    const code = error && typeof error === 'object' && 'code' in error ? error.code : undefined;
    if (process.platform === 'win32' && ['EPERM', 'EACCES', 'UNKNOWN'].includes(code)) {
      t.skip('Windows did not grant directory link creation for this test');
      return false;
    }
    throw error;
  }
}

async function linkFile(t, target, linkPath) {
  try {
    await symlink(target, linkPath, 'file');
    return true;
  } catch (error) {
    const code = error && typeof error === 'object' && 'code' in error ? error.code : undefined;
    if (process.platform === 'win32' && ['EPERM', 'EACCES', 'UNKNOWN'].includes(code)) {
      t.skip('Windows did not grant file link creation for this test');
      return false;
    }
    throw error;
  }
}

test('start, finish, list, and reactivation preserve session content and metadata', async (t) => {
  const root = await fixture(t);
  await start(root);
  const created = await marker(root);
  assert.deepEqual(
    {
      schemaVersion: created.schemaVersion,
      workspace: created.workspace,
      date: created.date,
      id: created.id,
      status: created.status,
    },
    {
      schemaVersion: 1,
      workspace: workspaceName,
      date,
      id: sessionId,
      status: 'active',
    },
  );
  assert.equal(typeof created.startedAt, 'string');
  assert.equal('finishedAt' in created, false);
  assert.deepEqual(Object.keys(created).sort(), [
    'date',
    'id',
    'schemaVersion',
    'startedAt',
    'status',
    'workspace',
  ]);

  const firstStart = created.startedAt;
  const idempotent = await start(root);
  assert.match(idempotent.stdout, /already active/);
  assert.equal((await marker(root)).startedAt, firstStart);

  await writeFile(join(sessionPath(root), 'notes.md'), 'keep this work\n', 'utf8');
  await writeFile(
    join(sessionPath(root), 'session.json'),
    JSON.stringify({ ...created, startedAt: '2020-01-01T00:00:00.000Z' }),
    'utf8',
  );
  await finish(root);
  const completed = await marker(root);
  assert.equal(completed.status, 'finished');
  assert.equal(typeof completed.finishedAt, 'string');
  assert.equal(completed.startedAt, '2020-01-01T00:00:00.000Z');
  assert.deepEqual(Object.keys(completed).sort(), [
    'date',
    'finishedAt',
    'id',
    'schemaVersion',
    'startedAt',
    'status',
    'workspace',
  ]);

  const listed = run(root, ['list']);
  assert.equal(listed.status, 0, listed.stderr);
  assert.match(listed.stdout, new RegExp(`${date}/${sessionId} \\[finished\\]`));

  await start(root);
  const reactivated = await marker(root);
  assert.equal(reactivated.status, 'active');
  assert.notEqual(reactivated.startedAt, '2020-01-01T00:00:00.000Z');
  assert.equal('finishedAt' in reactivated, false);
  assert.equal(await readFile(join(sessionPath(root), 'notes.md'), 'utf8'), 'keep this work\n');
});

test('start defaults to the current Asia/Saigon calendar date', async (t) => {
  const root = await fixture(t);
  const result = run(root, ['start', '--session', sessionId]);
  assert.equal(result.status, 0, result.stderr);
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Ho_Chi_Minh',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const expectedDate = `${parts.find((part) => part.type === 'year')?.value}-${parts.find((part) => part.type === 'month')?.value}-${parts.find((part) => part.type === 'day')?.value}`;
  assert.equal((await marker(root, expectedDate)).date, expectedDate);
});

test('cleanup previews without mutating and apply deletes only valid finished sessions', async (t) => {
  const root = await fixture(t);
  await start(root, 'finished');
  await finish(root, date, 'finished');
  await start(root, 'active');
  await writeFile(
    join(sessionPath(root, date, 'finished'), 'notes.md'),
    'private log content\n',
    'utf8',
  );
  await writeFile(join(sessionPath(root, date, 'active'), 'notes.md'), 'active notes\n', 'utf8');

  const malformedPath = sessionPath(root, date, 'malformed');
  await mkdir(malformedPath, { recursive: true });
  await writeFile(join(malformedPath, 'session.json'), '{', 'utf8');
  const unknownPath = join(root, '.agent-work', 'unrecognized-folder');
  await mkdir(unknownPath, { recursive: true });
  await writeFile(join(unknownPath, 'keep.txt'), 'unknown\n', 'utf8');

  const finishedMarkerBefore = await readFile(
    join(sessionPath(root, date, 'finished'), 'session.json'),
    'utf8',
  );
  const runtimeLockPath = join(root, '.scratch', 'api-task.lock');
  await writeFile(runtimeLockPath, 'other operation lock\n', 'utf8');
  const scratchEntriesBefore = (await readdir(join(root, '.scratch'))).sort();
  const preview = run(root, ['cleanup']);
  assert.equal(preview.status, 0, preview.stderr);
  assert.match(preview.stdout, /preview/);
  assert.match(preview.stdout, /eligible for cleanup/);
  assert.match(preview.stdout, /retained: active session/);
  assert.match(preview.stdout, /retained: invalid session marker/);
  assert.doesNotMatch(preview.stdout, /private log content/);
  assert.equal(
    await readFile(join(sessionPath(root, date, 'finished'), 'session.json'), 'utf8'),
    finishedMarkerBefore,
  );
  assert.equal(
    await readFile(join(sessionPath(root, date, 'finished'), 'notes.md'), 'utf8'),
    'private log content\n',
  );
  assert.deepEqual((await readdir(join(root, '.scratch'))).sort(), scratchEntriesBefore);
  assert.equal(await readFile(runtimeLockPath, 'utf8'), 'other operation lock\n');

  const applied = run(root, ['cleanup', '--apply']);
  assert.equal(applied.status, 0, applied.stderr);
  await assert.rejects(lstat(sessionPath(root, date, 'finished')));
  assert.equal(
    await readFile(join(sessionPath(root, date, 'active'), 'notes.md'), 'utf8'),
    'active notes\n',
  );
  assert.equal(await readFile(join(unknownPath, 'keep.txt'), 'utf8'), 'unknown\n');
  assert.equal(await readFile(join(malformedPath, 'session.json'), 'utf8'), '{');
});

test('cleanup can target one finished session and leaves other finished sessions intact', async (t) => {
  const root = await fixture(t);
  await start(root, 'first');
  await finish(root, date, 'first');
  await start(root, 'second');
  await finish(root, date, 'second');

  const result = run(root, ['cleanup', '--apply', '--session', `${date}/first`]);
  assert.equal(result.status, 0, result.stderr);
  await assert.rejects(lstat(sessionPath(root, date, 'first')));
  assert.equal((await marker(root, date, 'second')).status, 'finished');
});

test('invalid identifiers, dates, session paths, and non-Git roots are rejected', async (t) => {
  const root = await fixture(t);
  for (const id of ['../escape', '..', 'CON', 'COM1', 'bad/name', 'bad\\name', 'trailing.']) {
    const result = run(root, ['start', '--session', id, '--date', date]);
    assert.notEqual(result.status, 0, `${id} must be rejected`);
  }
  for (const invalidDate of ['2026-02-29', '2026-13-01', '../2026-10-09']) {
    const result = run(root, ['start', '--session', sessionId, '--date', invalidDate]);
    assert.notEqual(result.status, 0, `${invalidDate} must be rejected`);
  }
  const escaping = run(root, ['cleanup', '--session', '../outside/sentinel']);
  assert.notEqual(escaping.status, 0);

  const wrongRoot = await mkdtemp(join(tmpdir(), 'agent-work unrelated root-'));
  t.after(async () => rm(wrongRoot, { recursive: true, force: true }));
  const sentinel = join(wrongRoot, 'user-data.txt');
  await writeFile(sentinel, 'preserve this file\n', 'utf8');
  const rejectedRoot = spawnSync(
    process.execPath,
    [cliPath, 'cleanup', '--apply', '--root', wrongRoot],
    {
      cwd: repositoryRoot,
      encoding: 'utf8',
      windowsHide: true,
    },
  );
  assert.notEqual(rejectedRoot.status, 0);
  assert.match(rejectedRoot.stderr, /not a Git checkout/i);
  assert.equal(await readFile(sentinel, 'utf8'), 'preserve this file\n');
  await assert.rejects(lstat(join(wrongRoot, '.agent-work')));
});

test('start preserves pre-existing unmarked directories instead of claiming them', async (t) => {
  const root = await fixture(t);
  const path = sessionPath(root);
  await mkdir(path, { recursive: true });
  await writeFile(join(path, 'user-notes.md'), 'unmanaged notes\n', 'utf8');
  const result = run(root, ['start', '--session', sessionId, '--date', date]);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /no managed marker; retaining it/);
  assert.equal(await readFile(join(path, 'user-notes.md'), 'utf8'), 'unmanaged notes\n');
  await assert.rejects(lstat(join(path, 'session.json')));
});

test('an existing operation lock is never reclaimed and unrelated runtime locks survive cleanup', async (t) => {
  const root = await fixture(t);
  const path = sessionPath(root);
  await mkdir(path, { recursive: true });
  const activeMarker = {
    schemaVersion: 1,
    workspace: workspaceName,
    date,
    id: sessionId,
    status: 'finished',
    startedAt: '2026-10-09T00:00:00.000Z',
    finishedAt: '2026-10-09T00:01:00.000Z',
  };
  await writeFile(join(path, 'session.json'), JSON.stringify(activeMarker), 'utf8');
  await mkdir(join(root, '.scratch'), { recursive: true });
  await writeFile(join(root, '.scratch', 'agent-work.lock'), 'stale but unverified lock\n', 'utf8');
  await writeFile(join(root, '.scratch', 'api-task.lock'), 'owned by another tool\n', 'utf8');

  const startResult = run(root, ['start', '--session', sessionId, '--date', date]);
  assert.notEqual(startResult.status, 0);
  assert.match(startResult.stderr, /operation lock is already held/i);
  const cleanupResult = run(root, ['cleanup', '--apply']);
  assert.notEqual(cleanupResult.status, 0);
  assert.equal(
    await readFile(join(root, '.scratch', 'agent-work.lock'), 'utf8'),
    'stale but unverified lock\n',
  );
  assert.equal(
    await readFile(join(root, '.scratch', 'api-task.lock'), 'utf8'),
    'owned by another tool\n',
  );
  assert.equal((await marker(root)).status, 'finished');
});

test('failed lock writes and syncs remove only the lock file created by that attempt', async (t) => {
  for (const phase of ['write', 'sync']) {
    await t.test(`${phase} failure releases its own lock`, async (subtest) => {
      const root = await fixture(subtest);
      const lockPath = join(root, '.scratch', 'agent-work.lock');
      const failingOpen = async (path, flags, mode) => {
        const handle = await open(path, flags, mode);
        return {
          stat: (options) => handle.stat(options),
          writeFile: (contents, encoding) =>
            phase === 'write'
              ? Promise.reject(new Error('simulated lock write failure'))
              : handle.writeFile(contents, encoding),
          sync: () =>
            phase === 'sync'
              ? Promise.reject(new Error('simulated lock sync failure'))
              : handle.sync(),
          close: () => handle.close(),
        };
      };

      await assert.rejects(
        withOperationLock(
          root,
          async () => assert.fail('lock operation must not run'),
          failingOpen,
        ),
        new RegExp(`simulated lock ${phase} failure`),
      );
      await assert.rejects(lstat(lockPath));

      const nextCommand = run(root, ['start', '--session', sessionId, '--date', date]);
      assert.equal(nextCommand.status, 0, nextCommand.stderr);
      assert.equal((await marker(root)).status, 'active');
    });
  }
});

test('failed lock initialization preserves a replacement owner lock', async (t) => {
  const root = await fixture(t);
  const lockPath = join(root, '.scratch', 'agent-work.lock');
  const replacementPath = `${lockPath}.replacement`;
  const replacementContents = 'replacement owner lock\n';
  const replacingOpen = async (path, flags, mode) => {
    const handle = await open(path, flags, mode);
    await writeFile(replacementPath, replacementContents, { flag: 'wx' });
    return {
      stat: (options) => handle.stat(options),
      writeFile: async () => {
        await handle.close();
        await unlink(path);
        await rename(replacementPath, path);
        throw new Error('simulated lock write failure after replacement');
      },
      sync: () => handle.sync(),
      close: () => handle.close(),
    };
  };

  await assert.rejects(
    withOperationLock(root, async () => assert.fail('lock operation must not run'), replacingOpen),
    /simulated lock write failure after replacement/,
  );
  assert.equal(await readFile(lockPath, 'utf8'), replacementContents);

  const nextCommand = run(root, ['start', '--session', sessionId, '--date', date]);
  assert.notEqual(nextCommand.status, 0);
  assert.match(nextCommand.stderr, /already held/);
  assert.equal(await readFile(lockPath, 'utf8'), replacementContents);
});

test('cleanup retains sessions with nested and manifest links without following their targets', async (t) => {
  const root = await fixture(t);
  await start(root);
  await finish(root);
  const outside = await mkdtemp(join(tmpdir(), 'agent-work protected target-'));
  t.after(async () => rm(outside, { recursive: true, force: true }));
  const sentinelPath = join(outside, 'sentinel.txt');
  await writeFile(sentinelPath, 'outside data\n', 'utf8');
  const nestedLink = join(sessionPath(root), 'linked-output');
  if (!(await linkDirectory(t, outside, nestedLink))) return;

  const result = run(root, ['cleanup', '--apply']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /retained: contains a symlink or junction/);
  assert.equal((await marker(root)).status, 'finished');
  assert.equal(await readFile(sentinelPath, 'utf8'), 'outside data\n');
});

test('cleanup rejects a linked managed root and retains linked date or session directories', async (t) => {
  const root = await fixture(t);
  const outside = await mkdtemp(join(tmpdir(), 'agent-work external tree-'));
  t.after(async () => rm(outside, { recursive: true, force: true }));
  const sentinelPath = join(outside, 'sentinel.txt');
  await writeFile(sentinelPath, 'outside data\n', 'utf8');
  const managedRoot = join(root, '.agent-work');
  if (!(await linkDirectory(t, outside, managedRoot))) return;
  const rejected = run(root, ['cleanup', '--apply']);
  assert.notEqual(rejected.status, 0);
  assert.equal(await readFile(sentinelPath, 'utf8'), 'outside data\n');
  await rm(managedRoot, { force: true });

  await mkdir(join(root, '.agent-work'), { recursive: true });
  if (!(await linkDirectory(t, outside, join(root, '.agent-work', date)))) return;
  const dateResult = run(root, ['cleanup', '--apply']);
  assert.equal(dateResult.status, 0, dateResult.stderr);
  assert.equal(await readFile(sentinelPath, 'utf8'), 'outside data\n');
});

test('cleanup retains a linked session directory without following its target', async (t) => {
  const root = await fixture(t);
  await mkdir(join(root, '.agent-work', date), { recursive: true });
  const outside = await mkdtemp(join(tmpdir(), 'agent-work linked session target-'));
  t.after(async () => rm(outside, { recursive: true, force: true }));
  const sentinelPath = join(outside, 'sentinel.txt');
  await writeFile(sentinelPath, 'outside session data\n', 'utf8');
  if (!(await linkDirectory(t, outside, sessionPath(root)))) return;

  const result = run(root, ['cleanup', '--apply']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /retained: session directory is a symlink or junction/);
  assert.equal(await readFile(sentinelPath, 'utf8'), 'outside session data\n');
});

test('cleanup retains a linked marker without following its target', async (t) => {
  const root = await fixture(t);
  await start(root);
  await finish(root);
  const path = join(sessionPath(root), 'session.json');
  const markerContents = await readFile(path, 'utf8');
  await rm(path);
  const outside = await mkdtemp(join(tmpdir(), 'agent-work linked marker target-'));
  t.after(async () => rm(outside, { recursive: true, force: true }));
  const outsideMarker = join(outside, 'session.json');
  await writeFile(outsideMarker, markerContents, 'utf8');
  if (!(await linkFile(t, outsideMarker, path))) return;

  const result = run(root, ['cleanup', '--apply']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /retained: contains a symlink or junction/);
  assert.equal(await readFile(outsideMarker, 'utf8'), markerContents);
  await lstat(path);
});

test('session cleanup retains nested Git checkouts and the separate worktree area', async (t) => {
  const root = await fixture(t);
  await start(root);
  await finish(root);
  const nested = join(sessionPath(root), 'worker');
  await mkdir(nested);
  await writeFile(join(nested, '.git'), 'gitdir: retained-worktree-metadata\n');
  const worktrees = join(root, '.agent-work', 'worktrees');
  await mkdir(worktrees);
  await writeFile(join(worktrees, 'keep.txt'), 'separate agent checkout\n');
  const result = run(root, ['cleanup', '--apply']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /contains a Git checkout/);
  assert.equal(await readFile(join(nested, '.git'), 'utf8'), 'gitdir: retained-worktree-metadata\n');
  assert.equal(await readFile(join(worktrees, 'keep.txt'), 'utf8'), 'separate agent checkout\n');
});

test('session finish retains active contributor work until completion or worker handoff', async (t) => {
  const root = await fixture(t);
  await start(root);
  await mkdir(join(root, '.agent-work/state'), { recursive: true });
  const state = join(root, '.agent-work/state/active-tasks.json');
  await writeFile(state, JSON.stringify([{ owner: 'coordinator', task: 'publish', checkout: root, status: 'active' }]));
  let result = run(root, ['finish', '--session', `${date}/${sessionId}`]);
  assert.equal(result.status, 1);
  assert.equal((await marker(root)).status, 'active');
  await writeFile(state, JSON.stringify([{ owner: 'worker', task: 'implement', checkout: root, status: 'handed-off', role: 'worker' }]));
  result = run(root, ['finish', '--session', `${date}/${sessionId}`]);
  assert.equal(result.status, 0, result.stderr);
});
