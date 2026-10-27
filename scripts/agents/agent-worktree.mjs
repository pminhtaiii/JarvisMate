import { createHash } from 'node:crypto';
import { lstat, readFile, realpath } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { atomicWrite, dataDirectory, git, inside, readJson, repository, samePath, withLock } from './agent-store.mjs';
import { commonGitDirectory, registeredAssignmentBase } from './active-task-binding.mjs';
import { realDirectoryWithoutLinks } from './worktree-path.mjs';

const usage = `Usage:
  node scripts/agents/agent-worktree.mjs register --id <id> --path <worker> --integration-ref <branch> --session <date/id> --owner <owner> --task <task> [--external-app-owned]
  node scripts/agents/agent-worktree.mjs accept --id <id> --evidence <repo-file> --workers-stopped
  node scripts/agents/agent-worktree.mjs cleanup --id <id> [--apply]
All commands accept --root <checkout>. External app-owned worktrees require the flag and are never removed by this helper.
Cleanup previews by default, retains branches, and never force-removes a checkout. accept attests that workers stopped and the handoff was reviewed.`;

function argumentsFor(args) {
  const [command, ...rest] = args;
  const options = { register: ['path', 'integration-ref', 'session', 'owner', 'task', 'external-app-owned'], accept: ['evidence', 'workers-stopped'], cleanup: ['apply'] };
  if (!Object.hasOwn(options, command)) throw new Error(usage);
  const values = {};
  for (let index = 0; index < rest.length; index += 1) {
    const name = rest[index].slice(2);
    if (!rest[index].startsWith('--') || !['root', 'id', ...options[command]].includes(name) || Object.hasOwn(values, name)) throw new Error(usage);
    if (['apply', 'workers-stopped', 'external-app-owned'].includes(name)) values[name] = true;
    else {
      const value = rest[++index];
      if (!value?.trim() || value.startsWith('--')) throw new Error(usage);
      values[name] = value;
    }
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(values.id ?? '')) throw new Error('A bounded --id is required.');
  const required = options[command].filter((name) => name !== 'external-app-owned');
  if (command !== 'cleanup' && required.some((name) => !values[name])) throw new Error(usage);
  return { command, values };
}

function pathKey(path) {
  const normalized = resolve(path);
  return process.platform === 'win32' ? normalized.toLowerCase() : normalized;
}

async function worker(repo, path, branch, externalAppOwned = false) {
  const area = await dataDirectory(repo, 'worktrees');
  path = await realDirectoryWithoutLinks(path, 'Worker path');
  const managed = inside(area, path);
  const dump = inside(resolve(repo.primary, '.agent-work'), path);
  if (externalAppOwned ? managed || dump : !managed) throw new Error(externalAppOwned
    ? 'External app-owned workers must be outside the managed .agent-work area.'
    : 'Worker must be inside the managed worktree area; use --external-app-owned for an external app worktree.');
  if (await samePath(path, repo.root) || await samePath(path, repo.primary)) throw new Error('Worker must be outside the invoking and primary checkouts.');
  const fresh = await repository(repo.primary);
  const record = fresh.worktrees.find((entry) => entry.worktree && pathKey(entry.worktree) === pathKey(path));
  if (!record || !record.branch || Object.hasOwn(record, 'locked') || Object.hasOwn(record, 'prunable')) throw new Error('Worker must be registered, unlocked, and on a branch.');
  if (branch && record.branch !== branch) throw new Error('Worker branch changed since registration.');
  const head = git(path, ['rev-parse', 'HEAD']).stdout.trim();
  return { path, branch: record.branch, head, repository: await commonGitDirectory(path) };
}

async function taskStates(repo) {
  const state = await dataDirectory(repo, 'state');
  const entries = await readJson(resolve(state, 'active-tasks.json')).catch((error) => {
    if (error.code === 'ENOENT') return [];
    throw error;
  });
  if (!Array.isArray(entries) || entries.some((entry) => !entry || !['active', 'blocked', 'completed', 'handed-off', 'reassigned'].includes(entry.status))) throw new Error('Invalid shared task state.');
  return entries;
}

async function evidence(repo, path) {
  path = resolve(repo.primary, path);
  if (!(await lstat(path)).isFile()) throw new Error('Evidence must be a regular file.');
  path = await realpath(path);
  if (!inside(repo.primary, path) || inside(resolve(repo.primary, '.agent-work'), path) || inside(resolve(repo.primary, '.git'), path)) throw new Error('Evidence must be outside temporary dump/Git storage and inside the primary checkout.');
  return { path, sha256: createHash('sha256').update(await readFile(path)).digest('hex') };
}

