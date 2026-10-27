import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runWorkflow } from '../../../scripts/agents/pr-workflow.mjs';
import { packageScriptCommand } from '../../../scripts/agents/workflow-gate.mjs';

export function evidence() {
  return {
    head: 'abc',
    pr: { state: 'OPEN', headRefOid: 'abc', headRefName: 'feat/010-tooling-example', title: 'feat/010-tooling-example: add the example workflow', baseRefName: 'development', reviewDecision: 'APPROVED',
      reviews: { pageInfo: { hasPreviousPage: false }, nodes: [{ author: { login: 'coderabbitai', __typename: 'Bot' }, state: 'APPROVED', commit: { oid: 'abc' } }] },
      reviewThreads: { pageInfo: { hasNextPage: false }, nodes: [] } },
    checks: ['contributor-checks (ubuntu-latest)', 'contributor-checks (windows-latest)', 'runtime-checks (ubuntu-latest)', 'runtime-checks (windows-latest)'].map((name, id) => ({ id, name, head_sha: 'abc', status: 'completed', conclusion: 'success', app: { slug: 'github-actions' } })),
  };
}

export async function checkout(t) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'pr-workflow-')));
  t.after(() => rm(root, { recursive: true, force: true }));
  const git = (...args) => {
    const result = spawnSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true });
    assert.equal(result.status, 0, result.stderr); return result.stdout.trim();
  };
  git('init', '--quiet'); git('config', 'user.name', 'Tests'); git('config', 'user.email', 'tests@example.invalid');
  await writeFile(join(root, '.gitignore'), '.agent-work/\n');
  git('add', '.gitignore'); git('commit', '--quiet', '-m', 'base');
  git('update-ref', 'refs/remotes/origin/development', 'HEAD');
  git('checkout', '--quiet', '-b', 'feat/010-tooling-example');
  git('remote', 'add', 'origin', 'https://github.com/example/project.git');
  await writeFile(join(root, 'change.md'), 'change\n'); git('add', 'change.md'); git('commit', '--quiet', '-m', 'feature');
  await mkdir(join(root, '.agent-work'));
  // Existing numbered work retains v1 accounting; new-name tests switch to a fresh branch.
  await mkdir(join(root, '.agent-work/pr-workflow'));
  await writeFile(join(root, '.agent-work/pr-workflow/010-tooling-example.json'), JSON.stringify({ schemaVersion: 1, repository: 'example/project', branch: 'feat/010-tooling-example', base: 'development', repairRounds: [], conventionVersion: 1 }));
  const body = join(root, '.agent-work/body.md'); await writeFile(body, '## Summary\n\nStandardize tooling.\n\n## Evidence\n\nBefore: legacy behavior; after: verified checks.\n\n## Merge Danger\n\n**Door:** two-way; revert commit.\n\n**Blast Radius:** tooling; integration checks required.');
  const head = git('rev-parse', 'HEAD');
  const e = evidence(); e.head = head; e.pr.headRefOid = head; e.pr.reviews.nodes[0].commit.oid = head;
  for (const check of e.checks) check.head_sha = head;
  Object.assign(e.pr, { number: 1, url: 'https://github.com/example/project/pull/1', isDraft: true });
  let created = false, failGate = false;
  const comments = [];
  const calls = [];
  const execute = (binary, args) => {
    calls.push([binary, ...args]);
    if (binary === process.execPath || binary === packageScriptCommand('test:contributors').command) { if (failGate) throw new Error('Local gate failed'); return 'passed'; }
    if (binary === 'git') {
      if (args[0] === 'fetch') return '';
      if (args[0] === 'ls-remote' && args.includes('origin')) return '';
      if (args[0] === 'push') { e.pr.headRefOid = git('rev-parse', 'HEAD'); for (const check of e.checks) check.head_sha = e.pr.headRefOid; return ''; }
      return git(...args);
    }
    if (args[0] === 'pr' && args[1] === 'list') return JSON.stringify(created && e.pr.state === 'OPEN' ? [{ ...e.pr }] : []);
    if (args[0] === 'pr' && args[1] === 'view') return JSON.stringify(e.pr);
    if (args[0] === 'pr' && args[1] === 'create') { created = true; return e.pr.url; }
    if (args[0] === 'pr' && args[1] === 'ready') { e.pr.isDraft = false; return ''; }
    if (args[0] === 'pr' && args[1] === 'comment') { comments.push({ body: args[args.indexOf('--body') + 1] }); return ''; }
    if (args[0] === 'api' && args.at(-1).includes('/pulls?')) return JSON.stringify([[]]);
    if (args[0] === 'api' && args[1] === 'graphql') return JSON.stringify({ data: { repository: { pullRequest: e.pr } } });
    if (args[0] === 'api' && args.at(-1).includes('/comments?')) return JSON.stringify([comments]);
    if (args[0] === 'api') return JSON.stringify([{ check_runs: e.checks }]);
    return '';
  };
  const run = (...args) => runWorkflow([...args, ...(args[0] === 'publish' ? ['--summary', 'add the example workflow'] : []), '--root', root], { execute });
  let revision = 0;
  const advance = async () => { await writeFile(join(root, 'change.md'), `repair ${++revision}\n`); git('add', 'change.md'); git('commit', '--quiet', '-m', `repair ${revision}`); };
  return { root, body, e, calls, run, execute, advance, fail: () => { failGate = true; } };
}
