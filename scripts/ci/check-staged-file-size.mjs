import { execFileSync, spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { isAbsolute, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const LIMIT_BYTES = 20_000;
const LOCKFILES = new Set(['bun.lock', 'bun.lockb', 'npm-shrinkwrap.json', 'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock']);

function formatNumber(value) {
  return String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function git(root, args, options = {}) {
  return execFileSync('git', args, { cwd: root, windowsHide: true, timeout: 30_000, ...options });
}

function parseRawDiff(raw) {
  const fields = raw.toString('utf8').split('\0');
  const entries = [];
  for (let index = 0; index < fields.length && fields[index];) {
    const header = fields[index++];
    const [oldMode, newMode, , oid, status] = header.slice(1).trim().split(/\s+/);
    if (!header.startsWith(':') || !oldMode || !newMode || !oid || !status) throw new Error('Git returned an invalid raw diff record.');
    const oldPath = fields[index++];
    const path = status[0] === 'R' || status[0] === 'C' ? fields[index++] : oldPath;
    if (path === undefined) throw new Error('Git returned an incomplete raw diff record.');
    if (['A', 'C', 'M', 'R', 'T'].includes(status[0]) && (newMode === '100644' || newMode === '100755')) {
      entries.push({ mode: newMode, path, oid });
    }
  }
  return entries;
}

function isExcluded(path) {
  const parts = path.toLowerCase().split('/');
  const basename = parts.at(-1);
  return LOCKFILES.has(basename)
    || ['tests', 'specs'].includes(parts[0])
    || parts.includes('node_modules')
    || ['dist', 'coverage'].includes(parts[0])
    || /\.(?:generated|g)\.[^.]+$/.test(basename);
}

function stagedDiff(root) {
  return git(root, ['diff', '--cached', '--no-ext-diff', '--no-textconv', '--raw', '--no-abbrev', '-z', '--diff-filter=ACMRT', '--find-renames', '--find-copies']);
}

function commitId(root, revision) {
  const oid = git(root, ['rev-parse', '--verify', `${revision}^{commit}`], { encoding: 'utf8' }).trim();
  if (!/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i.test(oid)) throw new Error(`Git returned an invalid commit ID for ${revision}.`);
  return oid.toLowerCase();
}

function mergeParentBlobSignatures(root) {
  const mergeHeadPath = git(root, ['rev-parse', '--git-path', 'MERGE_HEAD'], { encoding: 'utf8' }).replace(/\r?\n$/, '');
  if (!mergeHeadPath) throw new Error('Git returned an empty MERGE_HEAD path.');

  let mergeHead;
  try {
    mergeHead = readFileSync(isAbsolute(mergeHeadPath) ? mergeHeadPath : resolve(root, mergeHeadPath), 'utf8');
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw new Error(`Could not read Git MERGE_HEAD: ${error.message}`, { cause: error });
  }

  const mergeRefs = mergeHead.split(/\r?\n/);
  if (mergeRefs.at(-1) === '') mergeRefs.pop();
  if (!mergeRefs.length || mergeRefs.some((ref) => !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i.test(ref))) {
    throw new Error('Invalid Git MERGE_HEAD: expected commit object IDs.');
  }

  const parents = [commitId(root, 'HEAD')];
  for (const ref of mergeRefs) {
    const resolved = commitId(root, ref);
    if (resolved !== ref.toLowerCase()) throw new Error(`Invalid Git MERGE_HEAD commit: ${ref}`);
    parents.push(resolved);
  }

  const signatures = new Set();
  for (const parent of parents) {
    const tree = git(root, ['ls-tree', '-rz', '--full-tree', parent], { maxBuffer: 64 * 1024 * 1024 }).toString('utf8');
    for (const entry of tree.split('\0')) {
      if (!entry) continue;
      const tab = entry.indexOf('\t');
      const [mode, type, oid] = entry.slice(0, tab).split(' ');
      if (tab < 0 || !mode || !type || !oid) throw new Error(`Git returned an invalid tree entry for ${parent}.`);
      if (type === 'blob' && (mode === '100644' || mode === '100755')) signatures.add(`${mode}:${oid}`);
    }
  }
  return signatures;
}

function objectSizes(root, entries) {
  if (!entries.length) return [];
  const input = Buffer.from(`${entries.map(({ oid }) => oid).join('\n')}\n`);
  const output = git(root, ['cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)'], { input, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
  const lines = output.trimEnd().split(/\r?\n/);
  if (lines.length !== entries.length) throw new Error('Git returned an incomplete staged-object size list.');
  return lines.map((line, index) => {
    const [oid, type, size] = line.split(' ');
    if (oid !== entries[index].oid || type !== 'blob' || !/^\d+$/.test(size ?? '')) throw new Error(`Could not read staged blob ${entries[index].oid}.`);
    return BigInt(size);
  });
}

function hasNulByte(root, oid) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn('git', ['cat-file', 'blob', oid], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
    let binary = false;
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      if (!binary && chunk.includes(0)) {
        binary = true;
        child.kill();
      }
    });
    child.stderr.on('data', (chunk) => { if (stderr.length < 2_000) stderr += chunk.toString('utf8'); });
    child.once('error', rejectPromise);
    child.once('close', (code, signal) => {
      if (binary) return resolvePromise(true);
      if (code !== 0) return rejectPromise(new Error(`git cat-file failed for ${oid}${signal ? ` (${signal})` : ''}: ${stderr.trim()}`));
      return resolvePromise(false);
    });
  });
}

function parseArgs(args) {
  const values = {};
  for (let index = 0; index < args.length; index += 2) {
    const name = args[index];
    const value = args[index + 1];
    if (name !== '--root' || !value || values[name]) {
      throw new Error('Usage: node scripts/ci/check-staged-file-size.mjs [--root <checkout>]');
    }
    values[name] = value;
  }
  return values;
}

export async function checkStagedFileSize(root) {
  const staged = parseRawDiff(stagedDiff(root)).filter(({ path }) => !isExcluded(path));
  const mergeParents = staged.length ? mergeParentBlobSignatures(root) : null;
  // Renames and resolutions can change paths; an exact parent mode and blob is the approved identity.
  const entries = mergeParents
    ? staged.filter(({ mode, oid }) => !mergeParents.has(`${mode}:${oid}`))
    : staged;
  const sizes = objectSizes(root, entries);
  const oversized = [];
  for (let index = 0; index < entries.length; index += 1) {
    if (sizes[index] <= BigInt(LIMIT_BYTES)) continue;
    // Exact upstream Spec Kit 1.2.3 blob; modified copies retain the size limit.
    if (entries[index].path === '.specify/scripts/powershell/common.ps1' && entries[index].oid === 'c0aa9154b5f5ad9211bbd6d2a3d5253c9759931d') continue;
    if (await hasNulByte(root, entries[index].oid)) continue;
    oversized.push({ path: entries[index].path, size: sizes[index].toString() });
  }
  return { entries: entries.length, oversized };
}

async function main() {
  const values = parseArgs(process.argv.slice(2));
  const root = resolve(values['--root'] ?? git(process.cwd(), ['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim());
  const result = await checkStagedFileSize(root);
  if (result.oversized.length) {
    console.error(`Staged implementation files exceed ${formatNumber(LIMIT_BYTES)} bytes (about 5,000 tokens at bytes/4; top-level tests/ and specs/ are excluded):`);
    for (const file of result.oversized) console.error(`- ${JSON.stringify(file.path)} (${formatNumber(file.size)} bytes)`);
    console.error('Split each file along a cohesive responsibility into smaller modules, keep a small entry point, stage the split, then rerun `pnpm run check:staged-size`.');
    process.exitCode = 1;
    return;
  }
  console.log(`Staged-file size check passed: ${result.entries} eligible implementation file(s); limit ${formatNumber(LIMIT_BYTES)} bytes.`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
