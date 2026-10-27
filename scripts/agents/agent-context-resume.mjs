import { lstat, readFile, realpath, stat } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { git as agentStoreGit, repository as agentRepository, samePath as canonicalSamePath } from './agent-store.mjs';
import { checkout, fail, normalizedRepoPath, parseTasks, repoFile } from './agent-context-common.mjs';

function changedPaths(output) {
  const records = output.split('\0');
  const changed = [];
  for (let index = 0; index < records.length; index += 1) {
    const record = records[index];
    if (!record) continue;
    const status = record.slice(0, 2);
    const path = record.slice(3).replace(/[\r\n\t]/g, (character) => ({
      '\r': '\\r',
      '\n': '\\n',
      '\t': '\\t',
    })[character]);
    if (status.includes('R') || status.includes('C')) {
      const original = (records[++index] ?? '').replace(/[\r\n\t]/g, (character) => ({
        '\r': '\\r',
        '\n': '\\n',
        '\t': '\\t',
      })[character]);
      changed.push(status + ' ' + original + ' -> ' + path);
    } else {
      changed.push(status + ' ' + path);
    }
  }
  return changed;
}

export function statIfPresent(path) {
  return lstat(path).catch((error) => {
    if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT') return null;
    throw error;
  });
}

export async function readWorkerState(root) {
  const repo = await agentRepository(root);
  const agentDirectory = resolve(repo.primary, '.agent-work');
  const stateDirectory = resolve(agentDirectory, 'state');
  const agentInfo = await statIfPresent(agentDirectory);
  if (!agentInfo) return { entries: [], worktrees: repo.worktrees, source: null };
  if (!agentInfo.isDirectory() || agentInfo.isSymbolicLink() || await realpath(agentDirectory) !== agentDirectory)
    fail('Shared agent-work directory must be a regular directory.');
  const stateInfo = await statIfPresent(stateDirectory);
  if (!stateInfo) return { entries: [], worktrees: repo.worktrees, source: null };
  if (!stateInfo.isDirectory() || stateInfo.isSymbolicLink() || await realpath(stateDirectory) !== stateDirectory)
    fail('Shared agent state directory must be a regular directory.');

  const storePath = resolve(stateDirectory, 'active-tasks.json');
  const lockPath = resolve(stateDirectory, 'active-task.lock');
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (await statIfPresent(lockPath)) {
      if (attempt === 0) {
        await new Promise((resolvePromise) => setTimeout(resolvePromise, 50));
        continue;
      }
      fail('Shared active-task state is being updated; retry the resume report.');
    }
    const storeInfo = await statIfPresent(storePath);
    if (!storeInfo) return { entries: [], worktrees: repo.worktrees, source: null };
    if (!storeInfo.isFile() || storeInfo.isSymbolicLink()) fail('Shared active-task state must be a regular file.');
    let entries;
    try {
      entries = JSON.parse(await readFile(storePath, 'utf8'));
    } catch (error) {
      fail(`Could not read shared active-task state: ${error.message}`);
    }
    if (await statIfPresent(lockPath)) {
      if (attempt === 0) {
        await new Promise((resolvePromise) => setTimeout(resolvePromise, 50));
        continue;
      }
      fail('Shared active-task state changed during the read; retry the resume report.');
    }
    if (!Array.isArray(entries) || entries.some((entry) =>
      !entry || typeof entry.owner !== 'string' || typeof entry.task !== 'string' ||
      !['active', 'blocked', 'completed', 'handed-off', 'reassigned'].includes(entry.status) ||
      typeof entry.summary !== 'string' || typeof entry.next !== 'string' ||
      (entry.role !== undefined && !['coordinator', 'worker'].includes(entry.role)))) {
      fail('Shared active-task state has an unsupported shape.');
    }
    return { entries, worktrees: repo.worktrees, source: normalizedRepoPath(root, storePath) };
  }
  fail('Shared active-task state is being updated; retry the resume report.');
}

export function evidencePointers(text) {
  const normalized = text.replaceAll('\\', '/');
  return [...normalized.matchAll(/https?:\/\/[^\s),>]+|(?:\.agent-work|docs|specs|context)\/[A-Za-z0-9._/-]+/g)]
    .map((match) => match[0].replace(/[.,;:!?]+$/, ''));
}

