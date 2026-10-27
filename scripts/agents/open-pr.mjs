import { spawnSync } from 'node:child_process';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const usage = `Usage: node scripts/agents/open-pr.mjs --remote <name> --base <branch> --title <title> --body-file <path>

Runs context, lint and contributor gates, verifies a clean feature branch based on the current remote base, pushes without force, and creates a draft PR. Re-running returns an existing open PR for the same head/base.`;

function execute(binary, args, cwd) {
  const result = spawnSync(binary, args, { cwd, encoding: 'utf8', windowsHide: true, maxBuffer: 2 * 1024 * 1024 });
  if (result.error || result.status !== 0) throw new Error(`${binary} failed: ${result.error?.message ?? result.stderr?.trim() ?? result.status}`);
  return result.stdout.trim();
}

function parseArgs(args) {
  const values = {};
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i]?.slice(2);
    if (!args[i]?.startsWith('--') || !['remote', 'base', 'title', 'body-file'].includes(key) || values[key] || !args[i + 1] || args[i + 1].startsWith('--')) throw new Error(usage);
    values[key] = args[i + 1];
  }
  for (const key of ['remote', 'base', 'title', 'body-file']) if (!values[key]) throw new Error(usage);
  if (!/^[A-Za-z0-9._-]+$/.test(values.remote) || !/^[A-Za-z0-9._/-]+$/.test(values.base) || values.base.startsWith('-')) throw new Error('Invalid remote or base name.');
  return values;
}

export async function openPr(args, dependencies = {}) {
  if (args.length === 1 && ['--help', '-h'].includes(args[0])) return { usage };
  const values = parseArgs(args);
  const root = resolve(dependencies.root ?? resolve(dirname(fileURLToPath(import.meta.url)), '../..'));
  const call = (binary, argv) => (dependencies.execute ?? execute)(binary, argv, root);
  const git = (...argv) => call('git', argv);
  const origin = git('remote', 'get-url', values.remote);
  const match = origin.match(/^(?:https:\/\/github\.com\/|git@github\.com:)([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+?)(?:\.git)?$/);
  if (!match) throw new Error('Selected remote must identify a GitHub repository over HTTPS or SSH.');
  const repo = match[1];
  const current = git('branch', '--show-current');
  if (!/^feat\/[a-z0-9]+(?:-[a-z0-9]+)*$/.test(current)) throw new Error('Open PR requires a feat/scope-description branch.');
  if (git('status', '--porcelain', '--untracked-files=all')) throw new Error('Open PR requires a clean checkout.');
  const head = git('rev-parse', 'HEAD');
  git('fetch', '--no-tags', values.remote, `refs/heads/${values.base}`);
  const base = git('rev-parse', 'FETCH_HEAD');
  const common = git('merge-base', head, base);
  if (!common || common !== base) throw new Error(`Feature branch is not up to date with ${values.remote}/${values.base}; integrate the fetched base first.`);
  const pnpm = process.platform === 'win32'
    ? script => ['cmd.exe', ['/d', '/s', '/c', `pnpm run ${script}`]]
    : script => ['pnpm', ['run', script]];
  const gates = [
    ['node', ['scripts/ci/check-context.mjs']],
    pnpm('lint'),
    pnpm('test:contributors'),
  ];
  for (const [binary, argv] of gates) call(binary, argv);
  if (git('status', '--porcelain', '--untracked-files=all') || git('rev-parse', 'HEAD') !== head || git('branch', '--show-current') !== current) throw new Error('Checkout changed during gates; inspect before publishing.');
  git('push', values.remote, `HEAD:refs/heads/${current}`);
  const existing = JSON.parse(call('gh', ['pr', 'list', '--repo', repo, '--head', current, '--base', values.base, '--state', 'open', '--json', 'number,url,headRefName,baseRefName,isDraft']));
  if (!Array.isArray(existing) || existing.some(pr => pr.headRefName !== current || pr.baseRefName !== values.base)) throw new Error('GitHub returned conflicting PR metadata.');
  if (existing.length > 1) throw new Error('Multiple open PRs match this head and base; inspect them before retrying.');
  if (existing[0]) return { status: 'EXISTING', ...existing[0] };
  const url = call('gh', ['pr', 'create', '--repo', repo, '--draft', '--head', current, '--base', values.base, '--title', values.title, '--body-file', resolve(root, values['body-file'])]);
  return { status: 'CREATED', url };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  openPr(process.argv.slice(2)).then(result => console.log(JSON.stringify(result, null, 2))).catch(error => { console.error(error.message); process.exitCode = 1; });
}
