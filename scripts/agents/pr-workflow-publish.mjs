import { randomUUID } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import { resolve } from 'node:path';
import { assertNoTrackedArtifacts } from '../ci/check-tracked-files.mjs';
import { dataDirectory } from './agent-store.mjs';
import { assertAvailableNumber, assertAvailableBranch, assertNewDescription, assertNewSummary } from './pr-conventions.mjs';
import { inspectSubmissionTarget, publishSubmission } from './submission-pr.mjs';
import { withPublicationBody } from './publication-targets.mjs';
import { packageScriptCommand, runGate } from './workflow-gate.mjs';
import { changedLines } from './pr-workflow-status.mjs';

export async function publishCommand({ values, record, branch, repo, remote, git, find, pairedExecute, targets, dependencies, call, save, gh, json }) {
  const title = `${branch}: ${values.summary}`;
  const bodyPath = resolve(values['body-file']);
  if ((await stat(bodyPath)).size > 65_536) throw new Error('PR body exceeds 65536 bytes.');
  const body = await readFile(bodyPath, 'utf8');
  if (!body.trim() || Buffer.byteLength(body) > 65_536) throw new Error('PR body must contain 1–65536 bytes.');
  if (targets) {
    const publicContent = `${title}\n${body}`.toLowerCase();
    const privateRepository = targets.submission.repository.toLowerCase();
    if (publicContent.includes(privateRepository) || publicContent.includes(encodeURIComponent(privateRepository))) throw new Error('Public PR content must not include the private repository identity.');
  }
  if (git('status', '--porcelain', '--untracked-files=all')) throw new Error('Commit the assigned changes before publishing; checkout must be clean.');
  assertNoTrackedArtifacts(git('ls-files', '-z'));
  const initialPr = find();
  if (record.pr && (!initialPr || initialPr.number !== record.pr)) throw new Error('Recorded PR is closed or replaced; start a new feature branch instead of resetting its budget.');
  if (initialPr && !record.pr && !record.publicationStarted) throw new Error('Existing PR has no local accounting; recover its workflow record before publishing.');
  const conventionVersion = record.conventionVersion ?? (!record.pr && !record.publicationStarted ? 2 : undefined);
  if (conventionVersion !== undefined && ![1, 2].includes(conventionVersion)) throw new Error('Unsupported convention version; retain accounting and inspect before publishing.');
  const newConventions = conventionVersion !== undefined;
  if (newConventions) {
    if (targets && targets.submission.base !== 'development') throw new Error('New paired work requires submission/development; retain historical main configuration only for existing pairs.');
    assertNewSummary(values.summary);
    assertNewDescription(body);
    const inventory = conventionVersion === 1 ? assertAvailableNumber : assertAvailableBranch;
    inventory({ branch, targets: targets ?? { primary: { remote: 'origin', repository: remote } }, execute: pairedExecute, root: repo.root, fresh: !record.pr && !record.publicationStarted, hasPr: Boolean(record.pr) });
  }
  git('fetch', '--no-tags', 'origin', 'refs/heads/development:refs/remotes/origin/development');
  const size = changedLines(git('diff', '--numstat', '--no-renames', 'origin/development...HEAD'));
  if (!size.reviewable && !size.generated && !size.binaries) throw new Error('No changes against development.');
  const head = git('rev-parse', 'HEAD');
  if (targets) await inspectSubmissionTarget({ repo, targets, branch, execute: pairedExecute });
  const gateLogs = {};
  const gate = async (name, argv, command = process.execPath) => {
    if (dependencies.execute) return call(command, argv, 600_000);
    const directory = await dataDirectory(repo, 'pr-workflow-logs');
    try {
      const result = await runGate({ name, command, args: argv, cwd: repo.root, logPath: resolve(directory, `${Date.now()}-${randomUUID()}-${name}.log`), report: dependencies.report });
      gateLogs[name] = result;
      return result.summary || 'Passed without output.';
    } catch (error) {
      if (error.gate) { record.gateLogs = { ...gateLogs, [name]: error.gate }; await save(); }
      throw error;
    }
  };
  const contextOutput = await gate('context', [resolve(repo.root, 'scripts/ci/check-context.mjs')]);
  const dependencyChanges = git('diff', '--name-only', record.publishedHead ?? 'origin/development', 'HEAD', '--', 'package.json', '**/package.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml', '.npmrc', '.pnpmfile.cjs', 'pnpmfile.cjs');
  const installOutput = dependencyChanges ? await gate('dependencies', [resolve(repo.root, 'scripts/ci/check-dependency-install.mjs')]) : 'Dependency inputs unchanged since the last publication/base.';
  const runtimeOutput = await gate('runtime', [resolve(repo.root, 'scripts/ci/check-runtime.mjs')]);
  const contributorTests = packageScriptCommand('test:contributors');
  const testOutput = await gate('tests', contributorTests.args, contributorTests.command);
  if (git('status', '--porcelain', '--untracked-files=all') || git('rev-parse', 'HEAD') !== head || git('branch', '--show-current') !== branch) throw new Error('Checkout changed during local gates; inspect before push.');
  let pr = find();
  if (record.pr && (!pr || pr.number !== record.pr)) throw new Error('Recorded PR is closed or replaced; start a new feature branch instead of resetting its budget.');
  if (pr?.number !== initialPr?.number || pr?.headRefOid !== initialPr?.headRefOid) throw new Error('PR changed during local gates; inspect its current head before publishing.');
  record.localVerification = { head, context: contextOutput.slice(-2000), runtime: runtimeOutput.slice(-2000), dependencies: installOutput.slice(-2000), tests: testOutput.split('\n').slice(-10).join('\n') };
  record.gateLogs = gateLogs;
  delete record.completion;
  record.publicationStarted = true;
  if (newConventions) record.conventionVersion = conventionVersion;
  if (targets) record.pairedTargets = targets;
  await save();
  git('push', '--set-upstream', 'origin', `HEAD:refs/heads/${branch}`);
  await withPublicationBody(repo, body, async frozenBodyPath => {
    if (pr) gh('pr', 'edit', String(pr.number), '--repo', remote, '--title', title, '--body-file', frozenBodyPath);
    else {
      gh('pr', 'create', '--repo', remote, '--head', branch, '--base', 'development', '--draft', '--title', title, '--body-file', frozenBodyPath);
      pr = find();
      if (!pr) throw new Error('PR created but lookup failed; rerun publish to recover.');
    }
  });
  Object.assign(record, { pr: pr.number, url: pr.url, head, publishedHead: head, size, status: 'PUBLISHED' });
  await save();
  if (targets) {
    try {
      record.submission = await publishSubmission({ repo, targets, branch, head, title, body, primaryPr: { number: pr.number, url: pr.url }, execute: pairedExecute });
      delete record.submissionError;
      delete record.reason;
      await save();
    } catch (error) {
      record.status = 'PARTIAL_PUBLICATION';
      record.reason = record.submissionError = error.message;
      await save();
      throw new Error(`Public PR published at ${pr.url}; submission publication incomplete. Retain accounting and rerun publish. ${error.message}`, { cause: error });
    }
  }
  if (!values['skip-review-request'] && record.requestedReviewHead !== head) {
    const request = `@coderabbitai review\n\n<!-- slop-loop-review:${head} -->`;
    const pages = json('api', '--paginate', '--slurp', `repos/${remote}/issues/${pr.number}/comments?per_page=100`);
    if (!pages.flat().some((comment) => comment.body === request)) gh('pr', 'comment', String(pr.number), '--repo', remote, '--body', request);
    record.requestedReviewHead = head;
    await save();
  }
  return record;
}