export function taskReadiness(parsed) {
  const byId = new Map(parsed.tasks.map((task) => [task.id, task]));
  const ready = [];
  const blocked = [];
  for (const task of parsed.tasks.filter((entry) => !entry.checked)) {
    if (!task.dependenciesDeclared) {
      blocked.push({ task, dependencies: [], reason: 'dependencies unspecified' });
      continue;
    }
    const dependencies = task.dependencies.map((id) => {
      const dependency = byId.get(id);
      return { id, state: dependency ? (dependency.checked ? 'checked' : 'open') : 'unresolved' };
    });
    if (dependencies.every((dependency) => dependency.state === 'checked')) ready.push({ task, dependencies });
    else blocked.push({ task, dependencies, reason: null });
  }
  return { ready, blocked };
}

export function truncate(text, limit = 180) {
  const value = text.trim();
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value;
}

export function verificationSummary(text) {
  const value = text.replace(/\s+/g, ' ').trim();
  const outcomes = [...value.matchAll(/\b(?:fail(?:ed|ure|ures|ing)?|error|not[- ]run|timed[- ]out|timeout|blocked|pending|unavailable|skipped)\b/gi)]
    .map((match) => value.slice(Math.max(0, match.index - 45), Math.min(value.length, match.index + match[0].length + 75)));
  const suffix = [...new Set(outcomes)].slice(0, 3).join(' | ');
  return truncate(suffix ? `${truncate(value, 140)} | recorded outcome(s): ${suffix}` : value, 400);
}

