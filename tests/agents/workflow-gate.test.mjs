import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { packageScriptCommand, runGate } from '../../scripts/agents/workflow-gate.mjs';

test('package script gates run the same pnpm command on Unix and Windows', () => {
  assert.deepEqual(packageScriptCommand('test:contributors', 'linux'), { command: 'pnpm', args: ['run', 'test:contributors'] });
  assert.deepEqual(packageScriptCommand('test:contributors', 'win32'), { command: 'cmd.exe', args: ['/d', '/s', '/c', 'pnpm run test:contributors'] });
  assert.throws(() => packageScriptCommand('test:contributors && whoami', 'linux'), /package script/);
});

test('gate accepts only bounded positive integer environment timeouts', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'workflow-gate-env-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const previous = process.env.WORKFLOW_GATE_TIMEOUT;
  t.after(() => {
    if (previous === undefined) delete process.env.WORKFLOW_GATE_TIMEOUT;
    else process.env.WORKFLOW_GATE_TIMEOUT = previous;
  });
  const delays = [];
  const schedule = globalThis.setTimeout;
  t.mock.method(globalThis, 'setTimeout', (callback, delay, ...args) => {
    delays.push(delay);
    return schedule(callback, 10_000, ...args);
  });
  const cases = [
    [undefined, 600_000], ['', 600_000], ['invalid', 600_000],
    ['0', 600_000], ['-1', 600_000], ['1.5', 600_000],
    ['Infinity', 600_000], ['-Infinity', 600_000],
    ['2147483648', 600_000], ['1e100', 600_000],
    ['1', 1], ['600000', 600_000], ['2147483647', 2_147_483_647],
  ];
  for (const [index, [value, expected]] of cases.entries()) {
    if (value === undefined) delete process.env.WORKFLOW_GATE_TIMEOUT;
    else process.env.WORKFLOW_GATE_TIMEOUT = value;
    await runGate({ name: 'env', args: ['-e', ''], cwd: directory, logPath: join(directory, `${index}.log`), report() {} });
    assert.equal(delays.at(-1), expected, `environment timeout: ${value}`);
  }
  process.env.WORKFLOW_GATE_TIMEOUT = '-1';
  await runGate({ name: 'explicit', args: ['-e', ''], cwd: directory, logPath: join(directory, 'explicit.log'), timeout: 1234, report() {} });
  assert.equal(delays.at(-1), 1234, 'explicit timeout takes precedence');
});

test('gate progress arrives before exit and complete stdout/stderr remains in its log', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'workflow-gate-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const logPath = join(directory, 'gate.log');
  const events = [];
  let notifyStart;
  const started = new Promise(resolve => { notifyStart = resolve; });
  let finished = false;
  const running = runGate({ name: 'example', args: ['-e', "process.stdout.write('first\\n'); setTimeout(() => { console.error('last'); }, 100)"], cwd: directory, logPath, report: event => { events.push(event); if (event.status === 'running') notifyStart(); } }).then(result => { finished = true; return result; });
  await started;
  assert.equal(finished, false, 'start event must be visible before the command finishes');
  const result = await running;
  assert.equal(events[0].status, 'running');
  assert.equal(events.at(-1).status, 'passed');
  assert.equal(result.exitCode, 0);
  assert.match(await readFile(logPath, 'utf8'), /first[\s\S]*last/);
  assert.equal(result.log, logPath);
});

test('failed and timed-out gates retain diagnostics, exit status and bounded summaries', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'workflow-gate-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  for (const timeout of [false, true]) {
    const logPath = join(directory, timeout ? 'timeout.log' : 'failure.log');
    let failure;
    try {
      await runGate({ name: 'example', args: ['-e', timeout ? "console.log('waiting');setInterval(() => {}, 1000)" : "console.error('x'.repeat(5000));process.exit(2)"], cwd: directory, logPath, timeout: timeout ? 1000 : 10000, report() {} });
    } catch (error) { failure = error; }
    assert.ok(failure);
    assert.ok(failure.message.length < 2500);
    assert.equal(failure.gate.status, timeout ? 'timed-out' : 'failed');
    if (timeout) assert.notEqual(failure.gate.exitCode, 0, 'termination preserves the platform exit status');
    else assert.equal(failure.gate.exitCode, 2);
    assert.match(await readFile(logPath, 'utf8'), timeout ? /"status":"timed-out"/ : /x{5000}/);
  }
});

test('gate timeout terminates descendants inheriting its output pipes', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'workflow-gate-tree-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const script = "const {spawn}=require('node:child_process');const child=spawn(process.execPath,['-e',\"setInterval(() => require('node:fs').appendFileSync('heartbeat','x'),50);setTimeout(() => process.exit(),60000)\"],{stdio:['ignore','inherit','inherit']});require('node:fs').writeFileSync('descendant.pid',String(child.pid));setTimeout(() => {},60000);";
  const started = Date.now();
  await assert.rejects(runGate({ name: 'nested', args: ['-e', script], cwd: directory, logPath: join(directory, 'nested.log'), timeout: 1500, report() {} }), /timed-out/);
  const pid = Number(await readFile(join(directory, 'descendant.pid'), 'utf8'));
  t.after(() => { try { process.kill(pid); } catch (error) { if (error.code !== 'ESRCH') throw error; } });
  if (process.platform === 'win32') assert.throws(() => process.kill(pid, 0), error => error.code === 'ESRCH', 'descendant must not survive a gate timeout');
  const heartbeat = () => readFile(join(directory, 'heartbeat'), 'utf8').catch(error => { if (error.code === 'ENOENT') return ''; throw error; });
  const stopped = await heartbeat();
  await new Promise(resolve => setTimeout(resolve, 200));
  assert.equal(await heartbeat(), stopped, 'descendant activity stops, even while POSIX waits to reap a zombie PID');
  assert.ok(Date.now() - started < 20000, 'timeout must not wait for inherited pipes from surviving descendants');
});
