import { createHash } from 'node:crypto';
import { withPublicationBody } from './publication-targets.mjs';
import { command, pages, sides } from './paired-issue-api.mjs';
import { hasLine, privateIdentityAppears } from './paired-issue-resolution.mjs';

export function commentBody(pr, evidence, marker) {
  return [
    `Completed with [PR #${pr.number}](${pr.url}).`,
    '',
    `Acceptance criteria attested: ${evidence.acceptance.length}.`,
    `Evidence SHA-256: ${createHash('sha256').update(JSON.stringify(evidence)).digest('hex')}`,
    'Detailed evidence is retained locally by the completing agent.',
    '',
    marker,
  ].join('\n');
}

export function readIssueComments(call, repo, target, issue) {
  const endpoint = `repos/${target.repository}/issues/${issue.number}/comments?per_page=100`;
  return pages(command(call, ['api', '--paginate', '--slurp', '--method', 'GET', endpoint], repo, 60_000), `${target.repository} issue comment`);
}

export function existingCompletionComment(comments, marker, body, side) {
  const completionComments = comments.filter((comment) => typeof comment?.body === 'string' && /<!-- paired-issue-completion:[^>]+ -->/.test(comment.body));
  const matching = completionComments.filter((comment) => hasLine(comment.body, marker));
  if (matching.length > 1 || completionComments.length > matching.length) throw new Error(`Conflicting completion markers exist on the ${side} issue.`);
  if (!matching.length) return false;
  const normalize = (value) => value.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  if (normalize(matching[0].body) !== normalize(body)) throw new Error(`A completion marker on the ${side} issue has conflicting evidence.`);
  return true;
}

export function sameVerifiedSnapshot(previous, current) {
  return JSON.stringify(previous) === JSON.stringify(current);
}

export async function postComment(repo, call, target, issue, body) {
  const args = ['issue', 'comment', String(issue.number), '--repo', target.repository, '--body-file'];
  return withPublicationBody(repo, body, (path) => command(call, [...args, path], repo));
}

export function issueCommentsState(call, repo, targets, current, evidence, record) {
  const bodies = {
    primary: commentBody(current.publicPr, evidence, record.completionMarker),
    submission: commentBody(current.submissionPr, evidence, record.completionMarker),
  };
  for (const side of sides) {
    if (Buffer.byteLength(bodies[side], 'utf8') > 65_536) throw new Error(`The ${side} completion comment exceeds 65536 bytes.`);
    if (side === 'primary' && privateIdentityAppears(bodies[side], targets.submission.repository)) throw new Error('Public completion comments must not include the private repository identity.');
  }
  const comments = {};
  for (const side of sides) {
    const listed = readIssueComments(call, repo, targets[side], current.pair.issues[side]);
    comments[side] = existingCompletionComment(listed, record.completionMarker, bodies[side], side);
    if (record.progress[side].commented === true && !comments[side]) throw new Error(`The recorded ${side} completion comment is missing.`);
    if (comments[side]) {
      record.progress[side].commented = true;
      record.progress[side].commentIntent = false;
    }
    if (current.pair.issues[side].state === 'closed') {
      record.progress[side].closed = true;
      record.progress[side].closeIntent = false;
    }
  }
  return { bodies, comments };
}
