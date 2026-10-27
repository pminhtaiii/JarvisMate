import { createHash } from 'node:crypto';
import { lstat, readFile, realpath } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { join, resolve } from 'node:path';
import { repository, git } from './agent-store.mjs';
import { reservedWindowsNamePattern } from './agent-work-session.mjs';

const sessionPattern = /^(\d{4}-\d{2}-\d{2})\/([A-Za-z0-9][A-Za-z0-9_-]{0,63})$/;

export function validateSessionRef(value) {
  const match = typeof value === 'string' && value.match(sessionPattern);
  if (!match) throw new Error('Session must be date/id.');
  if (reservedWindowsNamePattern.test(match[2])) throw new Error('Session ID is reserved on Windows.');
  const date = new Date(`${match[1]}T00:00:00.000Z`);
  if (Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== match[1]) throw new Error('Session date must be a real calendar date.');
  return value;
}

export function validateOwnedPaths(paths = []) {
  if (!Array.isArray(paths)) throw new Error('Owned paths must be supplied as repeated --owned-path options.');
  const normalized = paths.map((path) => {
    const hasControlCharacter = typeof path === 'string' && [...path].some((character) => {
      const code = character.charCodeAt(0);
      return code < 0x20 || code === 0x7f;
    });
    if (typeof path !== 'string' || !path || path.startsWith('/') || path.includes('\\') || path.includes(':') || hasControlCharacter) {
      throw new Error(`Unsafe owned path: ${String(path)}.`);
    }
    const segments = path.split('/');
    if (segments.some((part) => {
      const windowsBase = part.split('.')[0].replace(/[ .]+$/, '');
      return !part || part === '.' || part === '..' || ['.git', '.agent-work'].includes(part.toLowerCase()) || reservedWindowsNamePattern.test(windowsBase);
    })) {
      throw new Error(`Unsafe owned path: ${path}.`);
    }
    return path;
  });
  if (new Set(normalized).size !== normalized.length) throw new Error('Owned paths must be unique.');
  return normalized.sort();
}

function gitBuffer(root, args) {
  const result = spawnSync('git', args, { cwd: root, windowsHide: true, timeout: 15_000 });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(result.stderr.toString('utf8').trim() || `git ${args[0]} failed (${result.status})`);
  return result.stdout;
}

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

function indexMatchesWorktree(index, worktree) {
  if (worktree === null) return index.length === 0;
  if (!worktree || index.length !== 1) return false;
  const [entry] = index;
  if (entry.stage !== 0 || entry.sha256 !== worktree.sha256 || !['100644', '100755'].includes(entry.mode)) return false;
  return worktree.executable === null || (entry.mode === '100755') === worktree.executable;
}

function indexEntries(root) {
  const records = gitBuffer(root, ['ls-files', '--stage', '-z']).toString('utf8').split('\0').filter(Boolean);
  return records.map((record) => {
    const separator = record.indexOf('\t');
    if (separator < 0) throw new Error('Git returned a malformed index entry.');
    const [mode, oid, stage] = record.slice(0, separator).split(' ');
    if (!/^[0-9a-f]{40,64}$/.test(oid ?? '') || !/^\d+$/.test(stage ?? '')) throw new Error('Git returned a malformed index entry.');
    return { path: record.slice(separator + 1), mode, oid, stage: Number(stage) };
  });
}

async function worktreeFile(root, path) {
  const parts = path.split('/');
  let current = root;
  for (let index = 0; index < parts.length; index += 1) {
    current = join(current, parts[index]);
    const stat = await lstat(current).catch((error) => {
      if (error.code === 'ENOENT') return null;
      throw error;
    });
    if (!stat) return null;
    if (stat.isSymbolicLink()) throw new Error(`Owned path crosses a symbolic link: ${path}.`);
    if (index < parts.length - 1 && !stat.isDirectory()) throw new Error(`Owned path parent is not a directory: ${path}.`);
    if (index === parts.length - 1 && !stat.isFile()) throw new Error(`Owned path is not a regular file: ${path}.`);
    if (index === parts.length - 1) {
      return { sha256: sha256(await readFile(current)), executable: process.platform === 'win32' ? null : Boolean(stat.mode & 0o111) };
    }
  }
  return null;
}

