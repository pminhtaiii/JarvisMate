import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile, lstat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const repositoryRoot = fileURLToPath(new URL('../..', import.meta.url));
const cliPath = join(repositoryRoot, 'scripts/agents/agent-output.mjs');
const date = '2026-10-22';
const sessionId = 'orchestration-retro';
const session = `${date}/${sessionId}`;

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'agent output workspace-'));
  t.after(async () => rm(root, { recursive: true, force: true }));
  const git = spawnSync('git', ['init', '--quiet'], { cwd: root, encoding: 'utf8', windowsHide: true });
  assert.equal(git.status, 0, git.stderr);
  const sessionDirectory = join(root, '.agent-work', date, sessionId);
  await mkdir(sessionDirectory, { recursive: true });
  await writeFile(join(sessionDirectory, 'session.json'), `${JSON.stringify({
    schemaVersion: 1,
    workspace: 'project',
    date,
    id: sessionId,
    status: 'active',
    startedAt: '2026-10-22T00:00:00.000Z',
  })}\n`, 'utf8');
  return { root, sessionDirectory };
}

function run(root, input, extraArgs = []) {
  return spawnSync(process.execPath, [
    cliPath,
    '--workspace', root,
    '--session', session,
    '--output', 'handoff.json',
    ...extraArgs,
  ], { cwd: root, input, encoding: 'utf8', windowsHide: true });
}

test('writes structured UTF-8 JSON and returns bounded log tail with caller exit observation', async (t) => {
  const { root, sessionDirectory } = await fixture(t);
  const payload = {
    brief: { taskContext: 'Existing agent-context task output', delta: 'Keep the brief concise.' },
    exitObservation: { code: 7, signal: null },
  };
  const log = `${Array.from({ length: 500 }, (_, index) =>
    `${String(index).padStart(3, '0')}: ${'é'.repeat(24)}`).join('\n')}\n`;
  await writeFile(join(sessionDirectory, 'worker.log'), log, 'utf8');

  const result = run(root, JSON.stringify(payload), ['--log', 'worker.log']);

  assert.equal(result.status, 0, result.stderr);
  const outputPath = join(sessionDirectory, 'handoff.json');
  const bytes = await readFile(outputPath);
  assert.notEqual(bytes.subarray(0, 3).toString('hex'), 'efbbbf');
  assert.deepEqual(JSON.parse(bytes.toString('utf8')), payload);
  const summary = JSON.parse(result.stdout);
  assert.equal(summary.status, 'written');
  assert.equal(summary.output, 'handoff.json');
  assert.deepEqual(summary.exitObservation, payload.exitObservation);
  assert.equal(summary.log.file, 'worker.log');
  assert.equal(summary.log.fileBytes, Buffer.byteLength(log, 'utf8'));
  assert.ok(summary.log.truncated);
  assert.ok(summary.log.tailLines <= 100);
  assert.ok(Buffer.byteLength(summary.log.tail, 'utf8') <= 16 * 1024);
  assert.match(summary.log.tail, /499:/);
  assert.doesNotMatch(summary.log.tail, /000:/);
});

test('reports a missing named log by name before writing handoff output', async (t) => {
  const { root, sessionDirectory } = await fixture(t);

  const result = run(root, JSON.stringify({ brief: 'valid' }), ['--log', 'missing.log']);

  assert.notEqual(result.status, 0);
  assert.equal(result.stderr.trim(), 'Log file not found in session: missing.log');
  assert.equal(result.stdout, '');
  await assert.rejects(lstat(join(sessionDirectory, 'handoff.json')));
});

test('drops leading UTF-8 continuation bytes when a bounded tail starts inside a four-byte character', async (t) => {
  for (const continuationBytes of [1, 2, 3]) {
    const { root, sessionDirectory } = await fixture(t);
    const suffix = 'x'.repeat(continuationBytes);
    const log = `${'🚀'.repeat(5000)}${suffix}`;
    await writeFile(join(sessionDirectory, 'worker.log'), log, 'utf8');

    const result = run(root, JSON.stringify({ brief: 'valid' }), ['--log', 'worker.log']);

    assert.equal(result.status, 0, result.stderr);
    const summary = JSON.parse(result.stdout);
    assert.equal(summary.log.fileBytes, Buffer.byteLength(log, 'utf8'));
    assert.equal(summary.log.tailLines, 1);
    assert.ok(Buffer.byteLength(summary.log.tail, 'utf8') <= 16 * 1024);
    assert.ok(summary.log.tail.endsWith(suffix));
    assert.doesNotMatch(summary.log.tail, /\uFFFD/);
  }
});

