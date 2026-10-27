import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

function runGit(cwd, args, env) {
  const result = spawnSync('git', args, { cwd, encoding: 'utf8', env, windowsHide: true, timeout: 10_000 });
  if (result.error) throw result.error;
  return result;
}

export function installGitHooks(cwd = process.cwd(), env = process.env) {
  let rootResult;
  try {
    rootResult = runGit(cwd, ['rev-parse', '--show-toplevel'], env);
  } catch (error) {
    if (error?.code === 'ENOENT') return { status: 'outside-git' };
    throw error;
  }
  if (rootResult.status !== 0) return { status: 'outside-git' };
  const root = resolve(rootResult.stdout.trim());
  if (!existsSync(resolve(root, '.githooks', 'pre-commit'))) throw new Error('Repository pre-commit hook is missing at .githooks/pre-commit.');

  const configured = runGit(root, ['config', '--get-all', 'core.hooksPath'], env);
  if (configured.status === 0) {
    const values = configured.stdout.trim().split(/\r?\n/);
    if (values.length === 1 && values[0] === '.githooks') return { status: 'already-configured' };
    return { status: 'custom-path-preserved', path: configured.stdout.trim() };
  }
  if (configured.status !== 1) throw new Error(configured.stderr.trim() || 'Could not read Git core.hooksPath.');

  const update = runGit(root, ['config', '--local', 'core.hooksPath', '.githooks'], env);
  if (update.status !== 0) throw new Error(update.stderr.trim() || 'Could not configure Git core.hooksPath.');
  return { status: 'installed' };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = installGitHooks();
    if (result.status === 'installed') console.log('Installed repository Git hooks at .githooks.');
    else if (result.status === 'already-configured') console.log('Repository Git hooks are already configured.');
    else if (result.status === 'custom-path-preserved') console.warn(`Preserved custom core.hooksPath (${result.path}); the repository pre-commit hook was not activated.`);
    else console.log('Skipping Git hook setup outside a Git checkout.');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
