import { readFile } from 'node:fs/promises';
import { basename } from 'node:path';
import { findTask, headings, markdownLines, normalizedRepoPath, parseTasks, repoFile } from './agent-context-common.mjs';

export function taskConstraints(parsed, task) {
  const storyTags = [...task.line.matchAll(/\[(US\d+)\]/g)].map((match) => match[1]);
  const result = [];
  const add = (line) => {
    const value = line.trim();
    if (value && !result.includes(value)) result.push(value);
  };
  if (task.phase) {
    const end =
      parsed.headings.find(
        (heading) => heading.index > task.phase.index && heading.level <= task.phase.level,
      )?.index ?? parsed.lines.length;
    let owner = null;
    for (let index = task.phase.index + 1; index < end; index += 1) {
      if (!parsed.visible[index]) continue;
      const line = parsed.lines[index];
      const taskLine = line.match(/^ {0,3}[-*+]\s+\[[ xX]\]\s+(T\d{3})\b/);
      if (taskLine) {
        owner = taskLine[1];
        continue;
      }
      if (/^\s+\S/.test(line)) {
        if (owner === null || owner === task.id) add(line);
        continue;
      }
      if (line.trim()) owner = null;
      add(line);
    }
  }
  const dependency = parsed.headings.find((heading) => /dependency graph/i.test(heading.title));
  if (dependency) {
    const end =
      parsed.headings.find(
        (heading) => heading.index > dependency.index && heading.level <= dependency.level,
      )?.index ?? parsed.lines.length;
    for (let index = dependency.index + 1; index < end; index += 1) {
      const line = parsed.lines[index];
      if (!parsed.visible[index]) continue;
      if (
        line.includes(task.id) ||
        storyTags.some((tag) => line.includes(tag)) ||
        (task.line.includes('[P]') && line.includes('[P] marks'))
      )
        add(line);
    }
  }
  return result;
}

export function taskArtifacts(taskLine) {
  const paths = [];
  for (const token of taskLine.split(/\s+/)) {
    const candidate = token.replace(/^[`"'(]+/, '').replace(/[.`"'),;]+$/, '');
    if (/^(?:[^/\\\s]+[/\\])*[^/\\\s]+\.[A-Za-z0-9_-]+$/.test(candidate))
      paths.push(candidate.replaceAll('\\', '/'));
  }
  return paths.flatMap((path) => {
    const implementationPath = path.replace(
      /\.(?:spec|test|e2e-spec|unit)(?=\.(?:ts|tsx|js|mjs)$)/i,
      '',
    );
    return [...new Set([path, implementationPath])];
  });
}

export function sharedInterfaces(taskLine) {
  const names = new Set(taskLine.match(/\b[A-Z][A-Z0-9_]*_(?:PORT|INTERFACE|CONTRACT)\b/g) ?? []);
  for (const match of taskLine.matchAll(/(?:^|[/\\])ports[/\\]([a-z0-9-]+)\.port\.ts\b/gi)) {
    names.add(`${match[1].replaceAll('-', '_').toUpperCase()}_PORT`);
  }
  return [...names];
}

export function expandPlanPathBraces(line) {
  const open = line.indexOf('{');
  const close = line.indexOf('}', open + 1);
  if (
    open < 0 ||
    close < 0 ||
    line.indexOf('{', open + 1) >= 0 ||
    line.indexOf('}', close + 1) >= 0
  )
    return [line];
  const choices = line
    .slice(open + 1, close)
    .split(',')
    .map((choice) => choice.trim());
  if (choices.length < 2 || choices.some((choice) => choice.length === 0)) return [line];
  const prefix = line.slice(0, open);
  const suffix = line.slice(close + 1);
  return choices.map((choice) => `${prefix}${choice}${suffix}`);
}

export function planSections(planText, task) {
  const source = markdownLines(planText);
  const sectionHeadings = headings(source.lines, source.visible);
  const artifacts = taskArtifacts(task.line);
  const sectionMatches = [];
  for (const heading of sectionHeadings) {
    const end =
      sectionHeadings.find((next) => next.index > heading.index)?.index ?? source.lines.length;
    const lines = [];
    for (let index = heading.index + 1; index < end; index += 1) {
      if (!source.visible[index]) continue;
      const line = source.lines[index];
      if (
        line.includes(task.id) ||
        artifacts.some((path) => {
          const normalizedLine = line.replaceAll('\\', '/');
          const normalizedPath = path.replaceAll('\\', '/');
          return (
            normalizedLine.includes(normalizedPath) ||
            (!normalizedLine.includes('/') && normalizedLine.includes(basename(normalizedPath))) ||
            expandPlanPathBraces(normalizedLine).some((expanded) =>
              expanded.includes(normalizedPath),
            )
          );
        })
      )
        lines.push(line.trim());
    }
    if (heading.title.includes(task.id) || lines.length > 0)
      sectionMatches.push({ title: heading.line, lines });
  }
  return { source, sections: sectionMatches, interfaces: sharedInterfaces(task.line) };
}

export async function taskContext(root, tasksInput, taskId, planInput) {
  const tasksFile = await repoFile(root, tasksInput, '--tasks');
  const parsed = parseTasks((await readFile(tasksFile, 'utf8')).replace(/^\uFEFF/, ''), tasksInput);
  const task = findTask(parsed, taskId, tasksInput);
  process.stdout.write(
    `Task: ${task.id}\nPhase: ${task.phase?.line ?? '(no phase heading found)'}\nCanonical task line:\n${task.line}\n`,
  );

  const constraints = taskConstraints(parsed, task);
  process.stdout.write('Task-file constraints:\n');
  process.stdout.write(
    constraints.length > 0
      ? `${constraints.map((line) => `- ${line}`).join('\n')}\n`
      : '- No additional phase or dependency note applies.\n',
  );

  if (!planInput) {
    process.stdout.write('Plan: omitted; pass --plan to retrieve matching plan context.\n');
    return;
  }
  const planFile = await repoFile(root, planInput, '--plan');
  const plan = planSections(await readFile(planFile, 'utf8'), task);
  process.stdout.write(`Matching plan sections from ${normalizedRepoPath(root, planFile)}:\n`);
  if (plan.sections.length === 0)
    process.stdout.write(
      `- No task-specific heading or target-artifact section matched ${task.id}; plan body omitted.\n`,
    );
  for (const section of plan.sections) {
    process.stdout.write(`${section.title}\n`);
    for (const line of section.lines) process.stdout.write(`${line}\n`);
  }

  process.stdout.write('Shared interfaces referenced by the task:\n');
  if (plan.interfaces.length === 0) {
    process.stdout.write('- None named in the task line or target port paths.\n');
    return;
  }
  for (const name of plan.interfaces) {
    const matches = plan.source.lines.filter(
      (line, index) => plan.source.visible[index] && line.includes(name),
    );
    process.stdout.write(
      matches.length > 0
        ? `${matches.map((line) => `- ${name}: ${line.trim()}`).join('\n')}\n`
        : `- ${name}\n`,
    );
  }
}
