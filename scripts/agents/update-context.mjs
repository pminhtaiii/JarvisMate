import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { lstat, readFile, realpath } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { atomicWrite, withLock } from './agent-store.mjs';

const usage = `Usage: node scripts/agents/update-context.mjs --updates <edits.json> [--apply] [--root <checkout>]
Preview is the default. --apply updates existing context/*.md files and runs context checks.
JSON: {"updates":[{"file":"context/example.md","sha256":"<current file hash>",
"edits":[{"oldText":"unique existing passage","newText":"replacement passage"}]}]}
Use {"updates":[]} after inspecting context when no content changes are needed.
Headings and existing newline style are preserved. See context/workflow.md#context-refresh.`;
const hash = (text) => createHash('sha256').update(text).digest('hex');

function headings(text) {
  let fence;
  return text.split('\n').filter((line) => {
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (fence) {
      if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length && !marker[2].trim()) fence = undefined;
      return false;
    }
    if (marker) { fence = marker[1]; return false; }
    return /^ {0,3}#{1,6} /.test(line) || /^ {0,3}(?:=+|-+)\s*$/.test(line);
  }).join('\n');
}

async function run(args) {
  if (args.length === 1 && ['--help', '-h'].includes(args[0])) return console.log(usage);
  const options = {};
  for (let index = 0; index < args.length; index++) {
    const option = args[index];
    if (!['--root', '--updates', '--apply'].includes(option) || Object.hasOwn(options, option)) throw new Error(usage);
    if (option === '--apply') options[option] = true;
    else {
      const value = args[++index];
      if (!value || value.startsWith('--')) throw new Error(usage);
      options[option] = value;
    }
  }
  if (!options['--updates']) throw new Error(usage);
  const root = await realpath(resolve(options['--root'] ?? resolve(dirname(fileURLToPath(import.meta.url)), '../..')));
  const context = resolve(root, 'context');
  if ((await lstat(context)).isSymbolicLink() || await realpath(context) !== context) throw new Error('context must be an unlinked directory.');
  const plan = JSON.parse((await readFile(resolve(options['--updates']), 'utf8')).replace(/^\uFEFF/, ''));
  if (!Array.isArray(plan.updates)) throw new Error('Plan requires an updates array.');
  const execute = async () => {
    const pending = [];
    const seen = new Set();
    for (const update of plan.updates) {
      if (!update || !/^context\/[A-Za-z0-9_-]+\.md$/.test(update.file) || seen.has(update.file)) throw new Error('Each update must name a unique existing context/*.md file.');
      if (update.file === 'context/active_task.md') throw new Error('Use active-task.mjs for the shared task view.');
      seen.add(update.file);
      const path = resolve(root, update.file);
      const stat = await lstat(path);
      if (!stat.isFile() || stat.isSymbolicLink() || await realpath(path) !== path) throw new Error('Context targets must be regular unlinked files.');
      const source = await readFile(path, 'utf8');
      if (hash(source) !== update.sha256?.toLowerCase()) throw new Error(`Stale source: ${update.file}; inspect again and regenerate edits.`);
      if (!Array.isArray(update.edits) || !update.edits.length) throw new Error('Each update requires nonempty edits.');
      const newline = source.includes('\r\n') ? '\r\n' : '\n';
      let content = source.replace(/\r\n/g, '\n');
      for (const edit of update.edits) {
        if (!edit || typeof edit.oldText !== 'string' || !edit.oldText || typeof edit.newText !== 'string') throw new Error('Edits require nonempty oldText and string newText.');
        const oldText = edit.oldText.replace(/\r\n/g, '\n');
        const index = content.indexOf(oldText);
        if (index < 0 || content.indexOf(oldText, index + 1) !== -1) throw new Error(`Passage must match exactly once: ${update.file}`);
        content = content.slice(0, index) + edit.newText.replace(/\r\n/g, '\n') + content.slice(index + oldText.length);
      }
      if (headings(content) !== headings(source.replace(/\r\n/g, '\n'))) throw new Error(`Preserve existing headings: ${update.file}`);
      content = content.replace(/\n/g, newline);
      if (content !== source) pending.push({ file: update.file, path, source, content });
    }
    if (!options['--apply']) return console.log(JSON.stringify({ applied: false, files: pending.map(({ file, source, content }) => ({ file, before: hash(source), after: hash(content), content })) }, null, 2));
    const written = [];
    try {
      for (const entry of pending) {
        if (await readFile(entry.path, 'utf8') !== entry.source) throw new Error(`Source changed: ${entry.file}`);
        await atomicWrite(entry.path, entry.content);
        written.push(entry);
      }
      const check = spawnSync(process.execPath, [fileURLToPath(new URL('../ci/check-context.mjs', import.meta.url)), '--root', root], { encoding: 'utf8', windowsHide: true, timeout: 30_000 });
      if (check.error || check.status !== 0) throw new Error(check.error?.message || check.stderr || check.stdout || 'Context check failed.');
      console.log(check.stdout.trim());
      console.log(JSON.stringify({ applied: true, files: pending.map(({ file }) => file) }));
    } catch (error) {
      const retained = [];
      for (const entry of written.reverse()) {
        if (await readFile(entry.path, 'utf8') !== entry.content) { retained.push(entry.file); continue; }
        await atomicWrite(entry.path, entry.source);
      }
      throw new Error(`${error.message}\nRestored this run's edits.${retained.length ? ` Concurrent edits retained; inspect: ${retained.join(', ')}` : ''}`, { cause: error });
    }
  };
  if (options['--apply']) await withLock(resolve(context, '.context-update.lock'), execute);
  else await execute();
}

run(process.argv.slice(2)).catch((error) => { console.error(error.message); process.exitCode = 1; });
