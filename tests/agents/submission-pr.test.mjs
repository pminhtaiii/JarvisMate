import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { mkdtemp, mkdir, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import test from 'node:test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { inspectSubmissionTarget, publishSubmission, verifySubmission } from '../../scripts/agents/submission-pr.mjs';

const branch = 'feat/tooling-example';
const targets = {
  primary: { remote: 'origin', repository: 'example/public', base: 'development' },
  submission: { remote: 'submission', repository: 'course/private', base: 'development' },
};
const primaryPr = { number: 42, url: 'https://github.com/example/public/pull/42' };
const title = `${branch}: mirror the approved source`;
const body = '## Summary\n\nThe public review PR is authoritative.';

function git(cwd, ...args) {
  const result = spawnSync('git', args, { cwd, encoding: 'utf8', windowsHide: true });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, result.stderr || `git ${args.join(' ')} failed`);
  return result.stdout.trim();
}

function flag(args, name) { return args[args.indexOf(name) + 1]; }

async function fixture(t) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'submission-pr-')));
  t.after(() => rm(root, { recursive: true, force: true }));
  const source = join(root, 'source');
  const privateSeed = join(root, 'private-seed');
  const publicRemote = join(root, 'public.git');
  const privateRemote = join(root, 'private.git');
  await mkdir(source);

  git(root, 'init', '--bare', '--initial-branch=main', publicRemote);
  git(root, 'init', '--bare', '--initial-branch=main', privateRemote);
  git(root, 'init', '--initial-branch=main', source);
  git(source, 'config', 'user.name', 'Submission Test');
  git(source, 'config', 'user.email', 'submission@example.test');
  git(source, 'remote', 'add', 'origin', publicRemote);
  git(source, 'remote', 'add', 'submission', privateRemote);
  await writeFile(join(source, '.gitignore'), '.agent-work/\n');
  await writeFile(join(source, 'README.md'), '# Public project\n');
  await mkdir(join(source, 'src'));
  await writeFile(join(source, 'src', 'app.txt'), 'approved source\n');
  git(source, 'add', '.');
  git(source, 'commit', '--quiet', '-m', 'public source');
  git(source, 'push', '--quiet', 'origin', 'HEAD:refs/heads/main');
  git(source, 'push', '--quiet', 'origin', 'HEAD:refs/heads/development');
  git(source, 'switch', '--quiet', '-c', branch);
  await writeFile(join(source, 'src', 'feature.txt'), 'feature one\n');
  git(source, 'add', '.');
  git(source, 'commit', '--quiet', '-m', 'feature source');

  await mkdir(privateSeed);
  git(root, 'init', '--initial-branch=main', privateSeed);
  git(privateSeed, 'config', 'user.name', 'Private Seed');
  git(privateSeed, 'config', 'user.email', 'private@example.test');
  await writeFile(join(privateSeed, 'README.md'), '# Coursework submission\n');
  git(privateSeed, 'add', '.');
  git(privateSeed, 'commit', '--quiet', '-m', 'initial private history');
  git(privateSeed, 'push', '--quiet', privateRemote, 'HEAD:refs/heads/main');
  await writeFile(join(privateSeed, 'development.txt'), 'distinct private development base\n');
  git(privateSeed, 'add', '.');
  git(privateSeed, 'commit', '--quiet', '-m', 'private development base');
  git(privateSeed, 'push', '--quiet', privateRemote, 'HEAD:refs/heads/development');

  const repo = { root: source, primary: source };
  const prs = [];
  const calls = [];
  let createFailure;
  let pushFailure;
  let permission = 'WRITE';
  let submissionPrivate = true;
  const remoteHead = (ref) => {
    const output = git(source, 'ls-remote', '--heads', 'submission', ref);
    return output ? output.split(/\s+/)[0] : undefined;
  };
  const gh = (args) => {
    if (args[0] === 'repo' && args[1] === 'view') {
      const isSubmission = args[2] === targets.submission.repository;
      return JSON.stringify({
        visibility: isSubmission ? (submissionPrivate ? 'PRIVATE' : 'PUBLIC') : 'PUBLIC',
        isPrivate: isSubmission ? submissionPrivate : false,
        viewerPermission: isSubmission ? permission : 'ADMIN',
      });
    }
    if (args[0] === 'pr' && args[1] === 'list') {
      const found = prs.filter((pr) => pr.repository === flag(args, '--repo') && pr.headRefName === flag(args, '--head'));
      return JSON.stringify(found.map(({ number, url, baseRefName, headRefName, state }) => ({ number, url, baseRefName, headRefName, state })));
    }
    if (args[0] === 'pr' && args[1] === 'view') {
      const pr = prs.find((item) => item.number === Number(args[2]));
      if (!pr) throw new Error('PR not found');
      pr.headRefOid = remoteHead(`refs/heads/${pr.headRefName}`) ?? pr.headRefOid;
      return JSON.stringify(pr);
    }
    if (args[0] === 'pr' && args[1] === 'create') {
      if (createFailure === 'before') { createFailure = undefined; throw new Error('simulated create failure'); }
      const pr = {
        number: prs.length + 1,
        repository: flag(args, '--repo'),
        url: `https://github.com/${flag(args, '--repo')}/pull/${prs.length + 1}`,
        title: flag(args, '--title'),
        body: readFileSync(flag(args, '--body-file'), 'utf8'),
        state: 'OPEN',
        isDraft: args.includes('--draft'),
        baseRefName: flag(args, '--base'),
        headRefName: flag(args, '--head'),
        headRefOid: remoteHead(`refs/heads/${flag(args, '--head')}`),
      };
      prs.push(pr);
      if (createFailure === 'after') { createFailure = undefined; throw new Error('simulated lost create response'); }
      return pr.url;
    }
    if (args[0] === 'pr' && args[1] === 'edit') {
      const pr = prs.find((item) => item.number === Number(args[2]));
      if (!pr) throw new Error('PR not found');
      pr.title = flag(args, '--title');
      pr.body = readFileSync(flag(args, '--body-file'), 'utf8');
      return pr.url;
    }
    throw new Error(`Unexpected gh command: ${args.join(' ')}`);
  };
  const execute = (binary, args, cwd) => {
    calls.push([binary, ...args]);
    if (binary === 'gh') return gh(args);
    if (binary === 'git' && args[0] === 'remote' && args[1] === 'get-url') return args[2] === 'origin' ? 'https://github.com/example/public.git' : 'https://github.com/course/private.git';
    if (binary === 'git' && args[0] === 'push' && pushFailure) {
      const mode = pushFailure;
      pushFailure = undefined;
      if (mode === 'before') throw new Error('simulated push failure');
      const output = git(cwd, ...args);
      if (mode === 'after') throw new Error('simulated lost push response');
      return output;
    }
    return git(cwd, ...args);
  };
  const input = (extra = {}) => ({ repo, targets, branch, head: git(source, 'rev-parse', 'HEAD'), title, body, primaryPr, execute, ...extra });

  return {
    root, source, publicRemote, privateRemote, repo, prs, calls, execute, input,
    get permission() { return permission; }, set permission(value) { permission = value; },
    set submissionPrivate(value) { submissionPrivate = value; },
    set createFailure(value) { createFailure = value; },
    set pushFailure(value) { pushFailure = value; },
    remoteHead,
  };
}

