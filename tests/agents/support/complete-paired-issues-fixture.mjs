import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { mkdtemp, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

export const publicRepository = 'example/public';
export const privateRepository = 'course/private';
export const branch = 'feat/tooling-example';
export const publicHead = 'a'.repeat(40);
export const privateHead = 'b'.repeat(40);
export const tree = 'c'.repeat(40);
export const requiredChecks = [
  'contributor-checks (ubuntu-latest)',
  'contributor-checks (windows-latest)',
  'runtime-checks (ubuntu-latest)',
  'runtime-checks (windows-latest)',
];

function git(cwd, ...args) {
  const result = spawnSync('git', args, { cwd, encoding: 'utf8', windowsHide: true });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, result.stderr || `git ${args.join(' ')} failed`);
}

export function markerFor(key) {
  const digest = createHash('sha256').update(publicRepository.toLowerCase() + '\0' + key).digest('hex');
  return `<!-- paired-issue:sha256:${digest} -->`;
}

export async function fixture(t, options = {}) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'complete-paired-issues-')));
  t.after(() => rm(root, { recursive: true, force: true }));
  git(root, 'init', '--initial-branch=main');
  await writeFile(join(root, 'publication-targets.json'), JSON.stringify({
    schemaVersion: 1,
    submission: { remote: 'submission', base: 'development' },
  }));
  const key = 'localized-bug';
  const publicIssue = {
    number: 11,
    html_url: `https://github.com/${publicRepository}/issues/11`,
    body: `Request.\n${markerFor(key)}`,
    state: 'open',
    comments: [],
  };
  const privateIssue = {
    number: 23,
    html_url: `https://github.com/${privateRepository}/issues/23`,
    body: `Request.\n${markerFor(key)}`,
    state: 'open',
    comments: [],
  };
  const prs = {
    primary: {
      number: 7,
      url: `https://github.com/${publicRepository}/pull/7`,
      state: 'OPEN',
      mergedAt: null,
      headRefName: branch,
      headRefOid: publicHead,
      baseRefName: 'development',
      isDraft: false,
      isCrossRepository: false,
    },
    submission: {
      number: 9,
      url: `https://github.com/${privateRepository}/pull/9`,
      state: 'OPEN',
      mergedAt: null,
      headRefName: branch,
      headRefOid: privateHead,
      baseRefName: 'development',
      isDraft: false,
      isCrossRepository: false,
    },
  };
  const repositories = {
    [publicRepository]: {
      metadata: { nameWithOwner: publicRepository, visibility: 'PUBLIC', viewerPermission: 'WRITE', hasIssuesEnabled: true },
      issues: [publicIssue],
      pr: prs.primary,
    },
    [privateRepository]: {
      metadata: { nameWithOwner: privateRepository, visibility: 'PRIVATE', viewerPermission: 'WRITE', hasIssuesEnabled: true },
      issues: [privateIssue],
      pr: prs.submission,
    },
  };
  const checks = requiredChecks.map((name, id) => ({
    id: id + 1,
    name,
    head_sha: publicHead,
    status: 'completed',
    conclusion: 'success',
    app: { slug: 'github-actions' },
  }));
  const writes = [];
  const remoteTargets = { submission: privateRepository };
  const extraSubmissionPRs = options.extraSubmissionPRs ?? [];
  let loseCloseResponse = options.loseCloseResponse !== false;
  let loseCommentResponse = options.loseCommentResponse ?? null;
  let checkReadCount = 0;
  let changePrivateIssueAfterPublicClose = options.changePrivateIssueAfterPublicClose === true;
  const execute = (binary, args, cwd, timeout) => {
    assert.equal(typeof timeout, 'number');
    if (binary === 'git') return args[2] === 'origin' ? `https://github.com/${publicRepository}.git` : `https://github.com/${remoteTargets.submission}.git`;
    assert.equal(binary, 'gh');
    if (args[0] === 'repo' && args[1] === 'view') return JSON.stringify({ ...repositories[args[2]].metadata, ...(options.metadata?.[args[2]] ?? {}) });
    if (args[0] === 'pr' && args[1] === 'view') {
      const repositoryName = args[args.indexOf('--repo') + 1];
      const pr = repositories[repositoryName].pr;
      assert.equal(Number(args[2]), pr.number);
      return JSON.stringify(pr);
    }
    if (args[0] === 'pr' && args[1] === 'list') {
      assert.equal(args[args.indexOf('--repo') + 1], remoteTargets.submission);
      assert.equal(args[args.indexOf('--state') + 1], 'all');
      assert.equal(args[args.indexOf('--limit') + 1], '1000');
      const pr = repositories[remoteTargets.submission].pr;
      const listed = { number: pr.number, url: pr.url, baseRefName: pr.baseRefName, headRefName: pr.headRefName, state: pr.state };
      return JSON.stringify([listed, ...extraSubmissionPRs]);
    }
    if (args[0] === 'api' && args.includes('--paginate')) {
      const endpoint = args.at(-1);
      const issues = endpoint.match(/^repos\/([^/]+\/[^/]+)\/issues\?state=all&per_page=100$/);
      if (issues) return JSON.stringify([repositories[issues[1]].issues.map(({ comments, ...issue }) => ({ ...issue }))]);
      const comments = endpoint.match(/^repos\/([^/]+\/[^/]+)\/issues\/(\d+)\/comments\?per_page=100$/);
      if (comments) {
        const issue = repositories[comments[1]].issues.find(item => item.number === Number(comments[2]));
        return JSON.stringify([issue.comments.map(body => ({ body }))]);
      }
      const checkRuns = endpoint.match(/^repos\/([^/]+\/[^/]+)\/commits\/([^/]+)\/check-runs\?per_page=100$/);
      if (checkRuns) {
        checkReadCount++;
        if (options.changeIssueBodyAtCheck === checkReadCount) publicIssue.body = `Changed acceptance criteria.\n${markerFor(key)}`;
        const head = repositories[publicRepository].pr.headRefOid;
        return JSON.stringify([{ check_runs: checkRuns[2] === head ? checks : [] }]);
      }
      throw new Error(`unexpected paginated endpoint: ${endpoint}`);
    }
    if (args[0] === 'api' && args[1]?.startsWith('repos/')) {
      const commit = args[1].match(/^repos\/([^/]+\/[^/]+)\/git\/commits\/([^/]+)$/);
      if (commit) return JSON.stringify({ sha: commit[2], tree: { sha: commit[1] === privateRepository && options.treeMismatch ? 'd'.repeat(40) : tree } });
    }
    if (args[0] === 'issue' && args[1] === 'comment') {
      const repositoryName = args[args.indexOf('--repo') + 1];
      const issue = repositories[repositoryName].issues.find(item => item.number === Number(args[2]));
      const body = readFileSync(args[args.indexOf('--body-file') + 1], 'utf8');
      issue.comments.push(body);
      writes.push({ kind: 'comment', repository: repositoryName, body });
      if (repositoryName === publicRepository && options.changePrivateIssueAfterPublicComment) {
        privateIssue.body = `Changed criteria after first audit comment.\n${markerFor(key)}`;
      }
      if (repositoryName === loseCommentResponse) {
        loseCommentResponse = null;
        throw new Error('simulated lost comment response');
      }
      return '';
    }
    if (args[0] === 'issue' && args[1] === 'close') {
      const repositoryName = args[args.indexOf('--repo') + 1];
      const issue = repositories[repositoryName].issues.find(item => item.number === Number(args[2]));
      issue.state = 'closed';
      writes.push({ kind: 'close', repository: repositoryName, number: issue.number });
      if (repositoryName === publicRepository && changePrivateIssueAfterPublicClose) {
        changePrivateIssueAfterPublicClose = false;
        privateIssue.body = `Changed acceptance criteria after public close.\n${markerFor(key)}`;
      }
      if (repositoryName === privateRepository && loseCloseResponse) {
        loseCloseResponse = false;
        throw new Error('simulated lost close response');
      }
      return '';
    }
    throw new Error(`unexpected GitHub command: ${args.join(' ')}`);
  };
  const evidenceFile = join(root, 'evidence.json');
  await writeFile(evidenceFile, JSON.stringify({
    schemaVersion: 1,
    summary: 'Verified the requested repair.',
    acceptance: [{ criterion: 'The localized display is correct.', evidence: 'Focused verification passed.' }],
  }));
  const args = ['--key', key, '--pr', prs.primary.url, '--evidence-file', evidenceFile, '--root', root];
  return { root, args, evidenceFile, execute, repositories, prs, writes, checks, publicIssue, privateIssue, remoteTargets, extraSubmissionPRs };
}

export function mergePair(f) {
  for (const pr of Object.values(f.prs)) {
    pr.state = 'MERGED';
    pr.mergedAt = '2026-10-16T12:00:00Z';
  }
}

export function completionMarkerFor(key) {
  const digest = createHash('sha256').update(publicRepository.toLowerCase() + '\0' + key).digest('hex');
  return `<!-- paired-issue-completion:sha256:${digest} -->`;
}
