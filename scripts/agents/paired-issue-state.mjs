import { createHash } from 'node:crypto';
import { atomicWrite, readJson } from './agent-store.mjs';
import { command, json, sides } from './paired-issue-api.mjs';
import { featureBranch } from './pr-conventions.mjs';

const requiredChecks = [
  'contributor-checks (ubuntu-latest)',
  'contributor-checks (windows-latest)',
];

export function parsePullUrl(url, repositoryName) {
  let parsed;
  try { parsed = new URL(url); }
  catch { throw new Error('Provide the public resolving PR URL for the configured origin repository.'); }
  const match = parsed.pathname.match(/^\/([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)\/pull\/([1-9]\d*)\/?$/i);
  const number = Number(match?.[2]);
  if (parsed.protocol !== 'https:' || parsed.hostname !== 'github.com' || parsed.username || parsed.password || parsed.port || parsed.search || parsed.hash || !match || !Number.isSafeInteger(number) || match[1].toLowerCase() !== repositoryName.toLowerCase()) {
    throw new Error('The public resolving PR URL must match the configured origin repository.');
  }
  return { number, url: `https://github.com/${repositoryName}/pull/${number}` };
}

export function validHash(value) { return typeof value === 'string' && /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/i.test(value); }

export function validPrUrl(value, repositoryName, number) {
  return typeof value === 'string' && value.toLowerCase() === `https://github.com/${repositoryName}/pull/${number}`.toLowerCase();
}

export function readPr(call, repo, repositoryName, number, side, branch, expectedBase) {
  const fields = 'number,url,state,mergedAt,headRefName,headRefOid,baseRefName,isDraft,isCrossRepository';
  const pr = json(call, ['pr', 'view', String(number), '--repo', repositoryName, '--json', fields], repo, `${side} PR`);
  if (pr.number !== number || !validPrUrl(pr.url, repositoryName, number) || pr.isCrossRepository !== false) throw new Error(`The ${side} PR identity is invalid, cross-repository, or changed.`);
  if (pr.headRefName !== branch || pr.baseRefName !== expectedBase || !featureBranch.test(pr.headRefName ?? '') || !validHash(pr.headRefOid)) {
    throw new Error(`The ${side} PR must use the expected feature branch and base.`);
  }
  if (!['OPEN', 'CLOSED', 'MERGED'].includes(pr.state)) throw new Error(`GitHub returned an invalid ${side} PR state.`);
  if (pr.state === 'MERGED' && (typeof pr.mergedAt !== 'string' || !pr.mergedAt.trim())) throw new Error(`The merged ${side} PR has no mergedAt timestamp.`);
  return pr;
}

export function readSubmissionPr(call, repo, target, branch) {
  const listed = json(call, ['pr', 'list', '--repo', target.repository, '--head', branch, '--state', 'all', '--limit', '1000', '--json', 'number,url,baseRefName,headRefName,state'], repo, 'submission PR list');
  if (!Array.isArray(listed)) throw new Error('GitHub returned an invalid submission PR list.');
  if (listed.length > 1) throw new Error('Multiple submission PRs use this feature branch; inspect before completing issues.');
  if (!listed.length) return null;
  const item = listed[0];
  if (!Number.isSafeInteger(item?.number) || item.number < 1 || item.headRefName !== branch || item.baseRefName !== target.base) throw new Error('The submission PR does not use the public feature branch and configured base (historical main requires its original configuration).');
  return readPr(call, repo, target.repository, item.number, 'submission', branch, target.base);
}

export function prIdentity(pr, repositoryName) {
  return { repository: repositoryName, number: pr.number, url: pr.url, branch: pr.headRefName, base: pr.baseRefName };
}

export function completionMarker(publicRepository, key) {
  const digest = createHash('sha256').update(publicRepository.toLowerCase() + '\0' + key).digest('hex');
  return `<!-- paired-issue-completion:sha256:${digest} -->`;
}

export function validateCompletionRecord(record, expected) {
  if (!record || typeof record !== 'object' || Array.isArray(record) || record.schemaVersion !== 1 || record.key !== expected.key || record.issueMarker !== expected.issueMarker || record.completionMarker !== expected.completionMarker) throw new Error('Paired issue completion record has a mismatched stable-key identity.');
  if (JSON.stringify(record.targets) !== JSON.stringify(expected.targets) || JSON.stringify(record.issues) !== JSON.stringify(expected.issues) || JSON.stringify(record.resolvingPr) !== JSON.stringify(expected.resolvingPr)) throw new Error('Paired issue targets, issue identities, or resolving PR changed; inspect the retained completion record.');
  if (!record.progress || sides.some((side) => !record.progress[side] || typeof record.progress[side] !== 'object')) throw new Error('Paired issue completion record has invalid per-side progress.');
  const effectsStarted = record.applyStarted === true || sides.some((side) => ['commentIntent', 'commented', 'closeIntent', 'closed'].some((field) => record.progress[side][field] === true));
  if (record.evidenceSha256 !== expected.evidenceSha256 && effectsStarted) throw new Error('Completion evidence changed after apply intent or an audit effect began.');
  if (record.evidenceSha256 !== expected.evidenceSha256) delete record.verified;
  record.evidenceSha256 = expected.evidenceSha256;
}

export async function loadCompletionRecord(path, expected) {
  try {
    const record = await readJson(path);
    validateCompletionRecord(record, expected);
    return record;
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    return { ...expected, progress: { primary: {}, submission: {} } };
  }
}

export async function saveCompletionRecord(path, record) {
  record.updatedAt = new Date().toISOString();
  await atomicWrite(path, `${JSON.stringify(record, null, 2)}\n`);
}

export function readCheckRuns(call, repo, repositoryName, head) {
  const endpoint = `repos/${repositoryName}/commits/${head}/check-runs?per_page=100`;
  const output = command(call, ['api', '--paginate', '--slurp', '--method', 'GET', endpoint], repo, 60_000);
  let responses;
  try { responses = JSON.parse(output); }
  catch { throw new Error('GitHub returned invalid check-run JSON.'); }
  if (!Array.isArray(responses) || !responses.length || responses.some((page) => !page || typeof page !== 'object' || !Array.isArray(page.check_runs))) throw new Error('Could not confirm complete public check-run pagination.');
  return responses.flatMap((page) => page.check_runs);
}

export function assessChecks(call, repo, repositoryName, head) {
  const checks = readCheckRuns(call, repo, repositoryName, head);
  const latest = requiredChecks.map((name) => checks
    .filter((check) => check?.name === name && check.head_sha?.toLowerCase() === head.toLowerCase() && check.app?.slug === 'github-actions')
    .sort((left, right) => Number(right.id) - Number(left.id))[0]);
  const signatures = latest.map((check) => check ? {
    name: check.name,
    head: check.head_sha,
    status: check.status,
    conclusion: check.conclusion,
    app: check.app.slug,
  } : null);
  if (latest.some((check) => !check || !Number.isSafeInteger(check.id) || check.id < 1)) return { status: 'WAITING_CI', checks: signatures };
  if (latest.some((check) => check.status === 'completed' && check.conclusion !== 'success')) return { status: 'BLOCKED', checks: signatures, reason: 'A required exact-head GitHub Actions check failed.' };
  if (latest.some((check) => check.status !== 'completed' || check.conclusion !== 'success')) return { status: 'WAITING_CI', checks: signatures };
  return { status: 'READY', checks: signatures };
}

export function readCommitTree(call, repo, repositoryName, head) {
  const commit = json(call, ['api', `repos/${repositoryName}/git/commits/${head}`], repo, `${repositoryName} commit tree`);
  if (commit?.sha?.toLowerCase() !== head.toLowerCase() || !validHash(commit?.tree?.sha)) throw new Error(`GitHub returned an invalid commit tree for ${repositoryName}.`);
  return commit.tree.sha.toLowerCase();
}

export function mergedSnapshot(call, repo, targets, publicPr, submissionPr) {
  const checks = assessChecks(call, repo, targets.primary.repository, publicPr.headRefOid);
  if (checks.status !== 'READY') return { ...checks };
  const publicTree = readCommitTree(call, repo, targets.primary.repository, publicPr.headRefOid);
  const submissionTree = readCommitTree(call, repo, targets.submission.repository, submissionPr.headRefOid);
  if (publicTree !== submissionTree) return { status: 'BLOCKED', reason: 'The public and submission PR heads have different Git trees.' };
  return {
    status: 'READY',
    verified: {
      publicHead: publicPr.headRefOid.toLowerCase(),
      submissionHead: submissionPr.headRefOid.toLowerCase(),
      publicTree,
      submissionTree,
      publicMergedAt: publicPr.mergedAt,
      submissionMergedAt: submissionPr.mergedAt,
      checks: checks.checks,
    },
  };
}
