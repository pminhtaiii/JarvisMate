import { featureBranch as featureName } from './pr-conventions.mjs';
const checksRequired = ['contributor-checks (ubuntu-latest)', 'contributor-checks (windows-latest)'];
export { featureName };
export function validSummary(value) {
  return typeof value === 'string' && value.length > 0 && value.length <= 80 && value === value.trim() && !/[\r\n]/.test(value);
}

export function assess({ head, pr, checks }) {
  const result = { status: 'WAITING_CI', failedChecks: [], unresolved: [] };
  const titlePrefix = `${pr.headRefName}: `;
  if (pr.state !== 'OPEN' || pr.headRefOid !== head || !featureName.test(pr.headRefName) || !pr.title.startsWith(titlePrefix) || !validSummary(pr.title.slice(titlePrefix.length)) || pr.baseRefName !== 'development') return { ...result, status: 'BLOCKED', reason: 'PR identity, title, base, state, or current HEAD does not match.' };
  if (pr.reviews.pageInfo.hasPreviousPage || pr.reviewThreads.pageInfo.hasNextPage) return { ...result, status: 'BLOCKED', reason: 'Review data exceeds the bounded page; inspect manually.' };
  result.unresolved = pr.reviewThreads.nodes.filter((thread) => !thread.isResolved);
  if (pr.mergeable === 'CONFLICTING' || pr.mergeStateStatus === 'BEHIND') return { ...result, status: 'BLOCKED', reason: 'Update the feature branch against development and rerun verification.' };
  const latest = checksRequired.map((name) => checks.filter((check) => check.name === name && check.head_sha === head && check.app?.slug === 'github-actions').sort((a, b) => b.id - a.id)[0]);
  result.failedChecks = latest.filter((check) => check?.status === 'completed' && check.conclusion !== 'success').map((check) => ({ name: check.name, conclusion: check.conclusion, url: check.details_url }));
  if (result.failedChecks.length) result.status = 'NEEDS_FIX';
  else if (pr.mergeable === 'UNKNOWN' || latest.some((check) => !check || check.status !== 'completed')) result.status = 'WAITING_CI';
  else if (pr.mergeStateStatus === 'BLOCKED' && pr.isDraft === false) return { ...result, status: 'BLOCKED', reason: 'GitHub reports an unmet merge requirement.' };
  else result.status = pr.isDraft === false ? 'AWAITING_HUMAN_MERGE' : 'READY_FOR_HUMAN';
  return result;
}

export function changedLines(numstat) {
  let reviewable = 0, generated = 0, binaries = 0;
  for (const line of numstat.trim().split('\n').filter(Boolean)) {
    const [added, removed, ...path] = line.split('\t');
    if (added === '-' || removed === '-') { binaries++; continue; }
    const size = Number(added) + Number(removed);
    if (/(^|\/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock)$/.test(path.join('\t'))) generated += size;
    else reviewable += size;
  }
  return { reviewable, generated, binaries, overTarget: reviewable + generated > 1000 };
}

export function workflowSummary(record) {
  if (record.usage || !record.schemaVersion) return record;
  const unresolved = (record.observation?.unresolved ?? []).map(thread => ({ id: thread.id, isOutdated: thread.isOutdated, urls: thread.comments?.nodes.map(comment => comment.url) ?? [] }));
  const logs = Object.fromEntries(Object.entries(record.gateLogs ?? {}).map(([name, gate]) => [name, { status: gate.status, exitCode: gate.exitCode, log: gate.log, durationMs: gate.durationMs }]));
  return { status: record.status, branch: record.branch, head: record.head ?? record.publishedHead, pr: record.pr, url: record.url, submission: record.submission, size: record.size, reason: record.reason ?? record.observation?.reason, repairRounds: record.repairRounds.length, failedChecks: record.observation?.failedChecks ?? [], unresolved, logs, localVerifiedHead: record.localVerification?.head };
}