test('inspection rejects a public submission repository before any publication write', async t => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'submission-pr-guard-')));
  t.after(() => rm(root, { recursive: true, force: true }));
  const calls = [];
  const execute = (binary, args) => {
    calls.push([binary, ...args]);
    if (binary === 'git' && args[0] === 'remote') return args[2] === 'origin' ? 'https://github.com/example/public.git' : 'https://github.com/course/private.git';
    if (binary === 'git' && args[0] === 'ls-remote') return `${'a'.repeat(40)}\t${args.at(-1)}`;
    if (binary === 'gh' && args[0] === 'repo' && args[1] === 'view') return JSON.stringify({ visibility: 'PUBLIC', isPrivate: false, viewerPermission: 'WRITE' });
    throw new Error(`Unexpected command: ${binary} ${args.join(' ')}`);
  };

  await assert.rejects(inspectSubmissionTarget({ repo: { root, primary: root }, targets, branch, execute }), /private/i);
  assert.equal(calls.some(([binary, ...args]) => binary === 'git' && args[0] === 'push' || binary === 'gh' && args.includes('create')), false);
});

test('publication mirrors the complete source tree onto private ancestry and verifies both identities', async t => {
  const f = await fixture(t);
  const publicMain = git(f.source, 'ls-remote', 'origin', 'refs/heads/main');
  const privateMain = f.remoteHead('refs/heads/main');
  const publicDevelopment = git(f.source, 'ls-remote', 'origin', 'refs/heads/development');
  const privateDevelopment = f.remoteHead('refs/heads/development');
  const sourceHead = git(f.source, 'rev-parse', 'HEAD');

  const published = await publishSubmission(f.input());
  const mirrorHead = f.remoteHead(`refs/heads/${branch}`);
  const sourceTree = git(f.source, 'rev-parse', `${sourceHead}^{tree}`);

  assert.equal(published.head, mirrorHead);
  assert.equal(published.sourceHead, sourceHead);
  assert.equal(published.sourceTree, sourceTree);
  assert.equal(published.base, 'development');
  assert.equal(published.isDraft, true);
  assert.equal(git(f.source, 'rev-parse', `${mirrorHead}^{tree}`), sourceTree);
  assert.equal(git(f.source, 'rev-parse', `${mirrorHead}^`), f.remoteHead('refs/heads/development'));
  assert.notEqual(git(f.source, 'rev-parse', `${mirrorHead}^`), privateMain);
  assert.equal(git(f.source, 'ls-remote', 'origin', 'refs/heads/main'), publicMain);
  assert.equal(f.remoteHead('refs/heads/main'), privateMain);
  assert.equal(git(f.source, 'ls-remote', 'origin', 'refs/heads/development'), publicDevelopment);
  assert.equal(f.remoteHead('refs/heads/development'), privateDevelopment);
  assert.deepEqual(f.calls.filter(c => c[0] === 'git' && c[1] === 'push'), [['git', 'push', 'submission', `${mirrorHead}:refs/heads/${branch}`]]);
  assert.match(f.prs[0].body, /https:\/\/github\.com\/example\/public\/pull\/42/);
  assert.doesNotMatch(f.prs[0].body, /course\/private/);

  assert.deepEqual(await verifySubmission({ ...f.input(), sourceHead }), published);
});

