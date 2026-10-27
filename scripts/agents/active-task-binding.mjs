import { realpath } from 'node:fs/promises';
import { resolve } from 'node:path';
import { git, samePath } from './agent-store.mjs';
import { realDirectoryWithoutLinks } from './worktree-path.mjs';

export const originDevelopmentBaseRef = 'refs/remotes/origin/development';
const commitPattern = /^[0-9a-f]{40,64}$/i;
const readinessFields = ['base', 'branch', 'checkout', 'identity', 'readyAt', 'repository', 'schemaVersion'];

function isRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function identity(entry) {
  return { owner: entry.owner, task: entry.task, session: entry.session };
}

function sameIdentity(left, right) {
  return isRecord(left) && left.owner === right.owner && left.task === right.task && left.session === right.session;
}

function rejectUnsupportedReservation(entry) {
  if (entry.reservation?.schemaVersion === 1 && !['completed', 'handed-off', 'reassigned'].includes(entry.status)) {
    throw new Error('Unsupported active schema-v1 reservation: the original coordinator checkout and readiness receipt were not recorded. The entry was left unchanged; preserve it and have the coordinator confirm the worker stopped before creating a replacement with a new owner/task. No path will be inferred.');
  }
}

function validRepositoryPath(path) {
  return typeof path === 'string' && path.length > 0 && resolve(path) === path;
}

function validBase(base, reservation = false) {
  if (!isRecord(base) || typeof base.ref !== 'string') return false;
  if (reservation && base.ref !== originDevelopmentBaseRef) return false;
  if (!reservation && base.ref === 'existing-checkout') return base.sha === null || typeof base.sha === 'string' && commitPattern.test(base.sha);
  return base.ref === originDevelopmentBaseRef && typeof base.sha === 'string' && commitPattern.test(base.sha);
}

function readinessMatches(entry, readiness) {
  const binding = entry.binding;
  const reservation = entry.reservation;
  return isRecord(readiness) && reservation?.schemaVersion === 2 && binding &&
    Object.keys(readiness).sort().join('\0') === readinessFields.join('\0') &&
    readiness.schemaVersion === 1 && sameIdentity(readiness.identity, identity(entry)) &&
    Object.keys(readiness.identity ?? {}).sort().join('\0') === ['owner', 'session', 'task'].join('\0') &&
    readiness.checkout === binding.checkout && readiness.checkout.length <= 4096 &&
    readiness.repository === binding.repository && readiness.repository.length <= 4096 &&
    readiness.branch === binding.branch && typeof readiness.branch === 'string' && readiness.branch.length <= 1024 &&
    isRecord(readiness.base) && Object.keys(readiness.base).sort().join('\0') === ['ref', 'sha'].join('\0') &&
    readiness.base.ref === reservation.base.ref && readiness.base.sha === reservation.base.sha &&
    typeof readiness.readyAt === 'string' && readiness.readyAt.length <= 32 &&
    Number.isFinite(Date.parse(readiness.readyAt)) && new Date(readiness.readyAt).toISOString() === readiness.readyAt;
}

export function validateBindingMetadata(entry) {
  rejectUnsupportedReservation(entry);
  if (entry.reservation !== undefined) {
    const reservation = entry.reservation;
    if (!isRecord(reservation) || ![1, 2].includes(reservation.schemaVersion) || !sameIdentity(reservation.identity, identity(entry)) ||
        !validRepositoryPath(reservation.repository) || !validBase(reservation.base, true)) {
      throw new Error('Invalid active-task reservation identity or base.');
    }
    if (reservation.schemaVersion === 2 && (!validRepositoryPath(reservation.coordinatorCheckout) || !validRepositoryPath(reservation.primaryCheckout))) {
      throw new Error('Invalid active-task coordinator checkout identity.');
    }
    if (!entry.binding && (entry.checkout !== undefined || entry.head !== undefined)) throw new Error('An unbound reservation cannot claim a checkout or HEAD.');
  }
  if (entry.binding !== undefined) {
    const binding = entry.binding;
    if (!isRecord(binding) || binding.schemaVersion !== 1 || !sameIdentity(binding.identity, identity(entry)) ||
        !validRepositoryPath(binding.checkout) || !validRepositoryPath(binding.repository) ||
        binding.branch !== null && (typeof binding.branch !== 'string' || !binding.branch.startsWith('refs/heads/')) ||
        !validBase(binding.base) || typeof binding.boundAt !== 'string' || binding.checkout !== entry.checkout) {
      throw new Error('Invalid active-task binding identity.');
    }
    if (entry.reservation && (binding.repository !== entry.reservation.repository || JSON.stringify(binding.base) !== JSON.stringify(entry.reservation.base))) {
      throw new Error('Active-task binding does not match its reservation base.');
    }
  } else if (entry.checkout !== undefined && entry.reservation) {
    throw new Error('An unbound reservation cannot claim a checkout.');
  }
  if (entry.readiness !== undefined && !readinessMatches(entry, entry.readiness)) throw new Error('Reserved worker readiness receipt does not match its assignment identity.');
  if (entry.reservation?.schemaVersion === 2 && entry.status === 'handed-off' && entry.readiness === undefined) {
    throw new Error('A reserved worker handoff requires a recorded edit-ready receipt.');
  }
}

