import { readJson, repository, samePath } from './agent-store.mjs';
import { randomUUID } from 'node:crypto';
import {
  lstat,
  mkdir,
  open,
  readFile,
  realpath,
  rename,
  unlink,
} from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const workspaceName = 'project';
const managedDirectoryName = '.agent-work';
const manifestName = 'session.json';
const operationLockName = 'agent-work.lock';
const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const idPattern = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const reservedWindowsNamePattern = /^(?:CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])$/i;

const usage = `Usage:
  node scripts/agents/agent-work.mjs start --session <id> [--date YYYY-MM-DD] [--root <checkout>]
  node scripts/agents/agent-work.mjs finish --session <date>/<id> [--root <checkout>]
  node scripts/agents/agent-work.mjs list [--root <checkout>]
  node scripts/agents/agent-work.mjs cleanup [--session <date>/<id>] [--root <checkout>]
  node scripts/agents/agent-work.mjs cleanup --apply [--session <date>/<id>] [--root <checkout>]

Cleanup previews by default. --apply removes only valid finished sessions.`;

function writeOutput(value) {
  process.stdout.write(`${value}\n`);
}

function writeError(value) {
  process.stderr.write(`${value}\n`);
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isInside(parentPath, childPath) {
  const childRelativePath = relative(parentPath, childPath);
  return (
    childRelativePath !== '' &&
    childRelativePath !== '..' &&
    !childRelativePath.startsWith(`..${process.platform === 'win32' ? '\\' : '/'}`) &&
    !isAbsolute(childRelativePath)
  );
}

function assertContained(parentPath, childPath, description) {
  if (!isInside(parentPath, childPath)) {
    throw new Error(`${description} escapes its managed parent`);
  }
}

function validateDate(value, label = 'date') {
  if (typeof value !== 'string' || !datePattern.test(value)) {
    throw new Error(`Invalid ${label}; expected YYYY-MM-DD`);
  }
  const year = Number(value.slice(0, 4));
  const parsed = new Date(`${value}T00:00:00.000Z`);
  if (year < 1 || Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new Error(`Invalid calendar ${label}: ${value}`);
  }
  return value;
}

function validateId(value) {
  if (
    typeof value !== 'string' ||
    !idPattern.test(value) ||
    reservedWindowsNamePattern.test(value)
  ) {
    throw new Error(`Invalid session ID: ${String(value)}`);
  }
  return value;
}

function parseSessionPath(value) {
  if (typeof value !== 'string') {
    throw new Error('A session path in <date>/<id> form is required');
  }
  const segments = value.split(/[\\/]/);
  if (segments.length !== 2) {
    throw new Error('Invalid session path; expected <date>/<id>');
  }
  return { date: validateDate(segments[0]), id: validateId(segments[1]) };
}

function defaultDate() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Ho_Chi_Minh',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const part = (name) => parts.find((entry) => entry.type === name)?.value;
  return validateDate(`${part('year')}-${part('month')}-${part('day')}`);
}

function parseArguments(argv) {
  const command = argv[0];
  if (!command || command === '--help' || command === 'help') {
    return { help: true };
  }
  if (!['start', 'finish', 'list', 'cleanup'].includes(command)) {
    throw new Error(`Unknown command: ${command}\n${usage}`);
  }

  const options = { command, apply: false };
  for (let index = 1; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--apply' && command === 'cleanup') {
      if (options.apply) throw new Error('Duplicate option: --apply');
      options.apply = true;
      continue;
    }
    if (!['--session', '--date', '--root'].includes(argument)) {
      throw new Error(`Unknown option or positional argument: ${argument}`);
    }
    if (
      (argument === '--session' && !['start', 'finish', 'cleanup'].includes(command)) ||
      (argument === '--date' && command !== 'start') ||
      (argument === '--root' && options.root !== undefined)
    ) {
      throw new Error(`Option ${argument} is not valid for ${command}`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith('--')) {
      throw new Error(`Option ${argument} requires a value`);
    }
    index += 1;
    if (argument === '--session') {
      if (options.session !== undefined) throw new Error('Duplicate option: --session');
      options.session = value;
    } else if (argument === '--date') {
      if (options.date !== undefined) throw new Error('Duplicate option: --date');
      options.date = value;
    } else {
      options.root = value;
    }
  }

  if (['start', 'finish'].includes(command) && options.session === undefined) {
    throw new Error(`${command} requires --session`);
  }
  if (command === 'start' && options.apply) {
    throw new Error('--apply is valid only for cleanup');
  }
  if (command === 'start') {
    options.session = validateId(options.session);
    options.date = validateDate(options.date ?? defaultDate());
  } else if (command === 'finish' || (command === 'cleanup' && options.session !== undefined)) {
    options.session = parseSessionPath(options.session);
  }
  return options;
}

