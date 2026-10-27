import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { isAbsolute } from 'node:path';
import { checkout, fail, normalizedRepoPath, repoFile, samePath } from './agent-context-common.mjs';

export async function snapshot(root, files) {
  const current = await checkout(root);
  const seen = new Set();
  const declarations = [];
  for (const input of files) {
    const file = await repoFile(root, input, '--files');
    const path = normalizedRepoPath(root, file);
    const key = process.platform === 'win32' ? path.toLowerCase() : path;
    if (seen.has(key)) fail(`Duplicate snapshot path: ${input}`);
    seen.add(key);
    const bytes = await readFile(file);
    declarations.push({ path, sha256: createHash('sha256').update(bytes).digest('hex') });
  }
  process.stdout.write(
    `${JSON.stringify({ schemaVersion: 1, ...current, files: declarations }, null, 2)}\n`,
  );
}

export function validSnapshot(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const snapshotValue = value;
  if (
    snapshotValue.schemaVersion !== 1 ||
    typeof snapshotValue.root !== 'string' ||
    !isAbsolute(snapshotValue.root) ||
    !(
      snapshotValue.branch === null ||
      (typeof snapshotValue.branch === 'string' && snapshotValue.branch.length > 0)
    ) ||
    typeof snapshotValue.head !== 'string' ||
    !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(snapshotValue.head) ||
    !Array.isArray(snapshotValue.files) ||
    snapshotValue.files.length === 0
  )
    return false;
  return snapshotValue.files.every(
    (entry) =>
      entry &&
      typeof entry === 'object' &&
      !Array.isArray(entry) &&
      typeof entry.path === 'string' &&
      entry.path.length > 0 &&
      typeof entry.sha256 === 'string' &&
      /^[0-9a-f]{64}$/.test(entry.sha256),
  );
}

export async function verify(root, snapshotInput) {
  const snapshotFile = await repoFile(root, snapshotInput, '--snapshot');
  let snapshotValue;
  try {
    snapshotValue = JSON.parse((await readFile(snapshotFile, 'utf8')).replace(/^\uFEFF/, ''));
  } catch (error) {
    throw new Error(`Invalid snapshot JSON in ${snapshotInput}: ${error.message}`, { cause: error });
  }
  if (!validSnapshot(snapshotValue))
    throw new Error(`Malformed or unsupported snapshot in ${snapshotInput}.`);
  if (!samePath(snapshotValue.root, root))
    throw new Error(`Snapshot workspace mismatch: expected ${root}, found ${snapshotValue.root}.`);
  const current = await checkout(root);
  const changed = [];
  const missing = [];
  for (const entry of snapshotValue.files) {
    const file = await repoFile(root, entry.path, 'snapshot file', true);
    let bytes;
    try {
      bytes = await readFile(file);
    } catch (error) {
      if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT') {
        missing.push(entry.path);
        continue;
      }
      throw error;
    }
    if (createHash('sha256').update(bytes).digest('hex') !== entry.sha256) changed.push(entry.path);
  }
  process.stdout.write(
    `Workspace: ${current.root}\nFiles: ${snapshotValue.files.length - changed.length - missing.length}/${snapshotValue.files.length} unchanged\n`,
  );
  if (snapshotValue.head !== current.head)
    process.stdout.write(`HEAD drift: ${snapshotValue.head} -> ${current.head}\n`);
  if (snapshotValue.branch !== current.branch)
    process.stdout.write(
      `Branch drift: ${snapshotValue.branch ?? '(detached)'} -> ${current.branch ?? '(detached)'}\n`,
    );
  if (changed.length > 0 || missing.length > 0) {
    for (const path of changed) process.stderr.write(`Changed: ${path}\n`);
    for (const path of missing) process.stderr.write(`Missing: ${path}\n`);
    throw new Error('Snapshot is stale; declared files changed or are missing.');
  }
  process.stdout.write('Declared file content matches the snapshot.\n');
}
