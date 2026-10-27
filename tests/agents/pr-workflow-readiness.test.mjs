import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { assess, runWorkflow } from '../../scripts/agents/pr-workflow.mjs';
import { checkout, evidence } from './support/pr-workflow-fixture.mjs';

test('bot review decisions are advisory while GitHub merge blockers remain enforced', () => {
  const e = evidence();
  e.pr.reviewDecision = 'REVIEW_REQUIRED';
  assert.equal(assess(e).status, 'READY_FOR_HUMAN');
  e.pr.reviewDecision = 'APPROVED';
  e.pr.mergeStateStatus = 'BLOCKED';
  e.pr.isDraft = false;
  assert.equal(assess(e).status, 'BLOCKED');
  e.pr.reviewDecision = 'CHANGES_REQUESTED';
  assert.equal(assess(e).status, 'BLOCKED', 'server-side merge blockers remain enforced');
  e.pr.reviewDecision = 'REVIEW_REQUIRED';
  assert.equal(assess(e).status, 'BLOCKED');
  e.pr.reviewDecision = 'APPROVED';
  e.pr.isDraft = true;
  assert.equal(assess(e).status, 'READY_FOR_HUMAN', 'a validated draft may move to ready, but cannot be merged by this helper');
});

test('missing accounting fails closed instead of granting a fresh budget to an existing PR', async (t) => {
  const f = await checkout(t);
  await f.run('publish', '--body-file', f.body);
  const record = join(f.root, '.agent-work/pr-workflow/010-tooling-example.json');
  await rm(record);
  for (const command of ['status', 'ready']) await assert.rejects(f.run(command), /Missing PR accounting/);
  await assert.rejects(f.run('repair', '--reason', 'try again'), /Missing PR accounting/);
  await assert.rejects(f.run('publish', '--body-file', f.body), /no local accounting/);
  assert.equal(f.calls.filter((call) => call[0] === 'gh' && call[2] === 'create').length, 1);
});

test('watch caps every observation and sleep to the remaining ten-minute deadline', async (t) => {
  const f = await checkout(t);
  await f.run('publish', '--body-file', f.body);
  f.e.checks[0].status = 'in_progress';
  let clock = 0;
  const result = await runWorkflow(['watch', '--root', f.root], {
    now: () => clock,
    sleep: async (ms) => { clock += ms; },
    report: () => {},
    execute(binary, args, cwd, timeout) {
      if (binary === 'gh') clock += Math.min(timeout, 80_000);
      return f.execute(binary, args, cwd, timeout);
    },
  });
  assert.equal(result.status, 'TIMED_OUT');
  assert.ok(clock <= 600_000, `watch spent ${clock}ms`);
});

test('contributor CI must pass on the current head before readiness', () => {
  for (const name of ['contributor-checks (ubuntu-latest)', 'contributor-checks (windows-latest)']) {
    for (const state of ['missing', 'failure', 'pending', 'stale']) {
      const e = evidence();
      const check = e.checks.find((item) => item.name === name);
      if (state === 'missing') e.checks = e.checks.filter((item) => item !== check);
      if (state === 'failure') check.conclusion = 'failure';
      if (state === 'pending') check.status = 'in_progress';
      if (state === 'stale') check.head_sha = 'old';
      assert.equal(assess(e).status, state === 'failure' ? 'NEEDS_FIX' : 'WAITING_CI', `${name}: ${state}`);
    }
  }
});

test('harness lint failure prevents publication', async (t) => {
  const f = await checkout(t);
  await assert.rejects(runWorkflow(['publish', '--body-file', f.body, '--summary', 'gate runtime', '--root', f.root], {
    execute(binary, args, cwd, timeout) {
      if (binary === process.execPath && args[0].endsWith('check-runtime.mjs')) throw new Error('Harness lint failed');
      return f.execute(binary, args, cwd, timeout);
    },
  }), /Harness lint failed/);
  assert.equal(f.calls.some((call) => call[1] === 'push' || call[0] === 'gh' && call[2] === 'create'), false);
});

test('dependency changes require a fresh install before publishing; documentation changes do not', async (t) => {
  const f = await checkout(t);
  await f.run('publish', '--body-file', f.body);
  const git = (...args) => {
    const result = spawnSync('git', args, { cwd: f.root, encoding: 'utf8', windowsHide: true });
    assert.equal(result.status, 0, result.stderr);
  };
  await writeFile(join(f.root, 'package.json'), '{"private":true}\n');
  git('add', 'package.json'); git('commit', '--quiet', '-m', 'change dependency inputs');
  const run = () => runWorkflow(['publish', '--body-file', f.body, '--summary', 'gate dependencies', '--root', f.root], {
    execute(binary, args, cwd, timeout) {
      if (binary === process.execPath && args[0].endsWith('check-dependency-install.mjs')) throw new Error('Release age rejected');
      return f.execute(binary, args, cwd, timeout);
    },
  });
  const pushes = () => f.calls.filter((call) => call[1] === 'push').length;
  const before = pushes();
  await assert.rejects(run(), /Release age rejected/);
  assert.equal(pushes(), before);
  await f.run('publish', '--body-file', f.body);
  await f.advance();
  await run();
  assert.equal(pushes(), before + 2, 'unchanged dependencies permit documentation publication');
});

test('completion requires a clean published current head, linked PR and passing CI', async (t) => {
  const f = await checkout(t);
  await assert.rejects(f.run('complete'), /Missing PR accounting/);
  await f.run('publish', '--body-file', f.body);
  await assert.rejects(f.run('complete'), /linked/);
  const receipt = join(f.root, '.agent-work/app-state.json');
  await writeFile(receipt, JSON.stringify({ pullRequests: [] }));
  await assert.rejects(f.run('record-app-state', '--receipt', receipt), /linked PR/);
  await writeFile(receipt, JSON.stringify({ pullRequests: [{ url: f.e.pr.url, repository: 'example/project', number: 1 }] }));
  await f.run('record-app-state', '--receipt', receipt);
  assert.equal((await f.run('complete')).completion.head, f.e.head);
  f.e.checks[2].status = 'in_progress';
  await assert.rejects(f.run('complete'), /WAITING_CI/);
  f.e.checks[2].status = 'completed'; f.e.checks[2].conclusion = 'failure';
  await assert.rejects(f.run('complete'), /NEEDS_FIX/);
  f.e.checks[2].conclusion = 'success';
  await writeFile(join(f.root, 'dirty.md'), 'unpublished');
  await assert.rejects(f.run('complete'), /clean/);
  await rm(join(f.root, 'dirty.md'));
  await f.advance();
  await assert.rejects(f.run('complete'), /published|BLOCKED/);
});
