import assert from 'node:assert/strict';
import test from 'node:test';
import { assess, changedLines, runWorkflow, workflowSummary } from '../../scripts/agents/pr-workflow.mjs';
import { evidence } from './support/pr-workflow-fixture.mjs';

test('current-head CI allows human review without CodeRabbit approval', () => {
  const e = evidence();
  assert.equal(assess(e).status, 'READY_FOR_HUMAN');
  e.pr.reviews.nodes[0].commit.oid = 'old';
  assert.equal(assess(e).status, 'READY_FOR_HUMAN');
  e.pr.reviews.nodes = [];
  assert.equal(assess(e).status, 'READY_FOR_HUMAN');
});

test('merge and unknown commands are rejected before executing anything', async () => {
  let called = false;
  await assert.rejects(runWorkflow(['merge'], { execute() { called = true; } }), /Usage/);
  assert.equal(called, false);
});

test('PR titles require their branch prefix and a short summary', () => {
  const e = evidence();
  e.pr.title = `${e.pr.headRefName}: add the example workflow`;
  assert.equal(assess(e).status, 'READY_FOR_HUMAN');
  for (const title of [e.pr.headRefName, `${e.pr.headRefName}: `, 'feat/002-other: summary', `${e.pr.headRefName}: ${'x'.repeat(81)}`, `${e.pr.headRefName}: two\nlines`]) {
    e.pr.title = title;
    assert.equal(assess(e).status, 'BLOCKED', title);
  }
});

test('publishing rejects missing or invalid summaries before executing commands', async () => {
  let called = false;
  for (const args of [[], ['--summary', ' '], ['--summary', 'x'.repeat(81)], ['--summary', 'two\nlines']]) {
    await assert.rejects(runWorkflow(['publish', '--body-file', 'body.md', ...args], { execute() { called = true; } }), /summary/);
  }
  assert.equal(called, false);
});

test('failed, missing, skipped, spoofed, or superseded CI cannot be accepted', () => {
  for (const conclusion of ['failure', 'skipped', 'cancelled', 'neutral']) {
    const e = evidence(); e.checks[0].conclusion = conclusion;
    assert.equal(assess(e).status, 'NEEDS_FIX');
  }
  const e = evidence();
  e.checks[0].app.slug = 'another-app';
  assert.equal(assess(e).status, 'WAITING_CI');
  e.checks[0].app.slug = 'github-actions';
  e.checks[0].head_sha = 'old';
  assert.equal(assess(e).status, 'WAITING_CI');
  e.checks[0].head_sha = 'abc';
  e.checks.push({ ...e.checks[0], id: 99, status: 'in_progress', conclusion: null });
  assert.equal(assess(e).status, 'WAITING_CI');
});

test('unresolved comments remain visible and advisory while incomplete or mismatched evidence blocks', () => {
  const e = evidence();
  e.pr.reviewThreads.nodes.push({ id: 'thread', isResolved: false, isOutdated: true });
  assert.equal(assess(e).status, 'READY_FOR_HUMAN');
  assert.equal(assess(e).unresolved[0].id, 'thread');
  e.pr.reviewThreads.nodes = [];
  e.pr.reviews.nodes[0].author.__typename = 'User';
  assert.equal(assess(e).status, 'READY_FOR_HUMAN');
  e.pr.reviews.pageInfo.hasPreviousPage = true;
  assert.equal(assess(e).status, 'BLOCKED');
  e.pr.reviews.pageInfo.hasPreviousPage = false;
  e.pr.headRefOid = 'different';
  assert.equal(assess(e).status, 'BLOCKED');
  const waiting = evidence();
  waiting.pr.reviews.nodes[0].commit.oid = 'old';
  waiting.pr.reviewDecision = 'CHANGES_REQUESTED';
  waiting.pr.reviewThreads.nodes = [{ id: 'old-finding', isResolved: false }];
  assert.equal(assess(waiting).status, 'READY_FOR_HUMAN', 'comments are advisory under the human merge policy');
});

test('PR sizing reports generated changes and binaries separately without hiding them', () => {
  assert.deepEqual(changedLines('700\t400\tsrc/code.ts\n200\t100\tpackage-lock.json\n-\t-\tasset.png\n'), { reviewable: 1100, generated: 300, binaries: 1, overTarget: true });
});

test('routine summaries expose comments and log paths without historical command output', () => {
  const summary = workflowSummary({ schemaVersion: 1, repairRounds: [], localVerification: { head: 'abc', tests: 'private lengthy test transcript' }, gateLogs: { tests: { status: 'passed', log: 'tests.log', exitCode: 0, summary: 'lengthy output' } }, observation: { unresolved: [{ id: 'thread', isOutdated: false, comments: { nodes: [{ url: 'https://example.invalid/comment', body: 'lengthy comment' }] } }] } });
  assert.equal(summary.localVerifiedHead, 'abc');
  assert.equal(summary.logs.tests.log, 'tests.log');
  assert.equal(summary.unresolved[0].id, 'thread');
  assert.doesNotMatch(JSON.stringify(summary), /lengthy/);
  assert.equal(workflowSummary({ schemaVersion: 1, repairRounds: [], observation: { reason: 'Update the feature branch against development.' } }).reason, 'Update the feature branch against development.');
});