test('same-head retry reuses the mirror commit and PR; a new source tree advances the private branch', async t => {
  const f = await fixture(t);
  const first = await publishSubmission(f.input());
  const again = await publishSubmission(f.input());
  assert.equal(again.head, first.head);
  assert.equal(again.number, first.number);
  assert.equal(f.prs.length, 1);
  assert.equal(git(f.source, 'rev-list', '--count', `${f.remoteHead('refs/heads/development')}..${again.head}`), '1');

  await writeFile(join(f.source, 'src', 'feature.txt'), 'feature two\n');
  git(f.source, 'add', '.');
  git(f.source, 'commit', '--quiet', '-m', 'updated public source');
  const secondSource = git(f.source, 'rev-parse', 'HEAD');
  const second = await publishSubmission(f.input());

  assert.notEqual(second.head, first.head);
  assert.equal(git(f.source, 'rev-parse', `${second.head}^`), first.head);
  assert.equal(git(f.source, 'rev-parse', `${second.head}^{tree}`), git(f.source, 'rev-parse', `${secondSource}^{tree}`));
  assert.equal(f.prs.length, 1);
  assert.equal((await verifySubmission({ ...f.input(), sourceHead: secondSource })).head, second.head);

  const edited = await publishSubmission(f.input({ title: `${branch}: updated submission`, body: '## Updated summary\n\nFresh public evidence.' }));
  assert.equal(edited.number, first.number);
  assert.equal(f.prs[0].title, `${branch}: updated submission`);
  assert.match(f.prs[0].body, /Fresh public evidence/);
});

