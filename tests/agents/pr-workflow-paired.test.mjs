import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { runWorkflow } from '../../scripts/agents/pr-workflow.mjs';
import { checkout } from './support/pr-workflow-fixture.mjs';

test('paired publication resumes after a partial private PR failure and gates completion on both receipt links', async t => {
  const f = await checkout(t);
  assert.equal(spawnSync('git', ['switch', '-c', 'feat/tooling-paired-naming'], { cwd: f.root, windowsHide: true }).status, 0);
  Object.assign(f.e.pr, { headRefName: 'feat/tooling-paired-naming', title: 'feat/tooling-paired-naming: add the paired workflow' });
  const git = (cwd, ...args) => {
    const result = spawnSync('git', args, { cwd, encoding: 'utf8', windowsHide: true });
    assert.equal(result.status, 0, result.stderr); return result.stdout.trim();
  };
  const privateRemote = join(f.root, '.agent-work/private.git');
  const privateSeed = join(f.root, '.agent-work/private-seed');
  await mkdir(privateSeed);
  git(f.root, 'init', '--bare', '--initial-branch=main', privateRemote);
  git(f.root, 'init', '--initial-branch=main', privateSeed);
  git(privateSeed, 'config', 'user.name', 'Private Seed');
  git(privateSeed, 'config', 'user.email', 'private@example.invalid');
  await writeFile(join(privateSeed, 'README.md'), '# Unrelated coursework history\n');
  git(privateSeed, 'add', '.');
  git(privateSeed, 'commit', '--quiet', '-m', 'private initial history');
  git(privateSeed, 'remote', 'add', 'origin', privateRemote);
  git(privateSeed, 'push', '--quiet', 'origin', 'HEAD:refs/heads/main');
  git(privateSeed, 'push', '--quiet', 'origin', 'HEAD:refs/heads/development');
  git(f.root, 'remote', 'add', 'submission', 'https://github.com/course/private.git');
  git(f.root, 'config', `url.${privateRemote.replace(/\\/g, '/')}.insteadOf`, 'https://github.com/course/private.git');
  await writeFile(join(f.root, 'publication-targets.json'), JSON.stringify({ schemaVersion: 1, submission: { remote: 'submission', base: 'development' } }));
  git(f.root, 'add', 'publication-targets.json');
  git(f.root, 'commit', '--quiet', '-m', 'enable paired publication');

  const privateMain = git(f.root, 'ls-remote', 'submission', 'refs/heads/main').split(/\s+/)[0];
  const privatePrs = [];
  const pairedCalls = [];
  let failPrivateCreate = true;
  const privateHead = ref => {
    const output = git(f.root, 'ls-remote', '--heads', 'submission', ref);
    return output ? output.split(/\s+/)[0] : undefined;
  };
  const privateGh = args => {
    if (args[0] === 'repo' && args[1] === 'view') {
      return JSON.stringify(args[2] === 'course/private'
        ? { visibility: 'PRIVATE', isPrivate: true, viewerPermission: 'WRITE' }
        : { visibility: 'PUBLIC', isPrivate: false, viewerPermission: 'ADMIN' });
    }
    const repository = args[args.indexOf('--repo') + 1];
    if (repository !== 'course/private') return undefined;
    if (args[0] === 'pr' && args[1] === 'list') {
      return JSON.stringify(privatePrs.map(({ number, url, baseRefName, headRefName, state }) => ({ number, url, baseRefName, headRefName, state })));
    }
    if (args[0] === 'pr' && args[1] === 'view') {
      const pr = privatePrs.find(item => item.number === Number(args[2]));
      if (!pr) throw new Error('Private PR not found');
      pr.headRefOid = privateHead(`refs/heads/${pr.headRefName}`);
      return JSON.stringify(pr);
    }
    if (args[0] === 'pr' && args[1] === 'create') {
      if (failPrivateCreate) { failPrivateCreate = false; throw new Error('simulated private PR create failure'); }
      const number = 7;
      const pr = {
        number, url: `https://github.com/course/private/pull/${number}`, title: args[args.indexOf('--title') + 1],
        body: readFileSync(args[args.indexOf('--body-file') + 1], 'utf8'), state: 'OPEN', isDraft: args.includes('--draft'),
        headRefName: args[args.indexOf('--head') + 1], baseRefName: args[args.indexOf('--base') + 1],
        headRefOid: privateHead(`refs/heads/${args[args.indexOf('--head') + 1]}`),
      };
      privatePrs.push(pr);
      return pr.url;
    }
    if (args[0] === 'pr' && args[1] === 'ready') {
      const pr = privatePrs.find(item => item.number === Number(args[2]));
      if (!pr) throw new Error('Private PR not found');
      pr.isDraft = false;
      return '';
    }
    throw new Error(`Unexpected private GitHub command: ${args.join(' ')}`);
  };
  const execute = (binary, args, cwd, timeout) => {
    if (binary === 'gh') {
      if (args[0] === 'repo' && args[1] === 'view' || args.includes('--repo') && args[args.indexOf('--repo') + 1] === 'course/private') {
        pairedCalls.push([binary, ...args]);
        return privateGh(args);
      }
      return f.execute(binary, args, cwd, timeout);
    }
    if (binary === 'git' && args[0] === 'remote' && args[1] === 'get-url' && args[2] === 'submission') {
      return 'https://github.com/course/private.git';
    }
    if (binary === 'git' && (args[0] === 'fetch' && args.includes('submission') || args[0] === 'push' && args[1] === 'submission')) {
      pairedCalls.push([binary, ...args]);
      const result = spawnSync('git', args, { cwd, timeout, encoding: 'utf8', windowsHide: true });
      assert.equal(result.status, 0, result.stderr); return result.stdout.trim();
    }
    return f.execute(binary, args, cwd, timeout);
  };
  const run = (...args) => runWorkflow([...args, '--root', f.root], { execute });
  const publish = () => run('publish', '--body-file', f.body, '--summary', 'add the paired workflow');

  await writeFile(f.body, 'Summary includes https://github.com/course/private/pull/7');
  f.calls.length = 0;
  await assert.rejects(publish(), /private/i);
  assert.equal(f.calls.some(call => call[0] === 'git' && call[1] === 'push' && call[2] === 'origin' || call[0] === 'gh' && call[1] === 'pr' && call[2] === 'create'), false, 'private repository identity must be rejected before public publication');
  await writeFile(f.body, '## Summary\n\nStandardize tooling.\n\n## Evidence\n\nBefore: legacy behavior; after: verified checks.\n\n## Merge Danger\n\n**Door:** two-way; revert commit.\n\n**Blast Radius:** tooling; integration checks required.');

  await assert.rejects(publish(), /submission publication incomplete/);
  const recordPath = join(f.root, '.agent-work/pr-workflow/tooling-paired-naming.json');
  const partial = JSON.parse(await readFile(recordPath, 'utf8'));
  assert.equal(partial.status, 'PARTIAL_PUBLICATION');
  assert.ok(partial.pr, 'the public PR remains recorded after the private create failure');
  assert.equal(privatePrs.length, 0);

  const published = await publish();
  assert.equal(published.status, 'PUBLISHED');
  assert.equal(privatePrs.length, 1);
  assert.equal(published.submission.number, 7);
  assert.equal(privatePrs[0].headRefName, 'feat/tooling-paired-naming');
  const publicCreate = f.calls.find(call => call[0] === 'gh' && call[1] === 'pr' && call[2] === 'create');
  assert.equal(privatePrs[0].title, publicCreate[publicCreate.indexOf('--title') + 1]);
  assert.equal(published.submission.head, privateHead('refs/heads/feat/tooling-paired-naming'));
  assert.equal(privateHead('refs/heads/main'), privateMain);
  assert.match(privatePrs[0].body, /https:\/\/github\.com\/example\/project\/pull\/1/);
  assert.doesNotMatch(await readFile(f.body, 'utf8'), /course\/private/);
  assert.equal(f.calls.filter(call => call[0] === 'gh' && call[1] === 'pr' && call[2] === 'create').length, 1);
  assert.equal(pairedCalls.filter(call => call[0] === 'gh' && call[1] === 'pr' && call[2] === 'create').length, 2, 'one failed create and one successful retry');

  const receiptPath = join(f.root, '.agent-work/app-state.json');
  const primaryOnly = { pullRequests: [{ url: published.url, repository: 'example/project', number: published.pr }] };
  await writeFile(receiptPath, JSON.stringify(primaryOnly));
  await assert.rejects(run('record-app-state', '--receipt', receiptPath), /both linked PRs|including submission/);
  await writeFile(receiptPath, JSON.stringify({ pullRequests: [
    ...primaryOnly.pullRequests,
    { url: published.submission.url, repository: published.submission.repository, number: published.submission.number },
  ] }));
  const linked = await run('record-app-state', '--receipt', receiptPath);
  assert.equal(linked.submissionAppLink.url, published.submission.url);

  const complete = await run('complete');
  assert.equal(complete.completion.submission.url, published.submission.url);
  assert.equal(complete.completion.submissionAppLink.url, published.submission.url);
  const ready = await run('ready');
  assert.equal(ready.status, 'AWAITING_HUMAN_MERGE');
  assert.equal(ready.submission.isDraft, false);
  assert.equal(privatePrs[0].isDraft, false);
  assert.equal(f.e.pr.isDraft, false);
});