export async function commonGitDirectory(root) {
  const directory = git(root, ['rev-parse', '--git-common-dir']).stdout.trim();
  return realpath(resolve(root, directory));
}

function pathKey(path) {
  const normalized = resolve(path);
  return process.platform === 'win32' ? normalized.toLowerCase() : normalized;
}

async function inspectWorktree(repo, requestedPath, { requireBranch = false } = {}) {
  const path = await realDirectoryWithoutLinks(requestedPath, 'Worker worktree');
  const record = repo.worktrees.find((item) => item.worktree && pathKey(item.worktree) === pathKey(path));
  if (!record || Object.hasOwn(record, 'locked') || Object.hasOwn(record, 'prunable')) throw new Error('Worker must be a registered, unlocked Git worktree in the same repository.');
  const top = await realpath(git(path, ['rev-parse', '--show-toplevel']).stdout.trim());
  if (pathKey(top) !== pathKey(path)) throw new Error('Worker path must be the Git worktree root.');
  const branchResult = git(path, ['symbolic-ref', '--quiet', 'HEAD'], true);
  const branch = branchResult.status === 0 ? branchResult.stdout.trim() : null;
  if (branch && record.branch && branch !== record.branch) throw new Error('Worker branch changed during binding.');
  if (requireBranch && !branch) throw new Error('Worker must be on a registered Git branch.');
  const headResult = git(path, ['rev-parse', '--verify', 'HEAD^{commit}'], true);
  const head = headResult.status === 0 ? headResult.stdout.trim() : null;
  return { path, branch, head, repository: await commonGitDirectory(path) };
}

export async function reserveBinding(repo, entry, baseSha) {
  if (!commitPattern.test(baseSha ?? '')) throw new Error('reserve requires a full fetched origin/development commit SHA.');
  try {
    git(repo.root, ['fetch', '--no-tags', 'origin', `+refs/heads/development:${originDevelopmentBaseRef}`]);
  } catch {
    throw new Error('Could not fetch origin/development; reservation was not written.');
  }
  let currentHead;
  let fetchedHead;
  try {
    currentHead = git(repo.root, ['rev-parse', '--verify', 'HEAD^{commit}']).stdout.trim();
    fetchedHead = git(repo.root, ['rev-parse', '--verify', `${originDevelopmentBaseRef}^{commit}`]).stdout.trim();
  } catch {
    throw new Error('Fetched origin/development is unavailable after fetch; reservation was not written.');
  }
  if (currentHead !== baseSha || fetchedHead !== baseSha) {
    throw new Error('The parent checkout and freshly fetched origin/development must both match the reserved base SHA exactly.');
  }
  return {
    schemaVersion: 2,
    identity: identity(entry),
    repository: await commonGitDirectory(repo.root),
    coordinatorCheckout: await realpath(repo.root),
    primaryCheckout: await realpath(repo.primary),
    base: { ref: originDevelopmentBaseRef, sha: baseSha },
  };
}

export async function startBinding(repo, entry) {
  const current = await inspectWorktree(repo, repo.root);
  return {
    schemaVersion: 1,
    identity: identity(entry),
    checkout: current.path,
    repository: current.repository,
    branch: current.branch,
    base: { ref: 'existing-checkout', sha: current.head },
    boundAt: new Date().toISOString(),
  };
}

export async function bindAssignment(entry, repo, worktreePath) {
  validateBindingMetadata(entry);
  if (!['active', 'blocked'].includes(entry.status) || entry.role !== 'worker') throw new Error('Only active or blocked worker assignments can bind a worktree.');
  if (entry.binding) throw new Error('Assignment is already bound; retain its worktree identity.');
  const targetPath = resolve(repo.root, worktreePath);
  if (entry.checkout && !(await samePath(entry.checkout, targetPath))) throw new Error('Binding cannot relocate an existing assignment checkout.');
  const protectedPaths = [repo.primary, entry.reservation?.coordinatorCheckout, entry.reservation?.primaryCheckout,
    ...(entry.reservation?.schemaVersion === 1 ? [repo.root] : [])].filter(Boolean);
  if (entry.reservation && (await Promise.all(protectedPaths.map((path) => samePath(targetPath, path)))).some(Boolean)) {
    throw new Error('Reserved worker must bind a separate worktree outside the coordinator and primary checkouts.');
  }
  const current = await inspectWorktree(repo, targetPath, { requireBranch: Boolean(entry.reservation) });
  const repository = await commonGitDirectory(repo.root);
  if (current.repository !== repository) throw new Error('Worker worktree belongs to a different Git repository.');
  let base = { ref: 'existing-checkout', sha: current.head };
  if (entry.reservation) {
    const reserved = entry.reservation;
    if (!sameIdentity(reserved.identity, identity(entry)) || reserved.repository !== current.repository) throw new Error('Worker repository or reservation identity changed before binding.');
    if (current.head !== reserved.base.sha) throw new Error('Worker HEAD does not match the immutable reserved base.');
    if (git(current.path, ['status', '--porcelain', '--untracked-files=all']).stdout.trim()) throw new Error('Worker worktree must be clean before binding and editing.');
    base = reserved.base;
  } else if (!entry.checkout) {
    throw new Error('An unbound worker must reserve first; an existing checkout can bind only in place.');
  }
  const binding = {
    schemaVersion: 1,
    identity: identity(entry),
    checkout: current.path,
    repository: current.repository,
    branch: current.branch,
    base,
    boundAt: new Date().toISOString(),
  };
  entry.checkout = current.path;
  entry.binding = binding;
  return binding;
}

