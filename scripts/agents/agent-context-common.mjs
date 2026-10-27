import { spawnSync } from 'node:child_process';
import { readFile, realpath, stat } from 'node:fs/promises';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const moduleRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
export const usage = `Usage:
  node scripts/agents/agent-context.mjs assignment --uc <UC-ID> [--root <checkout>] (legacy; disabled for LifeMate)
  node scripts/agents/agent-context.mjs handoff --tasks <tasks.md> [--root <checkout>]
  node scripts/agents/agent-context.mjs resume [--tasks <tasks.md>] [--authorization <path> ...] [--root <checkout>]
  node scripts/agents/agent-context.mjs task --tasks <tasks.md> --task T017 [--plan <plan.md>] [--root <checkout>]
  node scripts/agents/agent-context.mjs snapshot --files <repo-relative-file...> [--root <checkout>]
  node scripts/agents/agent-context.mjs verify --snapshot <snapshot.json> [--root <checkout>]
  node scripts/agents/agent-context.mjs --help`;

export function fail(message) {
  throw new Error(`${message}\n\n${usage}`);
}

export function samePath(left, right) {
  const normalizedLeft = resolve(left);
  const normalizedRight = resolve(right);
  return process.platform === 'win32'
    ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight;
}

export function isInside(root, candidate) {
  const pathFromRoot = relative(root, candidate);
  return (
    pathFromRoot !== '' &&
    pathFromRoot !== '..' &&
    !pathFromRoot.startsWith(`..${sep}`) &&
    !isAbsolute(pathFromRoot)
  );
}

export async function resolveRoot(rootOption) {
  const candidate = rootOption ? resolve(process.cwd(), rootOption) : moduleRoot;
  const canonicalRoot = await realpath(candidate);
  if (!(await stat(canonicalRoot)).isDirectory())
    fail(`Checkout root is not a directory: ${candidate}`);
  return canonicalRoot;
}

export async function repoFile(root, input, label, allowMissing = false) {
  if (input.length === 0 || input.includes('\0') || isAbsolute(input)) {
    fail(`${label} must be a repo-relative path: ${input}`);
  }
  const candidate = resolve(root, input);
  if (!isInside(root, candidate)) fail(`${label} escapes the checkout root: ${input}`);
  try {
    const canonicalFile = await realpath(candidate);
    if (!isInside(root, canonicalFile))
      fail(`${label} resolves outside the checkout root: ${input}`);
    return canonicalFile;
  } catch (error) {
    if (
      allowMissing &&
      error &&
      typeof error === 'object' &&
      'code' in error &&
      error.code === 'ENOENT'
    ) {
      return candidate;
    }
    throw error;
  }
}

export function git(root, args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true });
  if (result.error) throw new Error(`Could not run git ${args.join(' ')}: ${result.error.message}`);
  if (result.status !== 0) {
    throw new Error((result.stderr || `git ${args.join(' ')} failed`).trim());
  }
  return result.stdout.trim();
}

export async function checkout(root) {
  const gitRoot = await realpath(git(root, ['rev-parse', '--show-toplevel']));
  if (!samePath(gitRoot, root)) fail(`--root must name a Git checkout root: ${root}`);
  const branch = git(root, ['branch', '--show-current']) || null;
  const head = git(root, ['rev-parse', 'HEAD']);
  return { root, branch, head };
}

export function markdownLines(text) {
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/);
  const visible = [];
  let fence = null;
  for (const line of lines) {
    const indent = line.match(/^ */)?.[0].length ?? 0;
    const body = line.slice(indent);
    if (fence) {
      const closes =
        indent <= 3 &&
        body.length >= fence.length &&
        body.slice(0, fence.length) === fence.character.repeat(fence.length) &&
        [...body.slice(fence.length)].every(
          (character) => character === fence.character || character === ' ' || character === '\t',
        );
      visible.push(false);
      if (closes) fence = null;
      continue;
    }
    const opening = indent <= 3 ? body.match(/^(`{3,}|~{3,})/)?.[0] : undefined;
    if (opening) {
      visible.push(false);
      fence = { character: opening[0], length: opening.length };
      continue;
    }
    visible.push(true);
  }
  return { lines, visible };
}

export function headings(lines, visible) {
  const found = [];
  lines.forEach((line, index) => {
    if (!visible[index]) return;
    const match = line.match(/^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (match) found.push({ index, level: match[1].length, title: match[2].trim(), line });
  });
  return found;
}

export function parseTasks(text, path) {
  const source = markdownLines(text);
  const sectionHeadings = headings(source.lines, source.visible);
  const tasks = [];
  const seen = new Map();
  source.lines.forEach((line, index) => {
    if (!source.visible[index]) return;
    const match = line.match(/^ {0,3}[-*+]\s+\[([ xX])\]\s+(T\d{3})\b.*$/);
    if (!match) return;
    const id = match[2];
    if (seen.has(id))
      fail(
        `Duplicate canonical task ID ${id} in ${path} at lines ${seen.get(id)} and ${index + 1}.`,
      );
    seen.set(id, index + 1);
    const prior = sectionHeadings.filter((heading) => heading.index < index);
    const phase =
      [...prior].reverse().find((heading) => /\bphase\b/i.test(heading.title)) ??
      prior.at(-1) ??
      null;
    tasks.push({ id, checked: match[1].toLowerCase() === 'x', line, lineIndex: index, phase });
  });
  if (tasks.length === 0) fail(`No canonical task checkbox lines were found in ${path}.`);
  tasks.forEach((task, index) => {
    const end = tasks[index + 1]?.lineIndex ?? source.lines.length;
    const field = source.lines.slice(task.lineIndex + 1, end).find((line, offset) =>
      source.visible[task.lineIndex + 1 + offset] && /^\s*[-*+]\s+\*\*Dependencies\*\*\s*:/i.test(line),
    );
    const value = field?.match(/^\s*[-*+]\s+\*\*Dependencies\*\*\s*:\s*(.*)$/i)?.[1]?.trim() ?? null;
    task.dependenciesDeclared = value !== null && value.length > 0;
    task.dependencies = value && !/^none\b/i.test(value)
      ? [...new Set(value.match(/\b(?:T\d{3}|X\d{2}(?:-[A-Z0-9]+)*)\b/g) ?? [])]
      : [];
  });
  return { ...source, tasks, headings: sectionHeadings };
}

export function findTask(parsed, id, path) {
  const task = parsed.tasks.find((entry) => entry.id === id);
  if (task) return task;
  const known = parsed.tasks.map((entry) => entry.id).join(', ');
  fail(`Unknown task ID ${id} in ${path}. Canonical IDs: ${known}.`);
}

export function normalizedRepoPath(root, file) {
  return relative(root, file).split(sep).join('/');
}

export async function readOptionalText(root, path) {
  try {
    const file = await repoFile(root, path, 'context path');
    return (await readFile(file, 'utf8')).replace(/^\uFEFF/, '');
  } catch (error) {
    if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT')
      return null;
    throw error;
  }
}
