import { realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { fail, resolveRoot, usage } from './agent-context-common.mjs';
import { handoff } from './agent-context-assignment.mjs';
import { resumeReport } from './agent-context-resume.mjs';
import { taskContext } from './agent-context-task.mjs';
import { snapshot, verify } from './agent-context-snapshot.mjs';

function parseArguments(argv) {
  if (argv.length === 0 || (argv.length === 1 && ['--help', '-h'].includes(argv[0]))) {
    return { help: true };
  }
  const mode = argv[0];
  if (!['assignment', 'handoff', 'resume', 'task', 'snapshot', 'verify'].includes(mode)) fail(`Unknown mode: ${mode}`);
  if (mode === 'assignment') {
    fail('Legacy UC assignment is disabled for LifeMate. Use the current project context and GitHub issue or PR for ownership and scope.');
  }
  if (argv.slice(1).includes('--help') || argv.slice(1).includes('-h')) {
    if (argv.length === 2) return { help: true };
    fail('Help cannot be combined with other options.');
  }

  const values = new Map();
  const files = [];
  const authorization = [];
  for (let index = 1; index < argv.length; index += 1) {
    const option = argv[index];
    if (option === '--authorization') {
      if (mode !== 'resume') fail('--authorization is only valid for resume.');
      const value = argv[index + 1];
      if (typeof value !== 'string' || value.length === 0 || value.startsWith('--')) {
        fail('--authorization requires a repo-relative path.');
      }
      authorization.push(value);
      index += 1;
      continue;
    }
    if (option === '--files') {
      if (values.has(option)) fail('--files may be supplied once.');
      values.set(option, true);
      while (index + 1 < argv.length && !argv[index + 1].startsWith('--')) {
        files.push(argv[index + 1]);
        index += 1;
      }
      if (files.length === 0) fail('--files requires at least one repo-relative path.');
      continue;
    }
    if (!['--uc', '--tasks', '--task', '--plan', '--snapshot', '--root'].includes(option)) {
      fail(`Unknown option or positional argument: ${option}`);
    }
    if (values.has(option)) fail(`${option} may be supplied once.`);
    const value = argv[index + 1];
    if (typeof value !== 'string' || value.length === 0 || value.startsWith('--')) {
      fail(`${option} requires a value.`);
    }
    values.set(option, value);
    index += 1;
  }

  const allowed = {
    assignment: ['--uc', '--root'],
    handoff: ['--tasks', '--root'],
    resume: ['--tasks', '--root'],
    task: ['--tasks', '--task', '--plan', '--root'],
    snapshot: ['--files', '--root'],
    verify: ['--snapshot', '--root'],
  }[mode];
  for (const option of values.keys()) {
    if (!allowed.includes(option)) fail(`${option} is not valid for ${mode}.`);
  }
  for (const required of {
    assignment: ['--uc'],
    handoff: ['--tasks'],
    resume: [],
    task: ['--tasks', '--task'],
    snapshot: ['--files'],
    verify: ['--snapshot'],
  }[mode]) {
    if (!values.has(required)) fail(`${mode} requires ${required}.`);
  }
  if (mode === 'task' && !/^T\d{3}$/.test(values.get('--task'))) {
    fail(`Invalid task ID ${values.get('--task')}; use a canonical ID such as T017.`);
  }
  return { mode, values, files, authorization };
}

async function main() {
  const args = parseArguments(process.argv.slice(2));
  if (args.help) {
    process.stdout.write(`${usage}\n`);
    return;
  }
  const values = args.values;
  const root = await resolveRoot(values.get('--root'));
  if (args.mode === 'handoff') return handoff(root, values.get('--tasks'));
  if (args.mode === 'resume') return resumeReport(root, values.get('--tasks'), args.authorization);
  if (args.mode === 'task')
    return taskContext(root, values.get('--tasks'), values.get('--task'), values.get('--plan'));
  if (args.mode === 'snapshot') return snapshot(root, args.files);
  return verify(root, values.get('--snapshot'));
}

const invokedPath = (() => {
  try {
    return process.argv[1] ? realpathSync(process.argv[1]) : null;
  } catch {
    return null;
  }
})();
if (invokedPath && invokedPath === realpathSync(fileURLToPath(import.meta.url))) {
  main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
