import { createHash } from 'node:crypto';
import { lstat, mkdir, readFile, realpath } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { isDeepStrictEqual } from 'node:util';
import { atomicWrite, readJson } from './agent-store.mjs';
import { validateSessionRef } from './owned-handoff.mjs';

const startMarker = '<!-- active-task:start -->';
const endMarker = '<!-- active-task:end -->';
const sessionStartMarker = '<!-- active-task-session:start -->';
const sessionEndMarker = '<!-- active-task-session:end -->';

export function parseLegacyView(source, validateEntries) {
  const starts = source.split(startMarker).length - 1;
  const ends = source.split(endMarker).length - 1;
  const block = source.match(/(<!-- active-task:start -->\r?\n```json\r?\n)([\s\S]*?)(\r?\n```\r?\n<!-- active-task:end -->)/);
  if (starts === 0 && ends === 0) return { hasMarkers: false, entries: [] };
  if (starts !== 1 || ends !== 1 || !block) throw new Error('Active-task markers are damaged; file left unchanged.');
  return { hasMarkers: true, entries: validateEntries(JSON.parse(block[2])) };
}

export async function readLegacyViews(repo) {
  const views = [];
  for (const worktree of repo.worktrees) {
    const context = resolve(worktree.worktree, 'context');
    const directory = await lstat(context).catch((error) => { if (error.code !== 'ENOENT') throw error; });
    if (!directory) continue;
    if (!directory.isDirectory() || directory.isSymbolicLink() || await realpath(context) !== context) throw new Error('Legacy context must be a regular directory, not a link.');
    const path = resolve(context, 'active_task.md');
    const stat = await lstat(path).catch((error) => { if (error.code !== 'ENOENT') throw error; });
    if (!stat) continue;
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('Legacy handoff must be a regular file.');
    views.push({ checkout: worktree.worktree, source: await readFile(path, 'utf8') });
  }
  return views;
}

export async function backupLegacyViews(store, views) {
  const legacy = views.filter(({ source }) => source.includes(startMarker) || source.includes(endMarker));
  if (!legacy.length) return 0;
  const directory = resolve(store, 'legacy-active-task');
  await mkdir(directory).catch((error) => { if (error.code !== 'EEXIST') throw error; });
  const stat = await lstat(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink() || await realpath(directory) !== directory) throw new Error('Legacy backup directory must be a regular directory, not a link.');

  for (const { checkout, source } of legacy) {
    const sourceHash = createHash('sha256').update(source).digest('hex');
    const identity = process.platform === 'win32' ? checkout.toLowerCase() : checkout;
    const pathHash = createHash('sha256').update(identity).digest('hex').slice(0, 16);
    const path = resolve(directory, `${pathHash}-${sourceHash}.json`);
    const backup = JSON.stringify({ schemaVersion: 1, checkout, source: 'context/active_task.md', sourceHash, content: source }, null, 2) + '\n';
    const existing = await lstat(path).catch((error) => { if (error.code !== 'ENOENT') throw error; });
    if (existing) {
      if (!existing.isFile() || existing.isSymbolicLink() || await readFile(path, 'utf8') !== backup) throw new Error('Legacy backup already exists with different content; preserve it and choose another migration path.');
      continue;
    }
    try { await atomicWrite(path, backup, { exclusive: true }); }
    catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const existing = await lstat(path);
      if (!existing.isFile() || existing.isSymbolicLink() || await readFile(path, 'utf8') !== backup) throw new Error('Legacy backup already exists with different content; preserve it and choose another migration path.', { cause: error });
    }
  }
  return legacy.length;
}

export function importLegacyViews(views, parse, validateEntries) {
  const collected = collectLegacyViews(views, parse, validateEntries);
  if (collected.conflicts.length) {
    const conflict = collected.conflicts[0];
    throw new Error(`Conflicting legacy assignment ${conflict.owner}/${conflict.task} in ${conflict.checkouts.join(' and ')}; reconcile the views before migration.`);
  }
  return collected.entries;
}

function collectLegacyViews(views, parse, validateEntries) {
  const imported = [];
  const originals = new Map();
  const conflicts = new Map();
  for (const view of views) {
    const parsed = parse(view.source);
    if (!parsed.hasMarkers) continue;
    for (const original of validateEntries(parsed.entries)) {
      const key = JSON.stringify([original.owner, original.task]);
      const previous = originals.get(key);
      if (previous) {
        const left = { ...previous.original };
        const right = { ...original };
        const checkoutMismatch = left.checkout && right.checkout && left.checkout !== right.checkout;
        delete left.checkout;
        delete right.checkout;
        if (checkoutMismatch || !isDeepStrictEqual(left, right)) {
          conflicts.set(key, {
            owner: original.owner,
            task: original.task,
            checkouts: [...new Set([...(conflicts.get(key)?.checkouts ?? [previous.checkout]), view.checkout])],
          });
          continue;
        }
        if (!previous.original.checkout && original.checkout) previous.entry.checkout = original.checkout;
        continue;
      }
      const entry = { ...original, checkout: original.checkout ?? view.checkout };
      imported.push(entry);
      originals.set(key, { original, entry, checkout: view.checkout });
    }
  }
  return {
    entries: imported.filter((entry) => !conflicts.has(JSON.stringify([entry.owner, entry.task]))),
    conflicts: [...conflicts.values()],
  };
}

