import { spawn, spawnSync } from 'node:child_process';
import { open } from 'node:fs/promises';

function defaultTimeout() {
  const timeout = Number(process.env.WORKFLOW_GATE_TIMEOUT);
  return Number.isInteger(timeout) && timeout > 0 && timeout <= 2_147_483_647 ? timeout : 600_000;
}

export function packageScriptCommand(script, platform = process.platform) {
  if (typeof script !== 'string' || !/^[a-zA-Z0-9:_-]+$/.test(script)) throw new Error('Invalid package script name.');
  return platform === 'win32'
    ? { command: 'cmd.exe', args: ['/d', '/s', '/c', `pnpm run ${script}`] }
    : { command: 'pnpm', args: ['run', script] };
}

export async function runGate({ name, command = process.execPath, args, cwd, logPath, timeout = defaultTimeout(), report = event => console.error(JSON.stringify(event)) }) {
  const log = await open(logPath, 'wx', 0o600);
  const started = Date.now();
  let tail = '', timedOut = false, spawnError, terminationError;
  let timer;
  try {
    report({ gate: name, status: 'running', log: logPath });
    const child = spawn(command, args, { cwd, detached: process.platform !== 'win32', windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    const capture = async stream => {
      for await (const chunk of stream) {
        await log.write(chunk);
        tail = (tail + chunk.toString('utf8')).slice(-2000);
      }
    };
    const closed = new Promise(resolve => {
      child.on('error', error => { spawnError = error; });
      child.on('close', (exitCode, signal) => resolve({ exitCode, signal }));
    });
    timer = setTimeout(() => {
      timedOut = true;
      if (!child.pid) return;
      // Gates own this process tree; nested pnpm/test commands must stop with it.
      if (process.platform === 'win32') {
        const stopped = spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, encoding: 'utf8', timeout: 10_000 });
        if (stopped.error || stopped.status !== 0) { terminationError = stopped.error?.message ?? stopped.stderr; child.kill(); }
      } else {
        try { process.kill(-child.pid, 'SIGKILL'); }
        catch (error) { if (error.code !== 'ESRCH') { terminationError = error.message; child.kill('SIGKILL'); } }
      }
    }, timeout);
    const [exit] = await Promise.all([closed, capture(child.stdout), capture(child.stderr)]);
    const result = { name, status: timedOut ? 'timed-out' : spawnError || exit.exitCode !== 0 ? 'failed' : 'passed', ...exit, log: logPath, durationMs: Date.now() - started, summary: tail.trim(), terminationError };
    if (spawnError) await log.write(`\n${spawnError.stack ?? spawnError.message}\n`);
    await log.write(`\n[gate-result] ${JSON.stringify({ ...result, summary: undefined })}\n`);
    report({ gate: name, status: result.status, exitCode: result.exitCode, log: logPath });
    if (result.status !== 'passed') {
      const error = new Error(`Gate ${name} ${result.status}; log: ${logPath}\n${spawnError?.message ?? result.summary}`);
      error.gate = result;
      throw error;
    }
    return result;
  } finally {
    clearTimeout(timer);
    await log.close();
  }
}