test('rejects malformed, BOM-prefixed, invalid UTF-8, and oversized input before creating output', async (t) => {
  const { root, sessionDirectory } = await fixture(t);
  const oversized = Buffer.from(JSON.stringify({ note: 'x'.repeat(256 * 1024) }));
  for (const input of [
    '{',
    '\uFEFF{"valid":true}',
    '{"exitObservation":{"code":1.5}}',
    Buffer.from([0xc3, 0x28]),
    oversized,
  ]) {
    const result = run(root, input);
    assert.notEqual(result.status, 0, Buffer.isBuffer(input) ? `${input.length} input bytes` : JSON.stringify(input));
    await assert.rejects(lstat(join(sessionDirectory, 'handoff.json')));
  }
});

test('rejects duplicate arguments, invalid session paths, and output names outside the session', async (t) => {
  const { root, sessionDirectory } = await fixture(t);
  const baseArgs = ['--workspace', root, '--session', session, '--output', 'handoff.json'];
  for (const args of [
    [...baseArgs, '--output', 'again.json'],
    ['--workspace', root, '--session', '../outside', '--output', 'handoff.json'],
    [...baseArgs.slice(0, -1), '../outside.json'],
    [...baseArgs.slice(0, -1), '..\\outside.json'],
  ]) {
    const result = spawnSync(process.execPath, [cliPath, ...args], {
      cwd: root,
      input: JSON.stringify({ brief: 'valid' }),
      encoding: 'utf8',
      windowsHide: true,
    });
    assert.notEqual(result.status, 0);
    await assert.rejects(lstat(join(sessionDirectory, 'handoff.json')));
  }
});

test('does not overwrite an existing session file', async (t) => {
  const { root, sessionDirectory } = await fixture(t);
  const outputPath = join(sessionDirectory, 'handoff.json');
  await writeFile(outputPath, 'keep unrelated content\n', 'utf8');

  const result = run(root, JSON.stringify({ brief: 'valid' }));

  assert.notEqual(result.status, 0);
  assert.equal(await readFile(outputPath, 'utf8'), 'keep unrelated content\n');
});

test('refuses a session path linked outside the workspace', async (t) => {
  const { root, sessionDirectory } = await fixture(t);
  const outside = await mkdtemp(join(tmpdir(), 'agent output external-'));
  t.after(async () => rm(outside, { recursive: true, force: true }));
  await writeFile(join(outside, 'sentinel.txt'), 'keep outside data\n', 'utf8');
  await rm(sessionDirectory, { recursive: true, force: true });
  try {
    await symlink(outside, sessionDirectory, process.platform === 'win32' ? 'junction' : 'dir');
  } catch (error) {
    if (['EPERM', 'EACCES', 'ENOTSUP'].includes(error.code)) {
      t.skip('directory links are unavailable in this environment');
      return;
    }
    throw error;
  }

  const result = run(root, JSON.stringify({ brief: 'valid' }));

  assert.notEqual(result.status, 0);
  assert.equal(await readFile(join(outside, 'sentinel.txt'), 'utf8'), 'keep outside data\n');
  await assert.rejects(lstat(join(outside, 'handoff.json')));
});

test('refuses a log link outside the session', async (t) => {
  const { root, sessionDirectory } = await fixture(t);
  const outside = await mkdtemp(join(tmpdir(), 'agent output external log-'));
  t.after(async () => rm(outside, { recursive: true, force: true }));
  const outsideLog = join(outside, 'worker.log');
  await writeFile(outsideLog, 'keep private log\n', 'utf8');
  try {
    await symlink(outsideLog, join(sessionDirectory, 'worker.log'), 'file');
  } catch (error) {
    if (['EPERM', 'EACCES', 'ENOTSUP'].includes(error.code)) {
      t.skip('file links are unavailable in this environment');
      return;
    }
    throw error;
  }

  const result = run(root, JSON.stringify({ brief: 'valid' }), ['--log', 'worker.log']);

  assert.notEqual(result.status, 0);
  assert.equal(await readFile(outsideLog, 'utf8'), 'keep private log\n');
  await assert.rejects(lstat(join(sessionDirectory, 'handoff.json')));
});
