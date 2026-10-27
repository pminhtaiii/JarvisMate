import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dataDirectory, readJson, repository, withLock } from './agent-store.mjs';
import { publicationTargets } from './publication-targets.mjs';
import { command, json, sides } from './paired-issue-api.mjs';
import { privateIdentityAppears, resolveIssuePair, validateTarget } from './paired-issue-resolution.mjs';
import { completionMarker, loadCompletionRecord, mergedSnapshot, parsePullUrl, prIdentity, readSubmissionPr, saveCompletionRecord, validateCompletionRecord, validHash, validPrUrl } from './paired-issue-state.mjs';
import { issueCommentsState, postComment, sameVerifiedSnapshot } from './paired-issue-comments.mjs';
import { featureBranch } from './pr-conventions.mjs';
const usage = 'Usage: node scripts/agents/complete-paired-issues.mjs --key <stable-key> --pr <public-PR-URL> --evidence-file <JSON> [--apply] [--root <checkout>]';
const defaultRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

export function execute(binary, args, cwd, timeout = 30_000) {
  const result = spawnSync(binary, args, { cwd, encoding: 'utf8', windowsHide: true, timeout, maxBuffer: 64 * 1024 * 1024 });
  if (result.error || result.status !== 0) throw new Error(result.error?.message || result.stderr || result.stdout || `${binary} failed (${result.status})`);
  return result.stdout.trim();
}

export function parseArgs(args) {
  if (args.length === 1 && ['--help', '-h'].includes(args[0])) return { help: true };
  const values = { apply: false };
  const valued = new Set(['key', 'pr', 'evidence-file', 'root']);
  for (let index = 0; index < args.length;) {
    const option = args[index++];
    if (option === '--apply') {
      if (values.apply) throw new Error(usage);
      values.apply = true;
      continue;
    }
    const name = option?.slice(2);
    const value = args[index++];
    if (!option?.startsWith('--') || !valued.has(name) || Object.hasOwn(values, name) || !value || value.startsWith('--')) throw new Error(usage);
    values[name] = value;
  }
  if (!values.key || !values.pr || !values['evidence-file']) throw new Error(usage);
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(values.key) || values.key.length > 80) throw new Error('Provide --key as a lowercase stable slug of at most 80 characters.');
  return values;
}

export async function readEvidence(path) {
  const bytes = await readFile(resolve(path));
  if (bytes.length > 65_536) throw new Error('Evidence file exceeds 65536 bytes.');
  let text;
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
  catch { throw new Error('Evidence file must contain valid UTF-8.'); }
  if (text.includes('\0')) throw new Error('Evidence file must not contain NUL characters.');
  let input;
  try { input = JSON.parse(text); }
  catch { throw new Error('Evidence file must contain valid JSON.'); }
  if (!input || typeof input !== 'object' || Array.isArray(input) || input.schemaVersion !== 1 || typeof input.summary !== 'string' || !input.summary.trim() || !Array.isArray(input.acceptance) || !input.acceptance.length) {
    throw new Error('Evidence must use schemaVersion 1 with a nonblank summary and at least one acceptance entry.');
  }
  const acceptance = input.acceptance.map((entry) => {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry) || typeof entry.criterion !== 'string' || !entry.criterion.trim() || typeof entry.evidence !== 'string' || !entry.evidence.trim()) {
      throw new Error('Each acceptance entry needs nonblank criterion and evidence text.');
    }
    return { criterion: entry.criterion.trim(), evidence: entry.evidence.trim() };
  });
  const evidence = { schemaVersion: 1, summary: input.summary.trim(), acceptance };
  if ([evidence.summary, ...acceptance.flatMap((item) => [item.criterion, item.evidence])].some((value) => value.includes('\0'))) throw new Error('Evidence text must not contain NUL characters.');
  return { evidence, source: text, decoded: JSON.stringify(input), sha256: createHash('sha256').update(JSON.stringify(evidence)).digest('hex') };
}

export function expectedRecord(values, pair, targets, publicPr, submissionPr, evidenceInput) {
  return {
    schemaVersion: 1,
    key: values.key,
    issueMarker: pair.marker,
    completionMarker: completionMarker(targets.primary.repository, values.key),
    targets: { primary: targets.primary.repository, submission: targets.submission.repository },
    issues: Object.fromEntries(sides.map((side) => [side, { number: pair.issues[side].number, url: pair.issues[side].url }])),
    resolvingPr: {
      primary: prIdentity(publicPr, targets.primary.repository),
      submission: prIdentity(submissionPr, targets.submission.repository),
    },
    evidenceSha256: evidenceInput.sha256,
  };
}

