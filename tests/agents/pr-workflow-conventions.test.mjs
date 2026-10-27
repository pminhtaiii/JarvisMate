import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { assess, runWorkflow } from '../../scripts/agents/pr-workflow.mjs';
import { assertAvailableNumber } from '../../scripts/agents/pr-conventions.mjs';
import { checkout } from './support/pr-workflow-fixture.mjs';

test('new publication requires a scope before gates or writes', async t => {
  const f = await checkout(t);
  const result = spawnSync('git', ['switch', '-c', 'feat/011-unscoped'], { cwd: f.root, windowsHide: true });
  assert.equal(result.status, 0);
  await assert.rejects(f.run('publish', '--body-file', f.body), /scope/);
  assert.equal(f.calls.some(c => c[1] === 'push'), false);
});

test('invalid new branch forms and incomplete history are refused before gates or writes', async t => {
  for (const branch of ['feat/000-tooling-work', 'feat/12-tooling-work', 'feat/012-Tooling-work', 'feat/012-tooling-work_thing', 'feat/012-tooling-work--thing', 'feat/012-tooling']) {
    const f = await checkout(t);
    assert.equal(spawnSync('git', ['switch', '-c', branch], { cwd: f.root, windowsHide: true }).status, 0);
    await assert.rejects(f.run('publish', '--body-file', f.body), /scope|three-digit/);
    assert.equal(f.calls.some(c => c[1] === 'push' || c[0] === process.execPath), false);
  }
  const f = await checkout(t);
  await assert.rejects(runWorkflow(['publish', '--body-file', f.body, '--summary', 'add tooling', '--root', f.root], {
    execute(binary, args, cwd, timeout) {
      if (binary === 'gh' && args[0] === 'api' && args.at(-1).includes('/pulls?')) return JSON.stringify([{ truncated: true }]);
      return f.execute(binary, args, cwd, timeout);
    },
  }), /Incomplete PR history/);
  assert.equal(f.calls.some(c => c[1] === 'push' || c[0] === process.execPath), false);
});

test('new paired work requires development bases while public base overrides fail before commands', async t => {
  let executed = false;
  await assert.rejects(runWorkflow(['publish', '--body-file', 'body.md', '--summary', 'add tooling', '--base', 'main'], {
    execute() { executed = true; },
  }), /only publishes to development/);
  assert.equal(executed, false);
  const f = await checkout(t);
  const git = (...args) => {
    const result = spawnSync('git', args, { cwd: f.root, windowsHide: true });
    assert.equal(result.status, 0);
  };
  git('remote', 'add', 'submission', 'https://github.com/course/private.git');
  await writeFile(join(f.root, 'publication-targets.json'), JSON.stringify({ schemaVersion: 1, submission: { remote: 'submission', base: 'main' } }));
  git('add', 'publication-targets.json');
  git('commit', '--quiet', '-m', 'historical configuration');
  await assert.rejects(f.run('publish', '--body-file', f.body), /New paired work requires submission\/development/);
  assert.equal(f.calls.some(c => c[1] === 'push' || c[0] === process.execPath), false);
});

test('new publish rejects reused numbers across local branches, live heads and paginated closed PR history', async t => {
  for (const source of ['local', 'remote', 'closed', 'merged', 'exact']) {
    const f = await checkout(t);
    if (source === 'local') assert.equal(spawnSync('git', ['branch', 'feat/010-tooling-prior'], { cwd: f.root, windowsHide: true }).status, 0);
    await assert.rejects(runWorkflow(['publish', '--body-file', f.body, '--summary', 'standardize tooling', '--root', f.root], {
      execute(binary, args, cwd, timeout) {
        if (binary === 'git' && args[0] === 'ls-remote' && source === 'remote') return 'a'.repeat(40) + '\trefs/heads/feat/010-infra-prior';
        if (binary === 'gh' && args[0] === 'api' && args.at(-1).includes('/pulls?') && ['closed', 'merged', 'exact'].includes(source)) {
          return JSON.stringify([[], [{ state: 'closed', merged_at: source === 'merged' ? '2026-10-16' : null, head: { ref: source === 'exact' ? 'feat/010-tooling-example' : 'feat/010-legacy' } }]]);
        }
        return f.execute(binary, args, cwd, timeout);
      },
    }), /unique NNN|already exists/);
    assert.equal(f.calls.some(c => c[1] === 'push' || c[0] === process.execPath), false);
  }
});