async function statOrNull(path, options) {
  try {
    return options === undefined ? await lstat(path) : await lstat(path, options);
  } catch (error) {
    if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT') {
      return null;
    }
    throw error;
  }
}

function assertDirectoryStat(stat, path, description) {
  if (!stat || stat.isSymbolicLink() || !stat.isDirectory()) {
    throw new Error(`${description} must be a real directory: ${path}`);
  }
}

function assertRegularFileStat(stat, path, description) {
  if (!stat || stat.isSymbolicLink() || !stat.isFile()) {
    throw new Error(`${description} must be a regular file: ${path}`);
  }
}

async function resolveCheckout(rootOption) {
  const requestedRoot = rootOption === undefined ? repositoryRoot : resolve(rootOption);
  const rootStat = await statOrNull(requestedRoot);
  assertDirectoryStat(rootStat, requestedRoot, 'Checkout root');
  const checkout = await realpath(requestedRoot);
  const result = spawnSync('git', ['rev-parse', '--show-toplevel'], {
    cwd: checkout,
    encoding: 'utf8',
    windowsHide: true,
  });
  if (result.error) throw new Error(`Could not verify Git checkout: ${result.error.message}`);
  if (result.status !== 0) throw new Error(`Checkout root is not a Git checkout: ${checkout}`);
  const gitRoot = await realpath(result.stdout.trim());
  const sameRoot =
    process.platform === 'win32'
      ? resolve(gitRoot).toLowerCase() === resolve(checkout).toLowerCase()
      : resolve(gitRoot) === resolve(checkout);
  if (!sameRoot) throw new Error(`Checkout root must be the Git root: ${checkout}`);
  return checkout;
}

function managedRootPath(checkout) {
  const path = join(checkout, managedDirectoryName);
  assertContained(checkout, path, 'Managed work root');
  return path;
}

async function existingManagedRoot(checkout) {
  const path = managedRootPath(checkout);
  const stat = await statOrNull(path);
  if (!stat) return null;
  assertDirectoryStat(stat, path, 'Managed work root');
  const realPath = await realpath(path);
  if (resolve(realPath) !== resolve(path)) {
    throw new Error('Managed work root resolves outside its exact workspace path');
  }
  return path;
}

async function ensureDirectory(parent, name, description) {
  const path = join(parent, name);
  assertContained(parent, path, description);
  let stat = await statOrNull(path);
  if (!stat) {
    await mkdir(path);
    stat = await statOrNull(path);
  }
  assertDirectoryStat(stat, path, description);
  return path;
}

function manifestPath(sessionDirectory) {
  const path = join(sessionDirectory, manifestName);
  assertContained(sessionDirectory, path, 'Session marker');
  return path;
}

function isIsoTimestamp(value) {
  if (typeof value !== 'string') return false;
  const parsed = new Date(value);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString() === value;
}

function validateManifest(value, date, id) {
  const allowedKeys = new Set([
    'schemaVersion',
    'workspace',
    'date',
    'id',
    'status',
    'startedAt',
    'finishedAt',
  ]);
  if (!isObject(value) || Object.keys(value).some((key) => !allowedKeys.has(key))) {
    throw new Error('invalid session marker');
  }
  if (
    value.schemaVersion !== 1 ||
    value.workspace !== workspaceName ||
    value.date !== date ||
    value.id !== id ||
    !['active', 'finished'].includes(value.status) ||
    !isIsoTimestamp(value.startedAt)
  ) {
    throw new Error('invalid session marker');
  }
  if (value.status === 'finished') {
    if (!isIsoTimestamp(value.finishedAt)) throw new Error('invalid session marker');
  } else if ('finishedAt' in value) {
    throw new Error('invalid session marker');
  }
  return value;
}

async function readManifest(sessionDirectory, date, id) {
  const path = manifestPath(sessionDirectory);
  assertRegularFileStat(await statOrNull(path), path, 'Session marker');
  let value;
  try {
    value = JSON.parse(await readFile(path, 'utf8'));
  } catch {
    throw new Error('invalid session marker');
  }
  return validateManifest(value, date, id);
}