export function verifyReadinessReceipt(entry) {
  rejectUnsupportedReservation(entry);
  if (entry.reservation?.schemaVersion !== 2) return null;
  if (!readinessMatches(entry, entry.readiness)) throw new Error('Reserved worker must complete edit-ready with a matching readiness receipt before handoff.');
  return entry.readiness;
}

export async function recordEditReadiness(entry, repo, binding) {
  binding ??= await verifyAssignmentBinding(entry, repo, repo.root);
  if (entry.reservation?.schemaVersion !== 2) return null;
  if (entry.readiness) return verifyReadinessReceipt(entry);
  const current = await inspectWorktree(repo, binding.checkout, { requireBranch: true });
  if (current.head !== binding.base.sha || git(current.path, ['status', '--porcelain', '--untracked-files=all']).stdout.trim()) {
    throw new Error('Edit readiness must be recorded before editing while the worker is clean at its creation base.');
  }
  const readiness = {
    schemaVersion: 1,
    identity: identity(entry),
    checkout: binding.checkout,
    repository: binding.repository,
    branch: binding.branch,
    base: { ...binding.base },
    readyAt: new Date().toISOString(),
  };
  if (!readinessMatches(entry, readiness)) throw new Error('Could not create a bounded readiness receipt for this worker identity.');
  entry.readiness = readiness;
  return readiness;
}

export async function verifyAssignmentBinding(entry, repo, currentCheckout) {
  validateBindingMetadata(entry);
  const binding = entry.binding;
  if (!binding) throw new Error('Worker assignment is unbound; bind its actual Git worktree before editing or handoff.');
  if (currentCheckout && !(await samePath(currentCheckout, binding.checkout))) throw new Error('Command must run in the bound worker checkout.');
  const current = await inspectWorktree(repo, binding.checkout);
  if (pathKey(current.path) !== pathKey(binding.checkout) || current.repository !== binding.repository || current.branch !== binding.branch) {
    throw new Error('Bound worker checkout, repository, or branch identity changed.');
  }
  if (binding.base.sha && (!current.head || git(current.path, ['merge-base', '--is-ancestor', binding.base.sha, current.head], true).status !== 0)) {
    throw new Error('Worker HEAD no longer descends from its immutable creation base.');
  }
  return binding;
}

export async function verifyHandoffAssignment(entry, repo, currentCheckout) {
  if (entry.binding || entry.reservation) return verifyAssignmentBinding(entry, repo, currentCheckout);
  if (entry.role !== 'worker' || entry.reassignedFrom && entry.status !== 'handed-off') {
    throw new Error('Unbound reassigned workers cannot hand off; continue them with a fresh binding in the source checkout.');
  }
  if (!entry.checkout || !(await samePath(entry.checkout, currentCheckout ?? repo.root))) {
    throw new Error('Legacy worker handoff must run in its recorded checkout.');
  }
  return null;
}

export async function registeredAssignmentBase(entry, current) {
  validateBindingMetadata(entry);
  const provenance = entry.binding ?? entry.reservation;
  if (!provenance) return current.head;
  if (provenance.repository !== current.repository) throw new Error('Registered worker belongs to a different Git repository than its assignment.');
  if (entry.binding) {
    if (!(await samePath(entry.checkout, current.path)) || !(await samePath(entry.binding.checkout, current.path)) || entry.binding.branch !== current.branch) {
      throw new Error('Registered worker path or branch does not match its active-task binding.');
    }
    if (entry.binding.base.sha && (!current.head || git(current.path, ['merge-base', '--is-ancestor', entry.binding.base.sha, current.head], true).status !== 0)) {
      throw new Error('Registered worker does not descend from its immutable creation base.');
    }
  } else if (current.head !== entry.reservation.base.sha) {
    throw new Error('Reserved worker must be registered at its exact creation base before edits.');
  }
  return provenance.base.sha;
}
