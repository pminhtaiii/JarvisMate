import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export function assertNoTrackedArtifacts(paths) {
  const dependencies = paths.split('\0').filter((path) => /(^|\/)node_modules(\/|$)/.test(path));
  if (dependencies.length) {
    throw new Error(`Installed dependencies must remain untracked (${dependencies.length} paths): ${dependencies.slice(0, 5).map((path) => JSON.stringify(path)).join(', ')}. Remove them with git rm --cached; preserve local files.`);
  }
  const evidence = paths.split('\0').filter((path) => path.startsWith('docs/verification/'));
  if (evidence.length) {
    throw new Error(`Verification records must remain local and untracked (${evidence.length} paths): ${evidence.slice(0, 5).map((path) => JSON.stringify(path)).join(', ')}. Remove them with git rm --cached; preserve local files.`);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = process.argv.slice(2);
    if (args.length && (args.length !== 2 || args[0] !== '--root')) throw new Error('Usage: node scripts/ci/check-tracked-files.mjs [--root <checkout>]');
    const paths = execFileSync('git', ['ls-files', '-z'], { cwd: args[1] ?? process.cwd(), encoding: 'utf8', windowsHide: true, timeout: 30_000, maxBuffer: 2 * 1024 * 1024 });
    assertNoTrackedArtifacts(paths);
    console.log('Tracked-file check passed: no installed dependencies or local-only verification records.');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
