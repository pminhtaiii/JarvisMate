import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { dataDirectory, readJson } from './agent-store.mjs';
import { command, pages, sides } from './paired-issue-api.mjs';

export function issueMarker(repositoryName, key) {
  const digest = createHash('sha256').update(repositoryName.toLowerCase() + '\0' + key).digest('hex');
  return `<!-- paired-issue:sha256:${digest} -->`;
}

export function hasLine(text, marker) {
  return typeof text === 'string' && text.split(/\r\n|\n|\r/).includes(marker);
}

export function privateIdentityAppears(text, repositoryName) {
  const normalized = String(text).toLowerCase();
  return normalized.includes(repositoryName.toLowerCase()) || normalized.includes(encodeURIComponent(repositoryName).toLowerCase());
}

export function validateTarget(side, target, metadata) {
  const expectedVisibility = side === 'primary' ? 'PUBLIC' : 'PRIVATE';
  if (!metadata || typeof metadata !== 'object' || metadata.nameWithOwner?.toLowerCase() !== target.repository.toLowerCase()) throw new Error(`GitHub repository identity does not match the configured ${side} target.`);
  if (metadata.visibility !== expectedVisibility) throw new Error(`The ${side} repository must be ${expectedVisibility.toLowerCase()}.`);
  if (!['WRITE', 'MAINTAIN', 'ADMIN'].includes(metadata.viewerPermission)) throw new Error(`Write permission is required for the ${side} repository.`);
  if (metadata.hasIssuesEnabled !== true) throw new Error(`Issues must be enabled for the ${side} repository.`);
}

export function issueUrl(repositoryName, issue) {
  if (!Number.isSafeInteger(issue?.number) || issue.number < 1 || typeof issue.html_url !== 'string') throw new Error('A marker-matched issue has an invalid identity.');
  let parsed;
  try { parsed = new URL(issue.html_url); }
  catch { throw new Error('A marker-matched issue has an invalid URL.'); }
  const expectedPath = `/${repositoryName}/issues/${issue.number}`;
  if (parsed.protocol !== 'https:' || parsed.hostname !== 'github.com' || parsed.pathname.toLowerCase() !== expectedPath.toLowerCase() || parsed.search || parsed.hash || !['open', 'closed'].includes(String(issue.state).toLowerCase())) {
    throw new Error('A marker-matched issue belongs to a different identity or has an invalid state.');
  }
  const body = typeof issue.body === 'string' ? issue.body.replace(/\r\n/g, '\n').replace(/\r/g, '\n') : '';
  return {
    number: issue.number,
    url: `https://github.com/${repositoryName}/issues/${issue.number}`,
    state: String(issue.state).toLowerCase(),
    bodySha256: createHash('sha256').update(body).digest('hex'),
  };
}

export function listIssues(call, repo, target) {
  const endpoint = `repos/${target.repository}/issues?state=all&per_page=100`;
  return pages(command(call, ['api', '--paginate', '--slurp', '--method', 'GET', endpoint], repo, 60_000), `${target.repository} issue`);
}

export function findIssue(call, repo, target, marker) {
  const matches = listIssues(call, repo, target).filter((issue) => hasLine(issue.body, marker));
  if (matches.some((issue) => issue.pull_request)) throw new Error(`The stable marker belongs to a pull request in the ${target.remote} repository.`);
  if (matches.length > 1) throw new Error(`Multiple issues contain the stable marker in the ${target.remote} repository.`);
  return matches[0] ? issueUrl(target.repository, matches[0]) : null;
}

export function validateIssueRecord(record, key, marker, targets, found) {
  if (!record || typeof record !== 'object' || Array.isArray(record) || record.schemaVersion !== 1 || record.key !== key || record.marker !== marker) throw new Error('Paired issue record has a mismatched stable-key identity.');
  if (!record.targets || sides.some((side) => typeof record.targets[side] !== 'string' || record.targets[side].toLowerCase() !== targets[side].repository.toLowerCase())) throw new Error('Paired issue targets changed; restore their configuration or reconcile the retained record.');
  if (!record.receipts || sides.some((side) => !Object.hasOwn(record.receipts, side))) throw new Error('Paired issue record has invalid receipts.');
  for (const side of sides) {
    const receipt = record.receipts[side];
    if (!receipt) continue;
    if (!found[side] || receipt.number !== found[side].number || typeof receipt.url !== 'string' || receipt.url.toLowerCase() !== found[side].url.toLowerCase()) throw new Error(`The saved ${side} issue receipt no longer matches its stable marker.`);
  }
}

export async function resolveIssuePair(call, repo, values, targets) {
  const marker = issueMarker(targets.primary.repository, values.key);
  const directory = await dataDirectory(repo, 'paired-issues');
  const recordPath = resolve(directory, `${values.key}.json`);
  let existing;
  try { existing = await readJson(recordPath); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const found = Object.fromEntries(sides.map((side) => [side, findIssue(call, repo, targets[side], marker)]));
  if (existing) validateIssueRecord(existing, values.key, marker, targets, found);
  if (sides.some((side) => !found[side])) throw new Error('Could not find both issues by their stable marker; markerless issues are never adopted.');
  return { marker, issues: found };
}
