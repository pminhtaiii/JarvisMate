import { randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { link, lstat, mkdir, open, readFile, realpath, rename, unlink } from 'node:fs/promises';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';

export function git(root, args, allowFailure = false) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true, timeout: 15_000 });
  if (result.error) throw result.error;
  if (result.status !== 0 && !allowFailure) throw new Error(result.stderr.trim() || `git ${args[0]} failed (${result.status})`);
  return result;
}

export function inside(parent, candidate) {
  const path = relative(parent, candidate);
  return path !== '' && path !== '..' && !path.startsWith(`..${sep}`) && !isAbsolute(path);
}

async function pathIdentity(path) {
  const absolute = resolve(path);
  try { return resolve(await realpath(absolute)); }
  catch (error) {
    if (!['ENOENT', 'ENOTDIR'].includes(error.code)) throw error;
    return absolute;
  }
}

export async function samePath(left, right) {
  const [leftPath, rightPath] = await Promise.all([pathIdentity(left), pathIdentity(right)]);
  return process.platform === 'win32'
    ? leftPath.toLowerCase() === rightPath.toLowerCase()
    : leftPath === rightPath;
}

export async function repository(root) {
  root = await realpath(resolve(root));
  const top = await realpath(git(root, ['rev-parse', '--show-toplevel']).stdout.trim());
  if (top !== root) throw new Error('Root must be the Git checkout root.');
  const worktrees = git(root, ['worktree', 'list', '--porcelain', '-z']).stdout.split('\0\0').filter(Boolean).map((record) => {
    const fields = {};
    for (const field of record.split('\0').filter(Boolean)) {
      const space = field.indexOf(' ');
      fields[space === -1 ? field : field.slice(0, space)] = space === -1 ? true : field.slice(space + 1);
    }
    return fields;
  });
  if (!worktrees[0]?.worktree || worktrees[0].bare) throw new Error('A primary non-bare checkout is required.');
  return { root, primary: await realpath(worktrees[0].worktree), worktrees };
}

export async function dataDirectory(repo, name) {
  let directory = repo.primary;
  for (const component of ['.agent-work', name]) {
    directory = resolve(directory, component);
    await mkdir(directory).catch((error) => { if (error.code !== 'EEXIST') throw error; });
    const stat = await lstat(directory);
    if (!stat.isDirectory() || stat.isSymbolicLink() || await realpath(directory) !== directory) throw new Error('Agent data directory must not be linked.');
  }
  return directory;
}

export async function atomicWrite(path, content, { exclusive = false } = {}) {
  const existing = await lstat(path).catch((error) => { if (error.code !== 'ENOENT') throw error; });
  if (existing && (!existing.isFile() || existing.isSymbolicLink())) throw new Error('Destination must be a regular file.');
  const temporary = resolve(dirname(path), `.agent-${randomUUID()}.tmp`);
  const handle = await open(temporary, 'wx', existing ? existing.mode & 0o777 : 0o600);
  try {
    try {
      await handle.writeFile(content, 'utf8');
      await handle.sync();
    } finally {
      await handle.close();
    }
    if (exclusive) await link(temporary, path);
    else await rename(temporary, path);
  } finally {
    await unlink(temporary).catch((error) => { if (error.code !== 'ENOENT') throw error; });
  }
}

export async function readJson(path) {
  const stat = await lstat(path);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('Agent data must be a regular file.');
  return JSON.parse(await readFile(path, 'utf8'));
}

export async function withLock(path, operation) {
  const handle = await open(path, 'wx').catch((error) => {
    if (error.code === 'EEXIST') throw new Error('Agent data file is busy; retry after the writer finishes. Do not reclaim its lock automatically.');
    throw error;
  });
  const identity = await handle.stat();
  try { return await operation(); }
  finally {
    await handle.close();
    const current = await lstat(path).catch((error) => { if (error.code !== 'ENOENT') throw error; });
    if (current?.ino === identity.ino && current?.dev === identity.dev) await unlink(path);
  }
}
