import { lstat, readdir, realpath, rm } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import {
  assertContained,
  assertDirectoryStat,
  datePattern,
  existingManagedRoot,
  idPattern,
  managedRootPath,
  reservedWindowsNamePattern,
  readManifest,
  statOrNull,
  validateDate,
  withOperationLock,
  writeOutput,
} from './agent-work-session.mjs';
async function firstUnsafeEntry(sessionDirectory) {
  const pending = [sessionDirectory];
  while (pending.length > 0) {
    const directory = pending.pop();
    let entries;
    try {
      entries = await readdir(directory);
    } catch {
      return 'cannot safely inspect session directory';
    }
    for (const entryName of entries) {
      if (entryName.toLowerCase() === '.git') return 'contains a Git checkout; remove it through Git worktree tooling';
      const entryPath = join(directory, entryName);
      let stat;
      try {
        stat = await lstat(entryPath);
      } catch {
        return 'cannot safely inspect session directory';
      }
      if (stat.isSymbolicLink()) return 'contains a symlink or junction';
      if (stat.isDirectory()) pending.push(entryPath);
      else if (!stat.isFile()) return 'contains an unsupported filesystem entry';
    }
  }
  return null;
}

function sessionRecord(label, extra = {}) {
  return { label, status: 'unknown', reason: 'unmanaged entry', ...extra };
}

async function inspectSession(managedRoot, date, id) {
  const label = `${date}/${id}`;
  const dateDirectory = join(managedRoot, date);
  const directory = join(dateDirectory, id);
  const directoryStat = await statOrNull(directory);
  if (!directoryStat || directoryStat.isSymbolicLink() || !directoryStat.isDirectory()) {
    return sessionRecord(label, {
      reason: 'session directory is missing or is not a real directory',
      date,
      id,
    });
  }
  const unsafeEntry = await firstUnsafeEntry(directory);
  if (unsafeEntry) return sessionRecord(label, { reason: unsafeEntry, date, id });
  try {
    const value = await readManifest(directory, date, id);
    return {
      label,
      date,
      id,
      directory,
      status: value.status,
      reason: value.status === 'finished' ? 'eligible for cleanup' : 'active session',
      eligible: value.status === 'finished',
    };
  } catch {
    return sessionRecord(label, { reason: 'invalid session marker', date, id });
  }
}

async function discoverSessions(checkout) {
  const managedRoot = await existingManagedRoot(checkout);
  if (!managedRoot) return { managedRoot: null, records: [] };
  const rootEntries = await readdir(managedRoot);
  const records = [];
  for (const name of rootEntries) {
    const path = join(managedRoot, name);
    const stat = await statOrNull(path);
    if (stat?.isSymbolicLink()) {
      records.push(sessionRecord(name, { reason: 'date entry is a symlink or junction' }));
      continue;
    }
    if (!stat?.isDirectory() || !datePattern.test(name)) {
      records.push(sessionRecord(name, { reason: 'unrecognized managed-root entry' }));
      continue;
    }
    try {
      validateDate(name);
    } catch {
      records.push(sessionRecord(name, { reason: 'invalid calendar date directory' }));
      continue;
    }
    for (const sessionName of await readdir(path)) {
      const sessionDirectory = join(path, sessionName);
      const sessionStat = await statOrNull(sessionDirectory);
      if (sessionStat?.isSymbolicLink()) {
        records.push(
          sessionRecord(`${name}/${sessionName}`, {
            reason: 'session directory is a symlink or junction',
            date: name,
            id: sessionName,
          }),
        );
        continue;
      }
      if (
        !sessionStat?.isDirectory() ||
        !idPattern.test(sessionName) ||
        reservedWindowsNamePattern.test(sessionName)
      ) {
        records.push(
          sessionRecord(`${name}/${sessionName}`, {
            reason: 'unrecognized session entry',
            date: name,
            id: sessionName,
          }),
        );
        continue;
      }
      records.push(await inspectSession(managedRoot, name, sessionName));
    }
  }
  return { managedRoot, records };
}