async function writeManifest(sessionDirectory, value) {
  const path = manifestPath(sessionDirectory);
  const currentStat = await statOrNull(path);
  if (currentStat) assertRegularFileStat(currentStat, path, 'Session marker');
  const temporaryPath = join(sessionDirectory, `.session.json.${randomUUID()}.tmp`);
  assertContained(sessionDirectory, temporaryPath, 'Temporary session marker');
  const contents = `${JSON.stringify(value, null, 2)}\n`;
  const handle = await open(temporaryPath, 'wx', 0o600);
  try {
    await handle.writeFile(contents, 'utf8');
    await handle.sync();
  } finally {
    await handle.close();
  }
  const latestStat = await statOrNull(path);
  if (latestStat) assertRegularFileStat(latestStat, path, 'Session marker');
  await rename(temporaryPath, path);
}

async function removeFailedLockIfOwned(lockPath, ownedIdentity) {
  const scratchPath = dirname(lockPath);
  const scratchStat = await statOrNull(scratchPath);
  if (!scratchStat || scratchStat.isSymbolicLink() || !scratchStat.isDirectory()) return false;
  if (resolve(await realpath(scratchPath)) !== resolve(scratchPath)) return false;

  const currentStat = await statOrNull(lockPath, { bigint: true });
  if (
    !currentStat ||
    currentStat.isSymbolicLink() ||
    !currentStat.isFile() ||
    currentStat.dev !== ownedIdentity.dev ||
    currentStat.ino !== ownedIdentity.ino
  ) {
    return false;
  }
  await unlink(lockPath);
  return true;
}

async function acquireLock(checkout, openFile) {
  const scratchPath = join(checkout, '.scratch');
  assertContained(checkout, scratchPath, 'Operation lock directory');
  let scratchStat = await statOrNull(scratchPath);
  if (!scratchStat) {
    await mkdir(scratchPath);
    scratchStat = await statOrNull(scratchPath);
  }
  assertDirectoryStat(scratchStat, scratchPath, 'Operation lock directory');

  const lockPath = join(scratchPath, operationLockName);
  assertContained(scratchPath, lockPath, 'Operation lock');
  const payload = `${JSON.stringify({ nonce: randomUUID(), startedAt: new Date().toISOString() })}\n`;
  let handle;
  let ownedIdentity;
  try {
    handle = await openFile(lockPath, 'wx', 0o600);
    ownedIdentity = await handle.stat({ bigint: true });
    await handle.writeFile(payload, 'utf8');
    await handle.sync();
  } catch (error) {
    let removalError;
    if (handle) {
      try {
        await handle.close();
      } catch {
        // Still verify the path identity before attempting removal.
      }
      if (ownedIdentity) {
        try {
          await removeFailedLockIfOwned(lockPath, ownedIdentity);
        } catch (failure) {
          removalError = failure;
        }
      }
    }
    if (error && typeof error === 'object' && 'code' in error && error.code === 'EEXIST') {
      throw new Error(
        'Operation lock is already held; stale locks are never reclaimed automatically',
        { cause: error },
      );
    }
    if (removalError) {
      const message =
        removalError && typeof removalError === 'object' && 'message' in removalError
          ? removalError.message
          : String(removalError);
      throw new Error(`Could not safely remove the failed operation lock: ${message}`, {
        cause: error,
      });
    }
    if (handle && !ownedIdentity) {
      throw new Error('Could not verify the new operation lock identity; leaving it in place', {
        cause: error,
      });
    }
    throw error;
  }
  await handle.close();

  return async function releaseLock() {
    const stat = await statOrNull(lockPath);
    if (!stat || stat.isSymbolicLink() || !stat.isFile()) return;
    const currentPayload = await readFile(lockPath, 'utf8');
    if (currentPayload !== payload) return;
    const finalStat = await statOrNull(lockPath);
    if (!finalStat || finalStat.isSymbolicLink() || !finalStat.isFile()) return;
    if ((await readFile(lockPath, 'utf8')) === payload) await unlink(lockPath);
  };
}

export async function withOperationLock(checkout, operation, openFile = open) {
  const release = await acquireLock(checkout, openFile);
  try {
    return await operation();
  } finally {
    await release();
  }
}

function newManifest(date, id) {
  return {
    schemaVersion: 1,
    workspace: workspaceName,
    date,
    id,
    status: 'active',
    startedAt: new Date().toISOString(),
  };
}

