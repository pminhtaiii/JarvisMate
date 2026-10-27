import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { runWorkflow } from '../../scripts/agents/pr-workflow.mjs';
import { packageScriptCommand } from '../../scripts/agents/workflow-gate.mjs';
import { checkout } from './support/pr-workflow-fixture.mjs';

test('publish rejects tracked dependencies before tests, push, or PR creation', async (t) => {
  const f = await checkout(t);
  await mkdir(join(f.root, 'node_modules/lib'), { recursive: true });
  await writeFile(join(f.root, 'node_modules/lib/index.js'), 'export {};\n');
  const git = (...args) => {
    const result = spawnSync('git', args, { cwd: f.root, encoding: 'utf8', windowsHide: true });
    assert.equal(result.status, 0, result.stderr);
  };
  git('add', 'node_modules');
  git('commit', '--quiet', '-m', 'accidental dependencies');
  await assert.rejects(f.run('publish', '--body-file', f.body), /Installed dependencies must remain untracked/);
  assert.equal(f.calls.some((call) => call[0] === process.execPath || call[0] === 'gh' || call[1] === 'push'), false);
});

test('publication uses the validated body snapshot even if its file changes during gates', async t => {
  const f = await checkout(t);
  const expectedBody = '## Summary\n\nChange tooling.\n\n## Evidence\n\nVerified checks.\n\n## Merge Danger\n\n**Door:** two-way\n\n**Blast Radius:** tooling\n' + 'x'.repeat(40_000);
  await writeFile(f.body, expectedBody);
  let publishedBody;
  await runWorkflow(['publish', '--body-file', f.body, '--summary', 'freeze the publication body', '--root', f.root], {
    execute(binary, args, cwd, timeout) {
      if (binary === process.execPath) writeFileSync(f.body, 'Changed after validation');
      if (binary === 'gh' && args[0] === 'pr' && args[1] === 'create') publishedBody = readFileSync(args[args.indexOf('--body-file') + 1], 'utf8');
      return f.execute(binary, args, cwd, timeout);
    },
  });
  const create = f.calls.find(call => call[0] === 'gh' && call[1] === 'pr' && call[2] === 'create');
  assert.ok(create.includes('--body-file'));
  assert.equal(publishedBody, expectedBody);
  assert.ok(create.join(' ').length < 1000, 'large bodies must stay outside the Windows command line');
});

test('publishing is gated and repeatable; repair count survives new publishes and stops at three', async (t) => {
  const f = await checkout(t);
  await f.run('publish', '--body-file', f.body);
  await f.run('publish', '--body-file', f.body);
  assert.equal(f.calls.filter((call) => call[0] === 'gh' && call[1] === 'pr' && call[2] === 'create').length, 1);
  for (const call of f.calls.filter((call) => call[0] === 'gh' && call[1] === 'pr' && ['create', 'edit'].includes(call[2]))) {
    assert.equal(call[call.indexOf('--title') + 1], 'feat/010-tooling-example: add the example workflow');
  }
  assert.equal(f.calls.filter((call) => call[0] === 'gh' && call[1] === 'pr' && call[2] === 'comment').length, 1);
  const savedPath = join(f.root, '.agent-work/pr-workflow/010-tooling-example.json');
  const saved = JSON.parse(await readFile(savedPath, 'utf8'));
  delete saved.requestedReviewHead;
  await writeFile(savedPath, JSON.stringify(saved));
  await f.run('publish', '--body-file', f.body);
  assert.equal(f.calls.filter((call) => call[0] === 'gh' && call[2] === 'comment').length, 1, 'recover a successful comment response without a duplicate request');
  assert.equal((await f.run('ready')).status, 'AWAITING_HUMAN_MERGE');
  assert.equal((await f.run('status')).status, 'AWAITING_HUMAN_MERGE');
  assert.equal(f.calls.some((call) => call.includes('merge') || call.includes('--force')), false);
  f.e.pr.reviewThreads.nodes = [{ id: 'finding', isResolved: false }];
  await f.run('repair', '--reason', 'Diagnosed round 1');
  await assert.rejects(f.run('repair', '--reason', 'duplicate command'), /already reserved/);
  for (let round = 1; round < 3; round++) {
    await f.advance();
    await f.run('publish', '--body-file', f.body);
    assert.equal((await f.run('status')).status, 'AWAITING_HUMAN_MERGE');
    f.e.pr.reviews.nodes[0].commit.oid = f.e.pr.headRefOid;
    await f.run('repair', '--reason', `Diagnosed round ${round + 1}`);
  }
  assert.equal((await f.run('status')).status, 'AWAITING_HUMAN_MERGE', 'advisory comments do not block human review');
  await f.advance();
  await f.run('publish', '--body-file', f.body);
  f.e.pr.reviews.nodes[0].commit.oid = f.e.pr.headRefOid;
  assert.equal((await f.run('status')).status, 'AWAITING_HUMAN_MERGE');
  await assert.rejects(f.run('repair', '--reason', 'fourth'), /Three repair rounds/);
  const record = JSON.parse(await readFile(join(f.root, '.agent-work/pr-workflow/010-tooling-example.json'), 'utf8'));
  assert.equal(record.repairRounds.length, 3);
  assert.equal(new Set(record.repairRounds.map((round) => round.head)).size, 3);
});

test('publish can skip only the automatic review request', async (t) => {
  const f = await checkout(t);
  const published = await f.run('publish', '--body-file', f.body, '--skip-review-request');

  assert.equal(published.status, 'PUBLISHED');
  assert.ok(f.calls.some(call => call[0] === process.execPath && call[1].endsWith('check-context.mjs')));
  assert.ok(f.calls.some(call => call[0] === process.execPath && call[1].endsWith('check-runtime.mjs')));
  const contributorTests = packageScriptCommand('test:contributors');
  assert.ok(f.calls.some(call => call[0] === contributorTests.command && JSON.stringify(call.slice(1)) === JSON.stringify(contributorTests.args)));
  assert.ok(f.calls.some(call => call[0] === 'git' && call[1] === 'push'));
  assert.ok(f.calls.some(call => call[0] === 'gh' && call[1] === 'pr' && call[2] === 'create' && call.includes('--draft')));
  assert.equal(f.calls.some(call => call[0] === 'gh' && call[1] === 'pr' && call[2] === 'comment'), false);
  assert.equal(f.calls.some(call => call[0] === 'gh' && call[1] === 'api' && call.at(-1).includes('/comments?')), false);
  const recordPath = join(f.root, '.agent-work/pr-workflow/010-tooling-example.json');
  assert.equal(JSON.parse(await readFile(recordPath, 'utf8')).requestedReviewHead, undefined);

  await f.run('publish', '--body-file', f.body);
  assert.equal(f.calls.filter(call => call[0] === 'gh' && call[1] === 'pr' && call[2] === 'comment').length, 1, 'the default still requests review on a later publish');
});
