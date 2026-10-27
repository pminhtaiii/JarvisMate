import { lstat, readdir, realpath } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { git, readJson, repository, samePath } from './agent-store.mjs';
import { validateSessionRef } from './owned-handoff.mjs';

const usage = `Usage: node scripts/agents/recovery-report.mjs [--owner <id>] [--task <id>] [--root <checkout>]`;

function parse(args) {
  const values = {};
  for (let index = 0; index < args.length; index += 1) {
    const name = args[index].slice(2);
    const value = args[index + 1];
    if (!args[index].startsWith('--') || !['owner', 'task', 'root'].includes(name) || Object.hasOwn(values, name) || !value?.trim() || value.startsWith('--')) throw new Error(usage);
    values[name] = value;
    index += 1;
  }
  for (const name of ['owner', 'task']) {
    if (values[name] && !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(values[name])) throw new Error(`Invalid --${name} ID.`);
  }
  return values;
}

async function optionalJson(path) {
  const stat = await lstat(path).catch((error) => {
    if (error.code === 'ENOENT') return null;
    throw error;
  });
  if (!stat) return null;
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Expected a regular state file: ${path}`);
  return readJson(path);
}

async function agentRoot(repo) {
  const directory = resolve(repo.primary, '.agent-work');
  const stat = await lstat(directory).catch((error) => {
    if (error.code === 'ENOENT') return null;
    throw error;
  });
  if (!stat) return null;
  if (!stat.isDirectory() || stat.isSymbolicLink() || await realpath(directory) !== directory) throw new Error('Managed agent root must be a real directory.');
  return directory;
}

async function agentDataDirectory(repo, name) {
  const root = await agentRoot(repo);
  if (!root) return null;
  const directory = resolve(root, name);
  const stat = await lstat(directory).catch((error) => {
    if (error.code === 'ENOENT') return null;
    throw error;
  });
  if (!stat) return null;
  if (!stat.isDirectory() || stat.isSymbolicLink() || await realpath(directory) !== directory) throw new Error(`Managed ${name} directory must be a real directory.`);
  return directory;
}

async function assignments(repo) {
  const directory = await agentDataDirectory(repo, 'state');
  if (!directory) return [];
  const statePath = resolve(directory, 'active-tasks.json');
  const entries = await optionalJson(statePath) ?? [];
  if (!Array.isArray(entries) || entries.some((entry) => !entry || typeof entry.owner !== 'string' || typeof entry.task !== 'string' || !['active', 'blocked', 'completed', 'handed-off', 'reassigned'].includes(entry.status))) throw new Error('Invalid shared task state; no recovery report was produced.');
  return entries;
}

async function receipts(repo) {
  const directory = await agentDataDirectory(repo, 'worktree-receipts');
  if (!directory) return [];
  const records = [];
  for (const name of await readdir(directory)) {
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.json$/.test(name)) continue;
    const record = await optionalJson(resolve(directory, name));
    if (record) records.push(record);
  }
  return records;
}

async function listedWorktree(repo, checkout) {
  if (typeof checkout !== 'string' || !checkout) return null;
  for (const entry of repo.worktrees) {
    if (await samePath(entry.worktree, checkout)) return entry;
  }
  return null;
}

function names(root, args) {
  return git(root, args).stdout.split('\0').filter(Boolean);
}

async function receiptFor(records, assignment, checkout) {
  if (checkout) {
    for (const record of records) {
      if (record.owner === assignment.owner && record.task === assignment.task && typeof record.path === 'string' && await samePath(record.path, checkout)) return record;
    }
  }
  return records.find((record) => record.owner === assignment.owner && record.task === assignment.task) ?? null;
}

async function receiptSummary(receipt, checkout) {
  if (!receipt) return null;
  return {
    id: receipt.id ?? null,
    status: receipt.status ?? 'unknown',
    pathMatches: Boolean(checkout && typeof receipt.path === 'string' && await samePath(receipt.path, checkout)),
  };
}

async function sessionMarker(repo, session) {
  if (typeof session !== 'string') return null;
  try { validateSessionRef(session); }
  catch { return null; }
  try {
    const managedRoot = await agentRoot(repo);
    if (!managedRoot) return null;
    const directory = resolve(managedRoot, session);
    const stat = await lstat(directory);
    if (!stat.isDirectory() || stat.isSymbolicLink() || await realpath(directory) !== directory) return null;
    const path = resolve(directory, 'session.json');
    const marker = await optionalJson(path);
    if (!marker) return null;
    return { status: marker.status ?? 'unknown', startedAt: marker.startedAt ?? null, finishedAt: marker.finishedAt ?? null };
  } catch {
    return null;
  }
}

async function summarize(repo, assignment, worktreeReceipts) {
  const actual = await listedWorktree(repo, assignment.checkout);
  const listedPath = actual ? resolve(actual.worktree) : null;
  const stat = listedPath ? await lstat(listedPath).catch((error) => {
    if (error.code === 'ENOENT') return null;
    throw error;
  }) : null;
  const canonical = stat?.isDirectory() && !stat.isSymbolicLink() ? await realpath(listedPath) : null;
  const checkout = canonical ?? listedPath;
  const receipt = await receiptSummary(await receiptFor(worktreeReceipts, assignment, checkout), checkout);
  let worktree = null;
  if (actual) {
    if (!canonical) {
      worktree = { path: checkout, available: false, reason: 'Git lists this worktree but its checkout path is missing or redirected.' };
    } else {
      const top = git(listedPath, ['rev-parse', '--show-toplevel'], true);
      if (top.status !== 0 || !(await samePath(top.stdout.trim(), checkout))) {
        worktree = { path: checkout, available: false, reason: 'Git worktree metadata no longer resolves to this checkout.' };
      } else {
        const head = git(listedPath, ['rev-parse', 'HEAD'], true);
        const branch = git(listedPath, ['symbolic-ref', '--quiet', 'HEAD'], true);
        worktree = {
          path: checkout,
          available: true,
          branch: branch.status === 0 ? branch.stdout.trim() : null,
          head: head.status === 0 ? head.stdout.trim() : null,
          stagedPaths: names(listedPath, ['diff', '--cached', '--name-only', '-z']),
          modifiedPaths: names(listedPath, ['diff', '--name-only', '-z']),
          untrackedPaths: names(listedPath, ['ls-files', '--others', '--exclude-standard', '-z']),
        };
      }
    }
  }
  return {
    assignment: {
      owner: assignment.owner,
      task: assignment.task,
      status: assignment.status,
      session: assignment.session ?? null,
      checkout: assignment.checkout ?? null,
    },
    checkpoint: {
      source: 'active-task record',
      updatedAt: assignment.updatedAt ?? null,
      next: assignment.next ?? null,
      verification: assignment.verification ?? null,
      sessionMarker: await sessionMarker(repo, assignment.session),
    },
    worktree,
    receipt,
    agent: {
      status: 'unknown',
      evidence: null,
      note: 'Local assignment, session, receipt, and Git records do not prove an agent is running or stopped.',
    },
  };
}

async function run(args) {
  if (args.length === 1 && ['--help', '-h'].includes(args[0])) return console.log(usage);
  const values = parse(args);
  const repo = await repository(values.root ?? resolve(dirname(fileURLToPath(import.meta.url)), '../..'));
  const [entries, worktreeReceipts] = await Promise.all([assignments(repo), receipts(repo)]);
  const selected = entries.filter((entry) => ['active', 'blocked'].includes(entry.status) && (!values.owner || entry.owner === values.owner) && (!values.task || entry.task === values.task));
  const report = [];
  for (const assignment of selected) report.push(await summarize(repo, assignment, worktreeReceipts));
  console.log(JSON.stringify({ generatedAt: new Date().toISOString(), source: 'local contributor state and Git worktrees', assignments: report }, null, 2));
}

run(process.argv.slice(2)).catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
