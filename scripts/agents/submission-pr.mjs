import { randomUUID } from 'node:crypto';
import { atomicWrite, withLock } from './agent-store.mjs';
import { githubRepository, withPublicationBody } from './publication-targets.mjs';
import { assertBranch, normalizeTargets, readRecord } from './submission-pr-shared.mjs';
const gitHash = /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/i;
const writablePermissions = new Set(['WRITE', 'MAINTAIN', 'ADMIN']);

function command(execute, binary, args, repo) {
  const result = execute(binary, args, repo.root, 30_000);
  return typeof result === 'string' ? result.trim() : String(result?.stdout ?? '').trim();
}

function git(execute, repo, ...args) { return command(execute, 'git', args, repo); }

function ghJson(execute, repo, ...args) {
  try { return JSON.parse(command(execute, 'gh', args, repo)); }
  catch (error) { throw new Error(`Could not read submission publication state: ${error.message}`, { cause: error }); }
}

function parseRef(output, reference) {
  const lines = output.split(/\r?\n/).filter(Boolean);
  if (!lines.length) return null;
  if (lines.length !== 1) throw new Error(`Remote reference ${reference} is ambiguous; inspect it before publishing.`);
  const [sha, ref] = lines[0].split(/\s+/);
  if (ref !== reference || !gitHash.test(sha ?? '')) throw new Error(`Remote reference ${reference} has an invalid value.`);
  return sha.toLowerCase();
}

function repoAccess(execute, repo, repository, expectedVisibility) {
  const info = ghJson(execute, repo, 'repo', 'view', repository, '--json', 'visibility,isPrivate,viewerPermission');
  const permission = String(info.viewerPermission ?? '').toUpperCase();
  const visibility = String(info.visibility ?? '').toUpperCase();
  const privateValue = typeof info.isPrivate === 'boolean' ? info.isPrivate : visibility === 'PRIVATE' ? true : visibility === 'PUBLIC' ? false : undefined;
  if (privateValue !== expectedVisibility || visibility && visibility !== (expectedVisibility ? 'PRIVATE' : 'PUBLIC') || !writablePermissions.has(permission)) {
    throw new Error(`${repository} must be ${expectedVisibility ? 'private' : 'public'} and grant WRITE, MAINTAIN, or ADMIN access.`);
  }
}

function assertRecord(record, targets, branch) {
  if (record.schemaVersion !== 1 || record.branch !== branch || record.base !== targets.submission.base || JSON.stringify(record.targets) !== JSON.stringify(targets) || !gitHash.test(record.mainBase ?? '') || !gitHash.test(record.sourceHead ?? '') || !gitHash.test(record.sourceTree ?? '') || record.mirrorHead !== null && !gitHash.test(record.mirrorHead ?? '') || record.previousMirrorHead !== null && !gitHash.test(record.previousMirrorHead ?? '') || typeof record.marker !== 'string' || !record.marker.startsWith('<!-- paired-submission:') || !['branch-pending', 'pr-pending', 'complete'].includes(record.phase)) {
    throw new Error('Submission publication record is invalid or belongs to different targets; inspect before publishing.');
  }
}

function privatePullRequests(execute, repo, repository, branch) {
  const listed = ghJson(execute, repo, 'pr', 'list', '--repo', repository, '--head', branch, '--state', 'all', '--limit', '1000', '--json', 'number,url,baseRefName,headRefName,state');
  if (!Array.isArray(listed)) throw new Error('GitHub returned an invalid submission PR list.');
  if (listed.length > 1) throw new Error('Multiple submission PRs use this feature branch; inspect before publishing.');
  if (!listed.length) return [];
  const number = listed[0]?.number;
  if (!Number.isInteger(number) || number < 1) throw new Error('GitHub returned an invalid submission PR identity.');
  const pr = ghJson(execute, repo, 'pr', 'view', String(number), '--repo', repository, '--json', 'number,url,title,body,state,isDraft,headRefName,headRefOid,baseRefName');
  if (pr.number !== number || pr.headRefName !== branch) throw new Error('Submission PR identity changed; inspect before publishing.');
  return [pr];
}

function matchingMetadata(pr, record) {
  const body = String(pr.body ?? '').replace(/\r\n/g, '\n');
  if (pr.title === record.title && body === String(record.body ?? '').replace(/\r\n/g, '\n')) return true;
  return typeof record.pendingTitle === 'string' && typeof record.pendingBody === 'string' && pr.title === record.pendingTitle && body === record.pendingBody.replace(/\r\n/g, '\n');
}