function formatRecords(checkout, records, mode) {
  writeOutput(`Managed work root: ${managedRootPath(checkout)}`);
  writeOutput(`Mode: ${mode}`);
  if (records.length === 0) writeOutput('No managed session directories found.');
  for (const record of records) {
    if (mode === 'list') {
      writeOutput(`- ${record.label} [${record.status}] ${record.reason}`);
    } else if (record.status === 'deleted') {
      writeOutput(`- ${record.label} [deleted] removed`);
    } else if (record.eligible) {
      writeOutput(`- ${record.label} [finished] eligible for cleanup`);
    } else {
      writeOutput(`- ${record.label} [${record.status}] retained: ${record.reason}`);
    }
  }
  if (mode !== 'list') {
    const eligible = records.filter((record) => record.eligible).length;
    const retained = records.length - eligible;
    const deleted = records.filter((record) => record.status === 'deleted').length;
    writeOutput(
      mode === 'apply'
        ? `Summary: ${deleted} deleted; ${retained} retained.`
        : `Summary: ${eligible} eligible; ${retained} retained.`,
    );
  }
}

async function listSessions(checkout) {
  const { records } = await discoverSessions(checkout);
  formatRecords(checkout, records, 'list');
}

async function deleteFinishedSession(checkout, managedRoot, record) {
  const currentRoot = await existingManagedRoot(checkout);
  if (!currentRoot || resolve(currentRoot) !== resolve(managedRoot)) {
    throw new Error('Managed work root changed before cleanup');
  }
  const dateDirectory = join(currentRoot, record.date);
  assertContained(currentRoot, dateDirectory, 'Session date directory');
  assertDirectoryStat(await statOrNull(dateDirectory), dateDirectory, 'Session date directory');
  const directory = join(dateDirectory, record.id);
  assertContained(currentRoot, directory, 'Session directory');
  assertDirectoryStat(await statOrNull(directory), directory, 'Session directory');
  const realManagedRoot = await realpath(currentRoot);
  const realSessionDirectory = await realpath(directory);
  assertContained(realManagedRoot, realSessionDirectory, 'Resolved session directory');
  if (
    resolve(realManagedRoot) !== resolve(currentRoot) ||
    resolve(realSessionDirectory) !== resolve(directory)
  ) {
    throw new Error('Resolved session path changed before cleanup');
  }
  const unsafeEntry = await firstUnsafeEntry(directory);
  if (unsafeEntry) throw new Error(`Session became unsafe before cleanup: ${unsafeEntry}`);

  // Re-read the marker under the operation lock immediately before deleting this bounded directory.
  const currentMarker = await readManifest(directory, record.date, record.id);
  if (currentMarker.status !== 'finished') {
    throw new Error('Session is no longer finished; retaining it');
  }
  await rm(directory, { recursive: true, force: false });
}

async function cleanupSessions(checkout, target, apply) {
  const run = async () => {
    const { managedRoot, records: discovered } = await discoverSessions(checkout);
    let records = discovered;
    if (target) {
      const label = `${target.date}/${target.id}`;
      records = records.filter((record) => record.label === label);
      if (records.length === 0) {
        records = [
          sessionRecord(label, {
            reason: 'session directory not found',
            date: target.date,
            id: target.id,
          }),
        ];
      }
    }
    if (apply && managedRoot) {
      for (const record of records) {
        if (!record.eligible) continue;
        await deleteFinishedSession(checkout, managedRoot, record);
        record.status = 'deleted';
        record.reason = 'removed';
      }
    }
    const mode = apply ? 'apply' : 'preview; pass --apply to remove finished sessions';
    formatRecords(checkout, records, mode);
  };
  if (apply) return withOperationLock(checkout, run);
  return run();
}


export { listSessions, cleanupSessions };