test('an established convention-v1 PR remains updateable after a historical same-number PR is recorded', async t => {
  const f = await checkout(t);
  const initial = await f.run('publish', '--body-file', f.body);
  assert.equal(initial.status, 'PUBLISHED');
  const recordPath = join(f.root, '.agent-work/pr-workflow/010-tooling-example.json');
  const record = JSON.parse(await readFile(recordPath, 'utf8'));
  assert.equal(record.conventionVersion, 1);
  const recordedPr = record.pr;
  f.calls.length = 0;

  const updated = await runWorkflow(['publish', '--body-file', f.body, '--summary', 'add the example workflow', '--root', f.root], {
    execute(binary, args, cwd, timeout) {
      if (binary === 'gh' && args[0] === 'api' && args.at(-1).includes('/pulls?')) {
        return JSON.stringify([[{ state: 'closed', head: { ref: 'feat/010-uc01-historical' } }]]);
      }
      return f.execute(binary, args, cwd, timeout);
    },
  });

  assert.equal(updated.status, 'PUBLISHED');
  assert.equal(updated.pr, recordedPr);
  assert.equal(f.calls.filter(call => call[0] === 'gh' && call[1] === 'pr' && call[2] === 'edit').length, 1);
  assert.equal(f.calls.some(call => call[0] === 'gh' && call[1] === 'pr' && call[2] === 'create'), false);
});

test('assertAvailableNumber returns early when hasPr is true and checks collisions on retries', () => {
  let executed = false;
  assertAvailableNumber({
    branch: 'feat/010-tooling-example',
    targets: { primary: { remote: 'origin', repository: 'example/project' } },
    execute() { executed = true; },
    root: '.',
    fresh: false,
    hasPr: true,
  });
  assert.equal(executed, false, 'established PR with hasPr=true must return early without checking inventory');

  const executeWithConflict = (binary, args) => {
    if (binary === 'git' && args[0] === 'for-each-ref') return 'feat/010-tooling-example';
    if (binary === 'git' && args[0] === 'ls-remote') return 'a'.repeat(40) + '\trefs/heads/feat/010-tooling-example\n' + 'b'.repeat(40) + '\trefs/heads/feat/010-other-tooling';
    if (binary === 'gh' && args[0] === 'api') return JSON.stringify([[]]);
    return '';
  };
  assert.throws(() => {
    assertAvailableNumber({
      branch: 'feat/010-tooling-example',
      targets: { primary: { remote: 'origin', repository: 'example/project' } },
      execute: executeWithConflict,
      root: '.',
      fresh: false,
      hasPr: false,
    });
  }, /Feature number 010 was already used; select a unique NNN\./);

  const executeClean = (binary, args) => {
    if (binary === 'git' && args[0] === 'for-each-ref') return 'feat/010-tooling-example';
    if (binary === 'git' && args[0] === 'ls-remote') return 'a'.repeat(40) + '\trefs/heads/feat/010-tooling-example';
    if (binary === 'gh' && args[0] === 'api') return JSON.stringify([[]]);
    return '';
  };
  assert.doesNotThrow(() => {
    assertAvailableNumber({
      branch: 'feat/010-tooling-example',
      targets: { primary: { remote: 'origin', repository: 'example/project' } },
      execute: executeClean,
      root: '.',
      fresh: false,
      hasPr: false,
    });
  });
});