async function inspectState({ repo, targets, branch, execute }) {
  assertBranch(branch);
  const normalized = normalizeTargets(targets);
  if (typeof execute !== 'function' || !repo?.root) throw new Error('A repository root and command executor are required.');

  for (const target of [normalized.primary, normalized.submission]) {
    const url = git(execute, repo, 'remote', 'get-url', target.remote);
    if (githubRepository(url).toLowerCase() !== target.repository.toLowerCase()) throw new Error(`The ${target.remote} remote changed from its configured publication target.`);
  }
  repoAccess(execute, repo, normalized.primary.repository, false);
  repoAccess(execute, repo, normalized.submission.repository, true);

  const mainReference = `refs/heads/${normalized.submission.base}`;
  const mainHead = parseRef(git(execute, repo, 'ls-remote', '--heads', 'submission', mainReference), mainReference);
  if (!mainHead) throw new Error('The private submission repository must already have its configured base branch.');

  const { path, record } = await readRecord(repo, branch);
  const branchReference = `refs/heads/${branch}`;
  const remoteHead = parseRef(git(execute, repo, 'ls-remote', '--heads', 'submission', branchReference), branchReference);
  const prs = privatePullRequests(execute, repo, normalized.submission.repository, branch);

  if (!record) {
    if (remoteHead || prs.length) throw new Error('An existing submission branch or PR has no retained accounting; inspect before publishing.');
    return { path, record: null, targets: normalized, mainHead, remoteHead, pr: null };
  }
  assertRecord(record, normalized, branch);

  const expectedRemoteHeads = new Set([record.mirrorHead, record.previousMirrorHead].filter(Boolean));
  if (remoteHead && !expectedRemoteHeads.has(remoteHead) || !remoteHead && record.phase !== 'branch-pending' && record.previousMirrorHead !== null) throw new Error('The retained submission branch changed or disappeared; refusing to overwrite it.');
  if (!remoteHead && record.phase !== 'branch-pending' && record.mirrorHead !== null) throw new Error('The retained submission branch is missing; inspect before publishing.');

  const pr = prs[0] ?? null;
  if (record.prNumber && (!pr || pr.number !== record.prNumber)) throw new Error('The retained submission PR is closed, missing, or replaced; inspect before publishing.');
  if (pr) {
    if (pr.state !== 'OPEN' || pr.baseRefName !== normalized.submission.base || pr.headRefName !== branch || !record.marker || !String(pr.body).includes(record.marker) || !matchingMetadata(pr, record)) throw new Error('The submission PR has unexpected edits or identity; inspect before publishing.');
    if (record.prUrl && pr.url !== record.prUrl) throw new Error('The retained submission PR URL changed; inspect before publishing.');
    if (!remoteHead || pr.headRefOid !== remoteHead) throw new Error('The submission PR head does not match its remote feature branch.');
  }
  return { path, record, targets: normalized, mainHead, remoteHead, pr };
}

export async function inspectSubmissionTarget(args) {
  const state = await inspectState(args);
  return { repository: state.targets.submission.repository, branch: args.branch, base: state.targets.submission.base, mainHead: state.mainHead, head: state.remoteHead, number: state.pr?.number, url: state.pr?.url };
}