test('resume recovers a lost push and a lost PR-create response without duplicates', async t => {
  const f = await fixture(t);
  f.pushFailure = 'after';
  await assert.rejects(publishSubmission(f.input()), /lost push response/);
  const resumed = await publishSubmission(f.input());
  assert.equal(f.prs.length, 1);
  assert.equal(f.remoteHead(`refs/heads/${branch}`), resumed.head);

  const g = await fixture(t);
  g.createFailure = 'after';
  const recovered = await publishSubmission(g.input());
  assert.equal(g.prs.length, 1);
  assert.equal(recovered.number, 1);
  assert.equal((await publishSubmission(g.input())).number, 1);
});

test('publication refuses external branch edits, closed PRs, changed targets, and insufficient access', async t => {
  const f = await fixture(t);
  const first = await publishSubmission(f.input());
  git(f.source, 'push', '--force', 'submission', `${git(f.source, 'rev-parse', 'refs/heads/main')}:refs/heads/${branch}`);
  await assert.rejects(inspectSubmissionTarget({ repo: f.repo, targets, branch, execute: f.execute }), /branch changed|overwrite/i);

  const g = await fixture(t);
  await publishSubmission(g.input());
  g.prs[0].state = 'CLOSED';
  await assert.rejects(inspectSubmissionTarget({ repo: g.repo, targets, branch, execute: g.execute }), /closed|unexpected edits/i);

  const h = await fixture(t);
  await publishSubmission(h.input());
  await assert.rejects(inspectSubmissionTarget({ repo: h.repo, targets: { ...targets, submission: { ...targets.submission, repository: 'course/other' } }, branch, execute: h.execute }), /remote changed/i);

  const i = await fixture(t);
  i.permission = 'READ';
  await assert.rejects(inspectSubmissionTarget({ repo: i.repo, targets, branch, execute: i.execute }), /WRITE|MAINTAIN|ADMIN/i);
  assert.equal(first.isDraft, true);
});

test('unaccounted submission branches are never adopted or overwritten', async t => {
  const f = await fixture(t);
  git(f.source, 'push', 'submission', `HEAD:refs/heads/${branch}`);
  await assert.rejects(inspectSubmissionTarget({ repo: f.repo, targets, branch, execute: f.execute }), /no retained accounting/i);
});

test('invalid branch names are rejected before querying or writing either target', async t => {
  const f = await fixture(t);
  const input = f.input({ branch: 'main' });
  f.calls.length = 0;
  await assert.rejects(publishSubmission(input), /feat\/scope-description/);
  assert.equal(f.calls.length, 0);
});

test('missing submission development never falls back to the existing main branch', async t => {
  const f = await fixture(t);
  git(f.source, 'push', 'submission', '--delete', 'development');
  f.calls.length = 0;
  await assert.rejects(publishSubmission(f.input()), /configured base/);
  assert.equal(f.calls.some(c => c[1] === 'push' || c[1] === 'pr' && ['create', 'edit'].includes(c[2])), false);
});

test('historical main records remain verifiable and target migration refuses to rewrite them', async t => {
  const f = await fixture(t);
  const historical = { ...targets, submission: { ...targets.submission, base: 'main' } };
  const first = await publishSubmission(f.input({ targets: historical }));
  const path = join(f.source, '.agent-work/paired-prs/feat-tooling-example.json');
  const snapshot = await readFile(path, 'utf8');
  assert.equal(first.base, 'main');
  assert.equal((await verifySubmission({ ...f.input({ targets: historical }), sourceHead: first.sourceHead })).head, first.head);
  f.calls.length = 0;
  await assert.rejects(publishSubmission(f.input()), /different targets/);
  assert.equal(f.calls.some(c => c[1] === 'push' || c[1] === 'pr' && ['create', 'edit'].includes(c[2])), false);
  assert.equal(await readFile(path, 'utf8'), snapshot);
});
