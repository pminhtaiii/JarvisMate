import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { runWorkflow } from '../../scripts/agents/pr-workflow.mjs';
import { checkout } from './support/pr-workflow-fixture.mjs';

test('unnumbered branch publication creates a matching PR title and remains eligible for completion', async t => {
  const f = await checkout(t), branch = 'feat/tooling-branch-naming';
  assert.equal(spawnSync('git', ['switch', '-c', branch], { cwd: f.root, windowsHide: true }).status, 0);
  Object.assign(f.e.pr, { headRefName: branch, title: `${branch}: standardize branch naming` });
  const published = await runWorkflow(['publish', '--body-file', f.body, '--summary', 'standardize branch naming', '--root', f.root], { execute: f.execute });
  assert.equal(published.status, 'PUBLISHED');
  assert.equal(published.conventionVersion, 2);
  const create = f.calls.find(call => call[0] === 'gh' && call[1] === 'pr' && call[2] === 'create');
  assert.equal(create[create.indexOf('--title') + 1], `${branch}: standardize branch naming`);
  assert.equal((await f.run('status')).status, 'READY_FOR_HUMAN');
  const receipt = join(f.root, '.agent-work/naming-app.json');
  await writeFile(receipt, JSON.stringify({ pullRequests: [{ url: published.url, repository: 'example/project', number: published.pr }] }));
  await f.run('record-app-state', '--receipt', receipt);
  assert.equal((await f.run('complete')).status, 'READY_FOR_HUMAN');
});

test('fresh numbered publication is refused while full-name collisions block unnumbered work', async t => {
  for (const source of ['numbered', 'remote', 'closed', 'merged', 'incomplete']) {
    const f = await checkout(t);
    const branch = source === 'numbered' ? 'feat/099-tooling-new-work' : 'feat/tooling-new-work';
    assert.equal(spawnSync('git', ['switch', '-c', branch], { cwd: f.root, windowsHide: true }).status, 0);
    await assert.rejects(runWorkflow(['publish', '--body-file', f.body, '--summary', 'add new work', '--root', f.root], {
      execute(binary, args, cwd, timeout) {
        if (binary === 'git' && args[0] === 'ls-remote' && source === 'remote') return 'a'.repeat(40) + `\trefs/heads/${branch}`;
        if (binary === 'gh' && args[0] === 'api' && args.at(-1).includes('/pulls?') && source !== 'remote') {
          return source === 'incomplete' ? JSON.stringify([{}]) : JSON.stringify([[], [{ state: 'closed', merged_at: source === 'merged' ? '2026-10-20' : null, head: { ref: branch } }]]);
        }
        return f.execute(binary, args, cwd, timeout);
      },
    }), /numeric prefix|already exists|already used|Incomplete PR history/);
    assert.equal(f.calls.some(call => call[1] === 'push' || call[0] === process.execPath), false);
  }
});