async function eligible(repo, receipt) {
  if (receipt.status !== 'accepted') throw new Error('Handoff has not been accepted with stopped workers.');
  if (receipt.externalAppOwned) throw new Error('External app-owned worktrees are never eligible for helper cleanup.');
  const current = await worker(repo, receipt.path, receipt.branch);
  if (current.head !== receipt.acceptedHead) throw new Error('Worker HEAD changed after acceptance.');
  const states = await taskStates(repo);
  if (states.some((entry) => !['completed', 'handed-off', 'reassigned'].includes(entry.status) && (!entry.checkout || resolve(entry.checkout) === current.path))) throw new Error('Worker has active or blocked assignments, or an unlocated active legacy assignment.');
  if (git(current.path, ['status', '--porcelain', '--untracked-files=all', '--ignored']).stdout.trim()) throw new Error('Worker has modified, untracked, or ignored files.');
  if (git(repo.primary, ['merge-base', '--is-ancestor', current.head, receipt.integrationRef], true).status !== 0) throw new Error('Worker tip is not integrated into the recorded integration ref.');
  const retained = await evidence(repo, receipt.evidence.path);
  if (retained.sha256 !== receipt.evidence.sha256) throw new Error('Retained evidence changed; accept the handoff again.');
  return current;
}

async function run(args) {
  if (args.length === 1 && args[0] === '--help') return console.log(usage);
  const { command, values } = argumentsFor(args);
  const repo = await repository(values.root ?? resolve(dirname(fileURLToPath(import.meta.url)), '../..'));
  const receipts = await dataDirectory(repo, 'worktree-receipts');
  const state = await dataDirectory(repo, 'state');
  const path = resolve(receipts, `${values.id}.json`);
  await withLock(resolve(receipts, 'operation.lock'), async () => withLock(resolve(state, 'active-task.lock'), async () => {
    if (command === 'register') {
      const exists = await lstat(path).catch((error) => { if (error.code !== 'ENOENT') throw error; });
      if (exists) throw new Error('Receipt already exists; retain its ownership history.');
      const current = await worker(repo, resolve(repo.primary, values.path), undefined, Boolean(values['external-app-owned']));
      const integrationRef = values['integration-ref'].startsWith('refs/heads/') ? values['integration-ref'] : `refs/heads/${values['integration-ref']}`;
      git(repo.primary, ['check-ref-format', integrationRef]);
      git(repo.primary, ['rev-parse', '--verify', '--end-of-options', `${integrationRef}^{commit}`]);
      if (!/^\d{4}-\d{2}-\d{2}\/[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(values.session)) throw new Error('Session must be date/id.');
      const sessionDirectory = resolve(repo.primary, '.agent-work', values.session);
      if (await realpath(sessionDirectory) !== sessionDirectory) throw new Error('Session directory must not be linked.');
      const session = await readJson(resolve(sessionDirectory, 'session.json'));
      const [date, id] = values.session.split('/');
      if (session.schemaVersion !== 1 || session.workspace !== 'project' || session.date !== date || session.id !== id || !['active', 'finished'].includes(session.status)) throw new Error('Invalid managed session.');
      const states = await taskStates(repo);
      const assignment = states.find((entry) => entry.owner === values.owner && entry.task === values.task);
      if (assignment?.session && assignment.session !== values.session) throw new Error('Worktree receipt session does not match its active-task assignment.');
      const base = assignment ? await registeredAssignmentBase(assignment, current) : current.head;
      await atomicWrite(path, JSON.stringify({ schemaVersion: 1, id: values.id, ...current, base, externalAppOwned: Boolean(values['external-app-owned']), integrationRef, session: values.session, owner: values.owner, task: values.task, status: 'registered' }, null, 2) + '\n');
      return console.log(JSON.stringify({ id: values.id, registered: true, path: current.path }));
    }
    const receipt = await readJson(path);
    if (receipt.schemaVersion !== 1 || receipt.id !== values.id || typeof receipt.path !== 'string' || typeof receipt.branch !== 'string' || !/^refs\/heads\//.test(receipt.integrationRef ?? '') || receipt.externalAppOwned !== undefined && typeof receipt.externalAppOwned !== 'boolean') throw new Error('Invalid ownership receipt.');
    if (command === 'accept') {
      const current = await worker(repo, receipt.path, receipt.branch, receipt.externalAppOwned === true);
      const states = await taskStates(repo);
      if (!states.some((entry) => entry.owner === receipt.owner && entry.task === receipt.task && ['completed', 'handed-off'].includes(entry.status) && entry.checkout && resolve(entry.checkout) === current.path)) throw new Error('A completed shared handoff matching owner, task, and checkout is required.');
      receipt.status = 'accepted';
      receipt.acceptedHead = current.head;
      receipt.evidence = await evidence(repo, values.evidence);
      await atomicWrite(path, JSON.stringify(receipt, null, 2) + '\n');
      return console.log(JSON.stringify({ id: values.id, accepted: true }));
    }
    const report = { id: values.id, path: receipt.path, eligible: false, removed: false };
    try { await eligible(repo, receipt); report.eligible = true; }
    catch (error) { report.reason = error.message; }
    if (values.apply && report.eligible) {
      // Eligibility is checked under the task-store lock immediately before Git removal.
      git(repo.primary, ['worktree', 'remove', receipt.path]);
      receipt.status = 'removed';
      await atomicWrite(path, JSON.stringify(receipt, null, 2) + '\n');
      report.removed = true;
    }
    console.log(JSON.stringify(report, null, 2));
  }));
}

run(process.argv.slice(2)).catch((error) => { console.error(error.message); process.exitCode = 1; });