function primaryPrUrl(primaryPr, repository) {
  const url = typeof primaryPr === 'string' ? primaryPr : primaryPr?.url;
  const match = typeof url === 'string' && url.match(/^https:\/\/github\.com\/([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)\/pull\/(\d+)\/?$/i);
  if (!match || match[1].toLowerCase() !== repository.toLowerCase() || primaryPr?.number !== undefined && Number(primaryPr.number) !== Number(match[2])) throw new Error('A public review PR URL for the configured origin repository is required.');
  return url;
}

function submissionBody(body, publicUrl, marker) {
  if (typeof body !== 'string' || !body.trim()) throw new Error('The submission PR body must include the public review summary.');
  const result = `${body.trimEnd()}\n\nPublic review PR: ${publicUrl}\n\n${marker}`;
  if (Buffer.byteLength(result) > 65_536) throw new Error('The submission PR body exceeds 65536 bytes.');
  return result;
}

function assertTitle(title) {
  if (typeof title !== 'string' || !title.trim() || title !== title.trim() || title.length > 256 || /[\r\n]/.test(title)) throw new Error('The submission PR title must be 1–256 characters on one line.');
}

async function saveRecord(path, record) {
  record.updatedAt = new Date().toISOString();
  await atomicWrite(path, `${JSON.stringify(record, null, 2)}\n`);
}

function commitMirror(execute, repo, tree, parent, branch, sourceHead) {
  return git(execute, repo, 'commit-tree', tree, '-p', parent, '-m', `submission mirror ${branch} ${sourceHead}`);
}

async function materializeInitialMirror(execute, repo, state, record) {
  git(execute, repo, 'fetch', '--no-tags', '--no-write-fetch-head', 'submission', `refs/heads/${record.base}`);
  const mainNow = parseRef(git(execute, repo, 'ls-remote', '--heads', 'submission', `refs/heads/${record.base}`), `refs/heads/${record.base}`);
  if (mainNow !== record.mainBase) throw new Error('Submission base changed during inspection; rerun publication after reviewing the new base.');
  git(execute, repo, 'cat-file', '-e', `${record.mainBase}^{commit}`);
  record.mirrorHead = commitMirror(execute, repo, record.sourceTree, record.mainBase, record.branch, record.sourceHead);
  record.previousMirrorHead = null;
  record.phase = 'branch-pending';
  await saveRecord(state.path, record);
}

function resultRecord(record, pr) {
  return {
    repository: record.targets.submission.repository,
    number: pr.number,
    url: pr.url,
    branch: record.branch,
    base: record.base,
    head: record.mirrorHead,
    sourceHead: record.sourceHead,
    sourceTree: record.sourceTree,
    isDraft: pr.isDraft,
  };
}

export async function publishSubmission({ repo, targets, branch, head, title, body, primaryPr, execute }) {
  assertBranch(branch);
  assertTitle(title);
  if (typeof head !== 'string' || !gitHash.test(head)) throw new Error('Submission publication requires the full public source commit SHA.');
  const inspected = await inspectState({ repo, targets, branch, execute });
  const lockPath = inspected.path.replace(/\.json$/i, '.lock');

  return withLock(lockPath, async () => {
    let state = await inspectState({ repo, targets, branch, execute });
    let record = state.record;
    const sourceHead = git(execute, repo, 'rev-parse', '--verify', `${head}^{commit}`).toLowerCase();
    if (sourceHead !== head.toLowerCase() || git(execute, repo, 'branch', '--show-current') !== branch || git(execute, repo, 'rev-parse', 'HEAD').toLowerCase() !== sourceHead) throw new Error('The public checkout must be on the requested feature branch and source commit.');
    const sourceTree = git(execute, repo, 'rev-parse', '--verify', `${sourceHead}^{tree}`).toLowerCase();
    const publicUrl = primaryPrUrl(primaryPr, state.targets.primary.repository);
    const desiredBody = record ? submissionBody(body, publicUrl, record.marker) : null;

    if (!record) {
      record = {
        schemaVersion: 1,
        targets: state.targets,
        repository: state.targets.submission.repository,
        branch,
        base: state.targets.submission.base,
        // Schema v1 retains this field name for historical records; it is the configured base SHA.
        mainBase: state.mainHead,
        sourceHead,
        sourceTree,
        mirrorHead: null,
        previousMirrorHead: null,
        phase: 'branch-pending',
        marker: `<!-- paired-submission:${randomUUID()} -->`,
        title,
        body: '',
        prNumber: null,
        prUrl: null,
      };
      record.body = submissionBody(body, publicUrl, record.marker);
      await saveRecord(state.path, record);
    } else {
      assertRecord(record, state.targets, branch);
      if (record.mirrorHead === null) {
        record.mainBase = state.mainHead;
        record.sourceHead = sourceHead;
        record.sourceTree = sourceTree;
        record.title = title;
        record.body = submissionBody(body, publicUrl, record.marker);
        await saveRecord(state.path, record);
      } else if (sourceHead !== record.sourceHead || sourceTree !== record.sourceTree) {
        if (sourceTree !== record.sourceTree) {
          const next = commitMirror(execute, repo, sourceTree, record.mirrorHead, branch, sourceHead);
          record.previousMirrorHead = record.mirrorHead;
          record.mirrorHead = next;
        }
        record.sourceHead = sourceHead;
        record.sourceTree = sourceTree;
        record.phase = 'branch-pending';
        await saveRecord(state.path, record);
      }
      if (!state.pr && !record.prNumber) {
        record.title = title;
        record.body = submissionBody(body, publicUrl, record.marker);
        delete record.pendingTitle;
        delete record.pendingBody;
      } else if (title !== record.title || desiredBody.replace(/\r\n/g, '\n') !== String(record.body).replace(/\r\n/g, '\n')) {
        record.pendingTitle = title;
        record.pendingBody = submissionBody(body, publicUrl, record.marker);
      }
      await saveRecord(state.path, record);
    }

    if (record.mirrorHead === null) await materializeInitialMirror(execute, repo, state, record);

    const currentBranchHead = parseRef(git(execute, repo, 'ls-remote', '--heads', 'submission', `refs/heads/${branch}`), `refs/heads/${branch}`);
    if (currentBranchHead !== record.mirrorHead) {
      if (currentBranchHead !== record.previousMirrorHead) throw new Error('The submission branch changed before push; refusing to overwrite it.');
      git(execute, repo, 'push', 'submission', `${record.mirrorHead}:refs/heads/${branch}`);
    }
    const pushedHead = parseRef(git(execute, repo, 'ls-remote', '--heads', 'submission', `refs/heads/${branch}`), `refs/heads/${branch}`);
    if (pushedHead !== record.mirrorHead) throw new Error('Submission push did not publish the intended mirror commit.');

    record.phase = 'pr-pending';
    await saveRecord(state.path, record);
    state = await inspectState({ repo, targets, branch, execute });
    let pr = state.pr;

    if (!pr) {
      const createTitle = record.pendingTitle ?? record.title;
      const createBody = record.pendingBody ?? record.body;
      try {
        await withPublicationBody(repo, createBody, path => command(execute, 'gh', ['pr', 'create', '--repo', record.targets.submission.repository, '--head', branch, '--base', record.base, '--draft', '--title', createTitle, '--body-file', path], repo));
      } catch (createError) {
        try { state = await inspectState({ repo, targets, branch, execute }); pr = state.pr; }
        catch { throw createError; }
        if (!pr) throw createError;
      }
      if (!pr) {
        state = await inspectState({ repo, targets, branch, execute });
        pr = state.pr;
      }
      if (!pr || !String(pr.body).includes(record.marker)) throw new Error('Submission PR creation did not produce the retained recovery marker.');
    } else if (record.pendingTitle !== undefined && (pr.title !== record.pendingTitle || String(pr.body ?? '').replace(/\r\n/g, '\n') !== record.pendingBody.replace(/\r\n/g, '\n'))) {
      try {
        await withPublicationBody(repo, record.pendingBody, path => command(execute, 'gh', ['pr', 'edit', String(pr.number), '--repo', record.targets.submission.repository, '--title', record.pendingTitle, '--body-file', path], repo));
      } catch (editError) {
        try { state = await inspectState({ repo, targets, branch, execute }); pr = state.pr; }
        catch { throw editError; }
        if (pr?.title !== record.pendingTitle || String(pr?.body ?? '').replace(/\r\n/g, '\n') !== record.pendingBody.replace(/\r\n/g, '\n')) throw editError;
      }
      state = await inspectState({ repo, targets, branch, execute });
      pr = state.pr;
    }

    if (!pr || pr.state !== 'OPEN' || pr.headRefOid !== record.mirrorHead || pr.baseRefName !== record.base || !String(pr.body).includes(record.marker)) throw new Error('The submission PR does not match its retained branch and source.');
    record.prNumber = pr.number;
    record.prUrl = pr.url;
    if (record.pendingTitle !== undefined) {
      record.title = record.pendingTitle;
      record.body = record.pendingBody;
      delete record.pendingTitle;
      delete record.pendingBody;
    }
    record.phase = 'complete';
    record.previousMirrorHead = null;
    await saveRecord(state.path, record);
    return resultRecord(record, pr);
  });
}

export async function verifySubmission({ repo, targets, branch, sourceHead, execute }) {
  assertBranch(branch);
  if (typeof sourceHead !== 'string' || !gitHash.test(sourceHead)) throw new Error('Submission verification requires the full public source commit SHA.');
  const state = await inspectState({ repo, targets, branch, execute });
  const record = state.record;
  if (!record || record.phase !== 'complete' || !record.prNumber || !state.pr || state.remoteHead !== record.mirrorHead || state.pr.number !== record.prNumber) throw new Error('Submission publication is incomplete or its retained PR identity changed.');
  const actualSourceHead = git(execute, repo, 'rev-parse', '--verify', `${sourceHead}^{commit}`).toLowerCase();
  if (actualSourceHead !== record.sourceHead || sourceHead.toLowerCase() !== actualSourceHead) throw new Error('Submission source commit does not match the retained publication.');
  const actualSourceTree = git(execute, repo, 'rev-parse', '--verify', `${actualSourceHead}^{tree}`).toLowerCase();
  const mirrorTree = git(execute, repo, 'rev-parse', '--verify', `${record.mirrorHead}^{tree}`).toLowerCase();
  if (actualSourceTree !== record.sourceTree || mirrorTree !== record.sourceTree) throw new Error('Submission mirror tree differs from the retained public source tree.');
  git(execute, repo, 'merge-base', '--is-ancestor', record.mainBase, record.mirrorHead);
  if (git(execute, repo, 'branch', '--show-current') !== branch || git(execute, repo, 'rev-parse', 'HEAD').toLowerCase() !== actualSourceHead) throw new Error('The public checkout changed during submission verification.');
  return resultRecord(record, state.pr);
}
