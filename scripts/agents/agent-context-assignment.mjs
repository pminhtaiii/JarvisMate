import { readFile } from 'node:fs/promises';
import { isAbsolute, resolve } from 'node:path';
import { checkout, fail, headings, isInside, markdownLines, normalizedRepoPath, parseTasks, readOptionalText, repoFile } from './agent-context-common.mjs';

export async function assignment(root, uc) {
  void root;
  void uc;
  fail('Legacy UC assignment is disabled for LifeMate. Use the current project context and GitHub issue or PR for ownership and scope.');
}

export function workflowEvidencePointers(root, activeText) {
  if (!activeText) return [];
  const source = markdownLines(activeText);
  const sectionHeadings = headings(source.lines, source.visible);
  const first = sectionHeadings.find((heading) => heading.level === 2);
  if (!first) return [];
  const end =
    sectionHeadings.find((heading) => heading.level <= first.level && heading.index > first.index)
      ?.index ?? source.lines.length;
  const result = [];
  for (let index = first.index + 1; index < end; index += 1) {
    if (!source.visible[index]) continue;
    for (const match of source.lines[index].matchAll(
      /\[([^\]]*(?:evidence|verification|record)[^\]]*)\]\(([^)]+)\)/gi,
    )) {
      const target = match[2].split('#')[0];
      if (!target || /^[a-z]+:/i.test(target) || isAbsolute(target)) continue;
      const resolved = resolve(root, 'context', target);
      if (isInside(root, resolved)) result.push(normalizedRepoPath(root, resolved));
      if (result.length === 3) return result;
    }
  }
  return result;
}

export async function handoff(root, tasksInput) {
  const tasksFile = await repoFile(root, tasksInput, '--tasks');
  const tasksText = (await readFile(tasksFile, 'utf8')).replace(/^\uFEFF/, '');
  const parsed = parseTasks(tasksText, tasksInput);
  const current = await checkout(root);
  const checked = parsed.tasks.filter((task) => task.checked).length;
  const open = parsed.tasks.length - checked;
  const candidate = parsed.tasks.find((task) => !task.checked);
  const activeText = await readOptionalText(root, 'context/active-feature.md');
  const workflowText = await readOptionalText(root, 'context/workflow.md');
  const workflowSource = workflowText ? markdownLines(workflowText) : null;
  const gates = workflowSource
    ? headings(workflowSource.lines, workflowSource.visible).filter((heading) =>
        /^Step [234]:/.test(heading.title),
      )
    : [];
  const evidence = workflowEvidencePointers(root, activeText);

  process.stdout.write(
    `Checkout: ${current.root}\nBranch: ${current.branch ?? '(detached)'}\nHEAD: ${current.head}\n`,
  );
  process.stdout.write(
    `Tasks: ${normalizedRepoPath(root, tasksFile)}\nCanonical tasks: ${checked} checked; ${open} open; ${parsed.tasks.length} total\n`,
  );
  process.stdout.write(
    candidate
      ? `First unchecked candidate (not authorization): ${candidate.line}\n`
      : 'First unchecked candidate: none\n',
  );
  process.stdout.write(
    'Workflow pointers: context/active-feature.md (checkpoint), context/workflow.md (sequence), context/testing.md (verification gates)\n',
  );
  if (evidence.length > 0)
    process.stdout.write(`Evidence pointers from active-feature.md: ${evidence.join(', ')}\n`);
  if (gates.length > 0) {
    process.stdout.write(
      `Next workflow stages (reference only): ${gates.map((heading) => heading.title).join(' -> ')}\n`,
    );
  } else {
    process.stdout.write(
      'Next workflow stages: consult context/workflow.md; no stage status is inferred.\n',
    );
  }
}