test('an unrecorded retry allows its own pushed branch on remote but rejects other branches sharing the number', async t => {
  const f = await checkout(t);
  await mkdir(join(f.root, '.agent-work/pr-workflow'), { recursive: true });
  const recordPath = join(f.root, '.agent-work/pr-workflow/010-tooling-example.json');
  await writeFile(recordPath, JSON.stringify({
    schemaVersion: 1,
    repository: 'example/project',
    branch: 'feat/010-tooling-example',
    base: 'development',
    repairRounds: [],
    publicationStarted: true,
    conventionVersion: 1,
  }));

  await assert.rejects(runWorkflow(['publish', '--body-file', f.body, '--summary', 'add the example workflow', '--root', f.root], {
    execute(binary, args, cwd, timeout) {
      if (binary === 'git' && args[0] === 'ls-remote') {
        return 'a'.repeat(40) + '\trefs/heads/feat/010-tooling-example\n' + 'b'.repeat(40) + '\trefs/heads/feat/010-other-feature';
      }
      return f.execute(binary, args, cwd, timeout);
    },
  }), /Feature number 010 was already used; select a unique NNN\./);

  await assert.rejects(runWorkflow(['publish', '--body-file', f.body, '--summary', 'add the example workflow', '--root', f.root], {
    execute(binary, args, cwd, timeout) {
      if (binary === 'git' && args[0] === 'ls-remote') {
        return 'a'.repeat(40) + '\trefs/heads/feat/010-tooling-example';
      }
      if (binary === 'gh' && args[0] === 'api' && args.at(-1).includes('/pulls?')) {
        return JSON.stringify([[{ state: 'closed', head: { ref: 'feat/010-other-historical' } }]]);
      }
      return f.execute(binary, args, cwd, timeout);
    },
  }), /Feature number 010 was already used; select a unique NNN\./);

  const retried = await runWorkflow(['publish', '--body-file', f.body, '--summary', 'add the example workflow', '--root', f.root], {
    execute(binary, args, cwd, timeout) {
      if (binary === 'git' && args[0] === 'ls-remote') {
        return 'a'.repeat(40) + '\trefs/heads/feat/010-tooling-example';
      }
      return f.execute(binary, args, cwd, timeout);
    },
  });

  assert.equal(retried.status, 'PUBLISHED');
  assert.equal(retried.pr, 1);
  const updatedRecord = JSON.parse(await readFile(recordPath, 'utf8'));
  assert.equal(updatedRecord.pr, 1);
  assert.equal(updatedRecord.publicationStarted, true);
});

test('new publish validates action summary and ordered nonempty description sections before gates', async t => {
  const f = await checkout(t);
  for (const summary of ['tooling changes', 'Standardize tooling']) {
    await assert.rejects(runWorkflow(['publish', '--body-file', f.body, '--summary', summary, '--root', f.root], { execute: f.execute }), /action verb/);
  }
  for (const body of ['plain text', '## Evidence\nchecks\n## Summary\nchange\n## Merge Danger\nrisk', '## Summary\n\n## Evidence\nchecks\n## Merge Danger\nrisk', '## Summary\nchange\n## Evidence\nchecks\n## Merge Danger\nrisk']) {
    await writeFile(f.body, body);
    await assert.rejects(f.run('publish', '--body-file', f.body), /description|Merge Danger/);
  }
  assert.equal(f.calls.some(c => c[1] === 'push' || c[0] === process.execPath), false);
});

test('legacy branch identity and retained publication intent remain readable', async t => {
  const f = await checkout(t), legacy = 'feat/001-example';
  assert.equal(spawnSync('git', ['switch', '-c', legacy], { cwd: f.root, windowsHide: true }).status, 0);
  Object.assign(f.e.pr, { headRefName: legacy, title: legacy + ': historical title' });
  await mkdir(join(f.root, '.agent-work/pr-workflow'), { recursive: true });
  await writeFile(join(f.root, '.agent-work/pr-workflow/001-example.json'), JSON.stringify({ schemaVersion: 1, repository: 'example/project', branch: legacy, base: 'development', repairRounds: [], publicationStarted: true }));
  await writeFile(f.body, 'Historical unstructured description');
  assert.equal((await f.run('publish', '--body-file', f.body)).status, 'PUBLISHED');
  assert.equal(assess(f.e).status, 'READY_FOR_HUMAN');
});