export async function resumeReport(root, tasksInput, authorizationInputs) {
  const current = await checkout(root);
  const status = agentStoreGit(root, ['status', '--porcelain=v1', '-z', '--untracked-files=all']);
  const changed = changedPaths(status.stdout);
  let parsed = null;
  let tasksFile = null;
  if (tasksInput) {
    tasksFile = await repoFile(root, tasksInput, '--tasks');
    parsed = parseTasks((await readFile(tasksFile, 'utf8')).replace(/^\uFEFF/, ''), tasksInput);
  }

  const authorization = [];
  if (tasksFile) {
    const decisionsInput = normalizedRepoPath(root, resolve(dirname(tasksFile), 'contracts', 'decisions.md'));
    const decisions = await repoFile(root, decisionsInput, 'authorization evidence pointer', true);
    if ((await statIfPresent(decisions))?.isFile()) authorization.push(normalizedRepoPath(root, decisions));
  }
  for (const input of authorizationInputs) {
    const file = await repoFile(root, input, '--authorization');
    if (!(await stat(file)).isFile()) fail(`Authorization evidence pointer is not a file: ${input}`);
    authorization.push(normalizedRepoPath(root, file));
  }

  const workerState = await readWorkerState(root);
  const workers = workerState.entries.filter((entry) => entry.role === 'worker');
  const counts = Object.fromEntries(['active', 'blocked', 'handed-off', 'completed', 'reassigned'].map((status) =>
    [status, workers.filter((entry) => entry.status === status).length]));
  const worktreePaths = workerState.worktrees.map((entry) => entry.worktree).filter(Boolean);
  const taskIds = new Set(parsed?.tasks.map((task) => task.id) ?? []);
  const relevantAssignments = [];
  for (const entry of workerState.entries) {
    if (
      !['active', 'blocked', 'handed-off'].includes(entry.status) ||
      typeof entry.checkout !== 'string' ||
      entry.checkout.length === 0
    ) continue;
    let listed = false;
    for (const path of worktreePaths) {
      if (await canonicalSamePath(path, entry.checkout)) {
        listed = true;
        break;
      }
    }
    if (!listed) continue;
    if (await canonicalSamePath(root, entry.checkout) || (entry.role === 'worker' && taskIds.has(entry.task))) {
      relevantAssignments.push(entry);
    }
  }
  relevantAssignments.sort((left, right) =>
    String(right.updatedAt ?? '').localeCompare(String(left.updatedAt ?? '')));
  const pointers = new Map();
  for (const entry of relevantAssignments) {
    const found = [...new Set([
      ...evidencePointers(entry.verification ?? ''),
      ...evidencePointers(entry.result ?? ''),
    ])];
    if (found.length) pointers.set(`${entry.owner}/${entry.task}`, found.slice(0, 5));
  }
  const readiness = parsed ? taskReadiness(parsed) : { ready: [], blocked: [] };

  process.stdout.write(`Checkout: ${current.root}\nBranch: ${current.branch ?? '(detached)'}\nHEAD: ${current.head}\n`);
  process.stdout.write(changed.length
    ? `Working tree: ${changed.length} changed path(s)\n${changed.slice(0, 8).map((path) => `  ${path}`).join('\n')}${changed.length > 8 ? '\n  …' : ''}\n`
    : 'Working tree: clean\n');

  if (!parsed) {
    process.stdout.write('Task ledger: not supplied; no task candidates or dependencies assessed.\n');
  } else {
    const checked = parsed.tasks.filter((task) => task.checked).length;
    const candidates = readiness.ready.slice(0, 5);
    process.stdout.write(`Task ledger: ${normalizedRepoPath(root, tasksFile)} (${checked} checked; ${parsed.tasks.length - checked} open)\n`);
    process.stdout.write('Ledger-derived task candidates (verify integrated dependency evidence and current authorization before acting):\n');
    if (!candidates.length) process.stdout.write('  none; dependencies are open, external, or unspecified\n');
    for (const { task, dependencies } of candidates) {
      const details = dependencies.length ? dependencies.map((dependency) => `${dependency.id} checked`).join(', ') : 'none';
      process.stdout.write(`  ${task.id} [${task.phase?.title ?? 'no phase'}] deps: ${details} — ${truncate(task.line.replace(/^\s*[-*+]\s+\[[ xX]\]\s+/, ''))}\n`);
    }
    if (readiness.ready.length > candidates.length) process.stdout.write(`  … ${readiness.ready.length - candidates.length} more candidate(s)\n`);
    const blocked = readiness.blocked.slice(0, 5);
    if (blocked.length) {
      process.stdout.write('Other open tasks and dependency state:\n');
      for (const { task, dependencies, reason } of blocked) {
        const details = reason ?? dependencies.map((dependency) => `${dependency.id} ${dependency.state}`).join(', ');
        process.stdout.write(`  ${task.id}: ${details}\n`);
      }
      if (readiness.blocked.length > blocked.length) process.stdout.write(`  … ${readiness.blocked.length - blocked.length} more open task(s)\n`);
    }
  }

  process.stdout.write('Authorization evidence pointers (pointers only; no grant is inferred):\n');
  const uniqueAuthorization = [...new Set(authorization)];
  process.stdout.write(uniqueAuthorization.length
    ? `${uniqueAuthorization.map((path) => `  ${path}`).join('\n')}\n`
    : '  none supplied or found\n');

  const storeLabel = workerState.source ?? '(shared store not present)';
  process.stdout.write(`Worker state from ${storeLabel}: ${Object.entries(counts).map(([status, count]) => `${status} ${count}`).join('; ')}\n`);
  process.stdout.write('Matching assignment records (shared-state snapshot):\n');
  const shown = relevantAssignments.slice(0, 8);
  if (!shown.length) process.stdout.write('  none for this checkout or ledger task IDs\n');
  for (const entry of shown) {
    process.stdout.write(`  ${entry.role ?? 'coordinator'} ${entry.owner}/${entry.task} [${entry.status}] — ${truncate(entry.summary, 120)}; next: ${truncate(entry.next, 140)}\n`);
    if (entry.verification) process.stdout.write(`    recorded verification (not revalidated): ${verificationSummary(entry.verification)}\n`);
    const found = pointers.get(`${entry.owner}/${entry.task}`) ?? [];
    if (found.length) process.stdout.write(`    recorded pointers (not revalidated): ${found.join(', ')}\n`);
  }
  if (relevantAssignments.length > shown.length)
    process.stdout.write(`  … ${relevantAssignments.length - shown.length} more assignment(s) omitted\n`);
  process.stdout.write('Recheck the source files and evidence before resuming; this report is read-only and never authorizes work.\n');
}