async function startSession(checkout, date, id) {
  await withOperationLock(checkout, async () => {
    const managedRoot = await ensureDirectory(checkout, managedDirectoryName, 'Managed work root');
    const dateDirectory = await ensureDirectory(managedRoot, date, 'Session date directory');
    const sessionDirectory = join(dateDirectory, id);
    assertContained(managedRoot, sessionDirectory, 'Session directory');
    let sessionStat = await statOrNull(sessionDirectory);
    let createdSession = false;
    if (!sessionStat) {
      await mkdir(sessionDirectory);
      sessionStat = await statOrNull(sessionDirectory);
      createdSession = true;
    }
    assertDirectoryStat(sessionStat, sessionDirectory, 'Session directory');

    const markerStat = await statOrNull(manifestPath(sessionDirectory));
    if (!markerStat) {
      if (!createdSession) {
        throw new Error('Existing session directory has no managed marker; retaining it');
      }
      await writeManifest(sessionDirectory, newManifest(date, id));
      writeOutput(`Started ${date}/${id}`);
      return;
    }
    assertRegularFileStat(markerStat, manifestPath(sessionDirectory), 'Session marker');
    const current = await readManifest(sessionDirectory, date, id);
    if (current.status === 'active') {
      writeOutput(`Session ${date}/${id} is already active`);
      return;
    }
    const reactivated = { ...current, status: 'active', startedAt: new Date().toISOString() };
    delete reactivated.finishedAt;
    await writeManifest(sessionDirectory, reactivated);
    writeOutput(`Reactivated ${date}/${id}`);
  });
}

async function finishSession(checkout, date, id) {
  await withOperationLock(checkout, async () => {
    const managedRoot = await existingManagedRoot(checkout);
    if (!managedRoot) throw new Error('Managed work root does not exist');
    const dateDirectory = join(managedRoot, date);
    assertDirectoryStat(await statOrNull(dateDirectory), dateDirectory, 'Session date directory');
    const sessionDirectory = join(dateDirectory, id);
    assertContained(managedRoot, sessionDirectory, 'Session directory');
    assertDirectoryStat(await statOrNull(sessionDirectory), sessionDirectory, 'Session directory');
    const current = await readManifest(sessionDirectory, date, id);
    if (current.status === 'finished') {
      writeOutput(`Session ${date}/${id} is already finished`);
      return;
    }
    const repo = await repository(checkout);
    const assignments = await readJson(join(repo.primary, '.agent-work/state/active-tasks.json')).catch((error) => {
      if (error.code !== 'ENOENT') throw error;
      return [];
    });
    if (!Array.isArray(assignments) || assignments.some((entry) => !entry || !['active', 'blocked', 'completed', 'handed-off', 'reassigned'].includes(entry.status))) throw new Error('Invalid shared task state; retain the session.');
    const session = `${date}/${id}`;
    const blockers = [];
    for (const entry of assignments) {
      if (['completed', 'handed-off', 'reassigned'].includes(entry.status)) continue;
      if (entry.session === session) { blockers.push(entry); continue; }
      let hasKnownSession = false;
      try {
        const parsed = parseSessionPath(entry.session);
        hasKnownSession = entry.session === `${parsed.date}/${parsed.id}`;
      } catch {
        // Unknown or malformed legacy session identities block conservatively by checkout.
      }
      if (hasKnownSession) continue;
      if (!entry.checkout || await samePath(entry.checkout, checkout)) blockers.push(entry);
    }
    if (blockers.length) {
      const details = blockers.map((entry) => `${entry.owner ?? 'unknown'}/${entry.task ?? 'unknown'} [${entry.status}; session=${entry.session ?? 'unknown'}; checkout=${entry.checkout ?? 'unknown'}]`);
      throw new Error(`Cannot finish session ${session}; active assignment blockers: ${details.join(', ')}.`);
    }
    await writeManifest(sessionDirectory, {
      ...current,
      status: 'finished',
      finishedAt: new Date().toISOString(),
    });
    writeOutput(`Finished ${date}/${id}`);
  });
}


export {
  usage,
  datePattern,
  idPattern,
  reservedWindowsNamePattern,
  writeOutput,
  writeError,
  parseArguments,
  resolveCheckout,
  managedRootPath,
  existingManagedRoot,
  statOrNull,
  assertDirectoryStat,
  assertContained,
  validateDate,
  readManifest,
  startSession,
  finishSession,
};