export async function inspectCurrent(values, evidenceInput, repo, call, targets, recordPath) {
  if ([evidenceInput.source, evidenceInput.decoded, JSON.stringify(evidenceInput.evidence)].some((text) => privateIdentityAppears(text, targets.submission.repository))) {
    throw new Error('Evidence must not include the private repository identity.');
  }
  for (const side of sides) {
    const metadata = json(call, ['repo', 'view', targets[side].repository, '--json', 'nameWithOwner,visibility,viewerPermission,hasIssuesEnabled'], repo, `${side} repository`);
    validateTarget(side, targets[side], metadata);
  }
  const pair = await resolveIssuePair(call, repo, values, targets);
  const publicUrl = parsePullUrl(values.pr, targets.primary.repository);
  const fields = 'number,url,state,mergedAt,headRefName,headRefOid,baseRefName,isDraft,isCrossRepository';
  const publicPr = json(call, ['pr', 'view', String(publicUrl.number), '--repo', targets.primary.repository, '--json', fields], repo, 'public PR');
  if (publicPr.number !== publicUrl.number || !validPrUrl(publicPr.url, targets.primary.repository, publicUrl.number) || publicPr.isCrossRepository !== false) throw new Error('The public PR identity is invalid, cross-repository, or changed.');
  if (!featureBranch.test(publicPr.headRefName ?? '') || publicPr.baseRefName !== 'development' || !validHash(publicPr.headRefOid)) throw new Error('The public PR must use a feat/scope-description branch (or historical numbered name) and development base.');
  if (!['OPEN', 'CLOSED', 'MERGED'].includes(publicPr.state)) throw new Error('GitHub returned an invalid public PR state.');
  if (publicPr.state === 'MERGED' && (typeof publicPr.mergedAt !== 'string' || !publicPr.mergedAt.trim())) throw new Error('The merged public PR has no mergedAt timestamp.');
  const submissionPr = readSubmissionPr(call, repo, targets.submission, publicPr.headRefName);
  if (!submissionPr) {
    try {
      await readJson(recordPath);
      throw new Error('The retained submission PR is missing or was replaced.');
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    return { status: 'WAITING_SUBMISSION_PR', pair, publicUrl, publicPr, submissionPr: null };
  }
  const expected = expectedRecord(values, pair, targets, publicPr, submissionPr, evidenceInput);
  if (publicPr.state === 'CLOSED' || submissionPr.state === 'CLOSED') return { status: 'BLOCKED', reason: 'A resolving PR closed without merging.', pair, publicUrl, publicPr, submissionPr, expected };
  if (publicPr.state !== 'MERGED' || submissionPr.state !== 'MERGED') return { status: 'WAITING_PR', pair, publicUrl, publicPr, submissionPr, expected };
  const merged = mergedSnapshot(call, repo, targets, publicPr, submissionPr);
  if (merged.verified) merged.verified.issueBodies = Object.fromEntries(sides.map((side) => [side, pair.issues[side].bodySha256]));
  return { ...merged, pair, publicUrl, publicPr, submissionPr, expected };
}

export function snapshotMatches(record, verified) {
  if (record.verified && !sameVerifiedSnapshot(record.verified, verified)) throw new Error('The merged PR heads, merge state, source trees, or exact-head CI evidence changed after preview.');
}

export async function runIssueCompletion(args, dependencies = {}) {
  const values = parseArgs(args);
  if (values.help) return { usage };
  const evidenceInput = await readEvidence(values['evidence-file']);
  const repo = await repository(values.root ?? defaultRoot);
  const call = (binary, argv, cwd, timeout) => (dependencies.execute ?? execute)(binary, argv, cwd, timeout);
  const targets = await publicationTargets(repo, call);
  if (!targets) throw new Error('Paired issue completion requires publication-targets.json.');
  const keyDirectory = await dataDirectory(repo, 'paired-issue-completion');
  const recordPath = resolve(keyDirectory, `${values.key}.json`);
  const lockPath = resolve(keyDirectory, `${values.key}.lock`);

  return withLock(lockPath, async () => {
    let current = await inspectCurrent(values, evidenceInput, repo, call, targets, recordPath);
    if (!current.expected) return { status: current.status, key: values.key, public: current.publicUrl.url };
    let record = await loadCompletionRecord(recordPath, current.expected);

    if (current.status !== 'READY') {
      await saveCompletionRecord(recordPath, record);
      return { status: current.status, key: values.key, reason: current.reason };
    }

    snapshotMatches(record, current.verified);
    const { comments } = issueCommentsState(call, repo, targets, current, evidenceInput.evidence, record);
    for (const side of sides) {
      if (comments[side]) record.progress[side].commented = true;
      if (current.pair.issues[side].state === 'closed') record.progress[side].closed = true;
    }

    if (!values.apply) {
      record.verified = current.verified;
      await saveCompletionRecord(recordPath, record);
      const closed = sides.every((side) => current.pair.issues[side].state === 'closed');
      return { status: closed ? 'COMPLETED' : 'READY_TO_COMPLETE', key: values.key, public: current.publicPr.url, submission: current.submissionPr.url };
    }

    if (sides.every((side) => current.pair.issues[side].state === 'closed')) {
      record.verified = current.verified;
      for (const side of sides) record.progress[side].closed = true;
      await saveCompletionRecord(recordPath, record);
      return { status: 'COMPLETED', key: values.key, public: current.publicPr.url, submission: current.submissionPr.url };
    }

    // Recheck the whole admission snapshot after local body preparation and before the first issue write.
    const beforeComments = await inspectCurrent(values, evidenceInput, repo, call, targets, recordPath);
    if (beforeComments.status !== 'READY') throw new Error('PR, CI, tree, or issue evidence changed before completion comments could be added.');
    validateCompletionRecord(record, beforeComments.expected);
    if (!sameVerifiedSnapshot(current.verified, beforeComments.verified)) throw new Error('PR, CI, tree, or issue evidence changed before completion comments could be added.');
    current = beforeComments;

    record.applyStarted = true;
    record.verified = current.verified;
    await saveCompletionRecord(recordPath, record);
    for (const side of sides) {
      const beforeComment = await inspectCurrent(values, evidenceInput, repo, call, targets, recordPath);
      if (beforeComment.status !== 'READY' || !sameVerifiedSnapshot(record.verified, beforeComment.verified)) throw new Error('PR, CI, tree, or issue evidence changed before completion comments could be added.');
      validateCompletionRecord(record, beforeComment.expected);
      current = beforeComment;
      const { bodies, comments } = issueCommentsState(call, repo, targets, current, evidenceInput.evidence, record);
      if (current.pair.issues[side].state === 'closed') {
        record.progress[side].closed = true;
        await saveCompletionRecord(recordPath, record);
        continue;
      }
      if (comments[side]) {
        record.progress[side].commented = true;
        await saveCompletionRecord(recordPath, record);
        continue;
      }
      record.progress[side].commentIntent = true;
      record.progress[side].commentBodySha256 = createHash('sha256').update(bodies[side]).digest('hex');
      await saveCompletionRecord(recordPath, record);
      await postComment(repo, call, targets[side], current.pair.issues[side], bodies[side]);
      record.progress[side].commentIntent = false;
      record.progress[side].commented = true;
      await saveCompletionRecord(recordPath, record);
    }

    for (const side of sides) {
      // Recheck both repositories before each close; a close may itself race with edits on the other issue.
      const beforeClose = await inspectCurrent(values, evidenceInput, repo, call, targets, recordPath);
      if (beforeClose.status !== 'READY') throw new Error('PR, CI, tree, or issue evidence changed before issue closure.');
      validateCompletionRecord(record, beforeClose.expected);
      snapshotMatches(record, beforeClose.verified);
      const closeComments = issueCommentsState(call, repo, targets, beforeClose, evidenceInput.evidence, record);
      if (beforeClose.pair.issues[side].state === 'closed') {
        record.progress[side].closed = true;
        await saveCompletionRecord(recordPath, record);
        continue;
      }
      if (!closeComments.comments[side]) throw new Error(`The ${side} audit comment is missing before issue closure.`);
      record.progress[side].closeIntent = true;
      await saveCompletionRecord(recordPath, record);
      command(call, ['issue', 'close', String(beforeClose.pair.issues[side].number), '--repo', targets[side].repository, '--reason', 'completed'], repo);
      record.progress[side].closeIntent = false;
      record.progress[side].closed = true;
      await saveCompletionRecord(recordPath, record);
    }

    const finalPair = await resolveIssuePair(call, repo, values, targets);
    if (sides.some((side) => finalPair.issues[side].number !== current.pair.issues[side].number || finalPair.issues[side].url !== current.pair.issues[side].url || finalPair.issues[side].bodySha256 !== current.pair.issues[side].bodySha256 || finalPair.issues[side].state !== 'closed')) {
      throw new Error('GitHub did not close both exact paired issues; rerun completion to recover.');
    }
    for (const side of sides) record.progress[side].closed = true;
    await saveCompletionRecord(recordPath, record);
    return { status: 'COMPLETED', key: values.key, public: current.publicPr.url, submission: current.submissionPr.url };
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runIssueCompletion(process.argv.slice(2)).then((result) => {
    console.log(result.usage ?? JSON.stringify(result, null, 2));
  }).catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