export async function migrateLegacyViews(repo, store, statePath, parse, validateEntries) {
  const views = await readLegacyViews(repo);
  const backups = await backupLegacyViews(store, views);
  let current;
  let stateExists = true;
  try {
    current = validateEntries(await readJson(statePath));
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    stateExists = false;
    current = [];
  }
  const collected = collectLegacyViews(views, parse, validateEntries);
  const legacy = collected.entries;
  const entries = [...current];
  const currentByKey = new Map(entries.map((entry, index) => [JSON.stringify([entry.owner, entry.task]), index]));
  const conflicts = [...collected.conflicts];
  let imported = 0;
  for (const entry of legacy) {
    const key = JSON.stringify([entry.owner, entry.task]);
    const index = currentByKey.get(key);
    if (index === undefined) {
      currentByKey.set(key, entries.length);
      entries.push(entry);
      imported++;
      continue;
    }
    const existing = { ...entries[index] };
    const incoming = { ...entry };
    delete existing.checkout;
    delete incoming.checkout;
    if (!isDeepStrictEqual(existing, incoming)) {
      conflicts.push({ owner: entry.owner, task: entry.task, checkouts: ['shared state', entry.checkout ?? 'legacy view'] });
    }
  }
  if (!stateExists && (imported || !conflicts.length) || stateExists && imported) await atomicWrite(statePath, JSON.stringify(entries, null, 2) + '\n');
  if (!imported && conflicts.length) return { migrated: false, imported: 0, conflicts, backups };
  if (!imported) return { migrated: false, imported: 0, reason: 'Shared state already contains all unambiguous legacy assignments; conflicting rows remain in backups for review.', conflicts, backups };
  return { migrated: true, imported, retained: entries.length, conflicts, backups };
}

function sessionFromOutput(output) {
  const match = typeof output === 'string' && output.match(/^\.agent-work\/(\d{4}-\d{2}-\d{2})\/([A-Za-z0-9][A-Za-z0-9_-]{0,63})\/progress\.md$/);
  if (!match) throw new Error('render --output must be .agent-work/<date>/<session>/progress.md.');
  return validateSessionRef(`${match[1]}/${match[2]}`);
}

async function ensureDirectory(path) {
  await mkdir(path).catch((error) => { if (error.code !== 'EEXIST') throw error; });
  const stat = await lstat(path);
  if (!stat.isDirectory() || stat.isSymbolicLink() || await realpath(path) !== path) throw new Error('Session progress directories must be regular directories, not links.');
}

function displayText(value) {
  const readable = [...String(value ?? '')].map((character) => {
    const code = character.charCodeAt(0);
    return code < 0x20 || code === 0x7f ? ' ' : character;
  }).join('');
  return readable.replace(/\s+/g, ' ').trim().replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function progressContent(entries, session, statePath) {
  const selected = entries.filter((entry) => entry.session === session);
  const status = { active: 'running', blocked: 'blocked', 'handed-off': 'handed-off', completed: 'completed', reassigned: 'reassigned' };
  const ledger = pathToFileURL(statePath).href;
  const lines = ['# Session progress', '', sessionStartMarker, `<!-- session: ${session} -->`, 'Generated from the canonical task ledger; update assignments with active-task.mjs.', '', `Canonical ledger: [shared active-task registry](${ledger})`, ''];
  if (!selected.length) lines.push('Status: ready', '', 'No assignment is registered for this session.', '', 'Next action: register the assignment with active-task.mjs start.');
  for (const entry of selected) {
    lines.push(`## ${entry.owner}/${entry.task}`, '', `Status: ${status[entry.status] ?? entry.status}`, '', `Goal: ${displayText(entry.summary)}`, '', `Next action: ${displayText(entry.next)}`);
    if (entry.verification) lines.push('', `Evidence: ${displayText(entry.verification)}`);
    if (entry.result) lines.push('', `Result: ${displayText(entry.result)}`);
    if (entry.handoffEvidence?.status) lines.push('', `Handoff evidence: ${displayText(entry.handoffEvidence.status)}${entry.handoffEvidence.revision ? ` at ${displayText(entry.handoffEvidence.revision)}` : ''}`);
    lines.push('', `Record: node scripts/agents/active-task.mjs list --owner ${entry.owner} --task ${entry.task}`, '');
  }
  lines.push(sessionEndMarker, '');
  return lines.join('\n');
}

export async function writeSessionProgress(root, output, entries, statePath) {
  const session = sessionFromOutput(output);
  const managedRoot = resolve(root, '.agent-work');
  await ensureDirectory(managedRoot);
  let directory = managedRoot;
  for (const component of session.split('/')) {
    directory = resolve(directory, component);
    await ensureDirectory(directory);
  }
  const path = resolve(directory, 'progress.md');
  const existing = await lstat(path).catch((error) => { if (error.code !== 'ENOENT') throw error; });
  if (existing) {
    if (!existing.isFile() || existing.isSymbolicLink()) throw new Error('Session progress output must be a regular file, not a link.');
    const source = await readFile(path, 'utf8');
    const starts = source.split(sessionStartMarker).length - 1;
    const ends = source.split(sessionEndMarker).length - 1;
    if (starts !== 1 || ends !== 1 || !source.includes(`<!-- session: ${session} -->`)) throw new Error('Session progress output is not this session\'s generated view; file left unchanged.');
  }
  await atomicWrite(path, progressContent(entries, session, statePath));
  return { output, session, assignments: entries.filter((entry) => entry.session === session).length };
}