export async function captureOwnedHandoff(entry) {
  const paths = validateOwnedPaths(entry.ownedPaths);
  if (!paths.length) throw new Error('Verified handoff requires declared owned paths.');
  const requestedCheckout = resolve(entry.checkout);
  const checkoutStat = await lstat(requestedCheckout);
  if (!checkoutStat.isDirectory() || checkoutStat.isSymbolicLink()) throw new Error('Assignment checkout must be a real directory.');
  const checkout = await realpath(requestedCheckout);
  const currentRepo = await repository(checkout);
  const branch = git(checkout, ['symbolic-ref', '--quiet', 'HEAD'], true);
  const head = git(checkout, ['rev-parse', '--verify', 'HEAD'], true);
  const index = indexEntries(checkout);
  const files = [];
  for (const path of paths) {
    const staged = [];
    for (const record of index.filter((item) => item.path === path)) {
      const bytes = gitBuffer(checkout, ['cat-file', 'blob', record.oid]);
      staged.push({ mode: record.mode, stage: record.stage, sha256: sha256(bytes) });
    }
    files.push({ path, index: staged, worktree: await worktreeFile(checkout, path) });
  }
  return {
    schemaVersion: 1,
    status: 'verified',
    capturedAt: new Date().toISOString(),
    revision: head.status === 0 ? head.stdout.trim() : null,
    identity: {
      checkout,
      gitDirectory: currentRepo.primary,
      branch: branch.status === 0 ? branch.stdout.trim() : null,
      indexSource: 'git index entries for declared owned paths',
      worktreeSource: 'regular file bytes for declared owned paths',
    },
    files,
  };
}

export async function verifyOwnedHandoff(entry) {
  const expected = entry.handoffEvidence;
  if (!expected || expected.status !== 'verified') return { verified: false, status: 'unverified', reason: 'Legacy handoff has no verified owned-path snapshot.' };
  let paths;
  try { paths = validateOwnedPaths(entry.ownedPaths); }
  catch (error) { return { verified: false, status: 'invalid', reason: error.message }; }
  if (!paths.length || !Array.isArray(expected.files) || expected.files.map((file) => file.path).join('\0') !== paths.join('\0')) {
    return { verified: false, status: 'invalid', reason: 'Handoff paths do not match the assignment ownership list.' };
  }
  let actual;
  try {
    actual = await captureOwnedHandoff(entry);
  } catch (error) {
    return { verified: false, status: 'changed', reason: error.message };
  }
  const identityChanged = ['checkout', 'gitDirectory', 'branch'].some((field) => expected.identity?.[field] !== actual.identity[field]);
  const expectedFiles = new Map(expected.files.map((file) => [file.path, file]));
  const acceptedStagingPaths = [];
  const changedPaths = [];
  for (const file of actual.files) {
    const original = expectedFiles.get(file.path);
    if (!original || JSON.stringify(original.worktree) !== JSON.stringify(file.worktree)) {
      changedPaths.push(file.path);
      continue;
    }
    if (JSON.stringify(original.index) === JSON.stringify(file.index)) continue;
    if (indexMatchesWorktree(file.index, original.worktree)) acceptedStagingPaths.push(file.path);
    else changedPaths.push(file.path);
  }
  const verified = !identityChanged && changedPaths.length === 0;
  return {
    verified,
    status: verified ? 'verified' : 'changed',
    checkout: actual.identity.checkout,
    branch: actual.identity.branch,
    head: actual.revision,
    identityChanged,
    changedPaths,
    acceptedStagingPaths,
    reason: verified ? undefined : identityChanged ? 'Checkout or branch changed after handoff.' : 'Owned path content or staged index entries changed after handoff.',
  };
}
