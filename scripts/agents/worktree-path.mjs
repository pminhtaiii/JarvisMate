import { lstat, realpath } from 'node:fs/promises';
import { parse, resolve, sep } from 'node:path';

async function directoryStat(path, label) {
  try { return await lstat(path); }
  catch (error) {
    if (error.code === 'ENOENT') throw new Error(`${label} does not exist.`, { cause: error });
    throw error;
  }
}

export async function realDirectoryWithoutLinks(path, label = 'Directory') {
  const requested = resolve(path);
  const { root } = parse(requested);
  let current = root;
  let stat = await directoryStat(current, label);
  if (stat.isSymbolicLink()) throw new Error(`${label} must be a real directory, not a symbolic link or junction.`);
  for (const component of requested.slice(root.length).split(sep).filter(Boolean)) {
    current = resolve(current, component);
    stat = await directoryStat(current, label);
    if (stat.isSymbolicLink()) throw new Error(`${label} must be a real directory, not a symbolic link or junction.`);
    if (!stat.isDirectory()) throw new Error(`${label} must be a real directory.`);
  }
  if (!stat.isDirectory()) throw new Error(`${label} must be a real directory.`);
  return realpath(requested);
}
