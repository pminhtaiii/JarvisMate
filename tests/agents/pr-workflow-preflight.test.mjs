import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { readFile, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { runWorkflow } from '../../scripts/agents/pr-workflow.mjs';
import { checkout } from './support/pr-workflow-fixture.mjs';

test('preflight reports freshness, dirty paths, naming, and size without publishing', async (t) => {
  const f = await checkout(t);
  const first = await f.run('preflight');
  assert.equal(first.status, 'READY_TO_WORK');
  assert.equal(first.ahead, 1);
  assert.equal(first.behind, 0);
  assert.equal(first.size.reviewable, 1);
  assert.equal(f.calls.some((call) => call[0] === 'gh' || call.includes('push') || call[0] === process.execPath), false);
  await writeFile(join(f.root, 'unfinished.md'), 'retain this work\n');
  const dirty = await f.run('preflight');
  assert.equal(dirty.status, 'BLOCKED');
  assert.match(dirty.dirty, /unfinished\.md/);
  const git = (...args) => {
    const result = spawnSync('git', args, { cwd: f.root, encoding: 'utf8', windowsHide: true });
    assert.equal(result.status, 0, result.stderr); return result.stdout.trim();
  };
  const advanced = git('commit-tree', 'HEAD^{tree}', '-p', 'origin/development', '-m', 'base advances');
  git('update-ref', 'refs/remotes/origin/development', advanced);
  assert.equal((await f.run('preflight')).behind, 1);
  git('checkout', '-b', 'wrong-name');
  assert.equal((await f.run('preflight')).branchValid, false);
  assert.equal(await readFile(join(f.root, 'unfinished.md'), 'utf8'), 'retain this work\n');
  await assert.rejects(runWorkflow(['preflight', '--root', f.root], { execute(binary, args, cwd, timeout) {
    if (binary === 'git' && args[0] === 'fetch') throw new Error('Fetch unavailable');
    return f.execute(binary, args, cwd, timeout);
  } }), /Fetch unavailable/);
});

test('preflight measures the fetched development tip even without a tracking refspec', async (t) => {
  const f = await checkout(t);
  const git = (...args) => {
    const result = spawnSync('git', args, { cwd: f.root, encoding: 'utf8', windowsHide: true });
    assert.equal(result.status, 0, result.stderr); return result.stdout.trim();
  };
  const remote = join(f.root, '.agent-work/remote.git');
  git('init', '--bare', '--quiet', remote);
  git('push', remote, 'refs/remotes/origin/development:refs/heads/development');
  const advanced = git('commit-tree', 'HEAD^{tree}', '-p', 'origin/development', '-m', 'remote base advances');
  git('push', remote, `${advanced}:refs/heads/development`);
  git('config', `url.${remote.split('\\').join('/')}.insteadOf`, 'https://github.com/example/project.git');
  git('config', '--unset-all', 'remote.origin.fetch');
  const report = await runWorkflow(['preflight', '--root', f.root], { execute(binary, args, cwd, timeout) {
    // Keep the origin identity seam GitHub-shaped while real Git fetches a local remote.
    if (binary === 'git' && args[0] === 'remote' && args[1] === 'get-url') return 'https://github.com/example/project.git';
    const result = spawnSync(binary, args, { cwd, timeout, encoding: 'utf8', windowsHide: true });
    assert.equal(result.status, 0, result.stderr); return result.stdout.trim();
  } });
  assert.equal(report.base, advanced);
  assert.equal(report.behind, 1);
  assert.equal(report.status, 'BLOCKED');
});

test('a failed local gate never pushes or opens a PR', async (t) => {
  const f = await checkout(t); f.fail();
  await assert.rejects(f.run('publish', '--body-file', f.body), /Local gate failed/);
  assert.equal(f.calls.some((call) => call[0] === 'git' && call[1] === 'push' || call[0] === 'gh' && call[2] === 'create'), false);
});

test('configured paired publication refuses a missing submission remote before primary gates or writes', async t => {
  const f = await checkout(t);
  await writeFile(join(f.root, 'publication-targets.json'), JSON.stringify({ schemaVersion: 1, submission: { remote: 'submission', base: 'development' } }));
  const committed = spawnSync('git', ['add', 'publication-targets.json'], { cwd: f.root, windowsHide: true }); assert.equal(committed.status, 0);
  const saved = spawnSync('git', ['commit', '--quiet', '-m', 'enable paired publication'], { cwd: f.root, windowsHide: true }); assert.equal(saved.status, 0);
  f.calls.length = 0;
  await assert.rejects(f.run('publish', '--body-file', f.body), /submission|No such remote/);
  assert.equal(f.calls.some(call => call[0] === process.execPath || call[1] === 'push' || call[0] === 'gh' && ['create', 'edit'].includes(call[2])), false);
});

test('closed PRs skip expensive gates and PR changes during gates prevent push', async (t) => {
  const f = await checkout(t);
  await f.run('publish', '--body-file', f.body);
  f.e.pr.state = 'MERGED';
  f.calls.length = 0;
  await assert.rejects(f.run('publish', '--body-file', f.body), /closed or replaced/);
  assert.equal(f.calls.some(call => call[0] === process.execPath || call[1] === 'push'), false);
  f.e.pr.state = 'OPEN';
  for (const change of ['closed', 'head']) {
    f.calls.length = 0;
    const oldHead = f.e.pr.headRefOid;
    await assert.rejects(runWorkflow(['publish', '--body-file', f.body, '--summary', 'fix lifecycle race', '--root', f.root], {
      execute(binary, args, cwd, timeout) {
        const output = f.execute(binary, args, cwd, timeout);
        if (binary === process.execPath && args[0].endsWith('check-runtime.mjs')) {
          if (change === 'closed') f.e.pr.state = 'MERGED';
          else f.e.pr.headRefOid = 'external-commit';
        }
        return output;
      },
    }), /closed or replaced|changed during local gates/);
    assert.equal(f.calls.some(call => call[1] === 'push' || call[0] === 'gh' && ['edit', 'create'].includes(call[2])), false);
    f.e.pr.state = 'OPEN'; f.e.pr.headRefOid = oldHead;
  }
});

test('prepare-next preserves the merged feature and refuses dirty, unmerged or existing targets', async t => {
  const f = await checkout(t);
  await f.run('publish', '--body-file', f.body);
  const target = 'feat/tooling-next-work';
  await assert.rejects(f.run('prepare-next', '--branch', target), /merged/);
  f.e.pr.state = 'MERGED';
  await writeFile(join(f.root, 'dirty.md'), 'keep me');
  await assert.rejects(f.run('prepare-next', '--branch', target), /clean/);
  assert.equal(await readFile(join(f.root, 'dirty.md'), 'utf8'), 'keep me');
  await rm(join(f.root, 'dirty.md'));
  await assert.rejects(f.run('prepare-next', '--branch', 'feat/010-tooling-example'), /scope/);
  const source = f.e.head;
  const result = await f.run('prepare-next', '--branch', target);
  assert.equal(result.branch, target);
  assert.equal(result.status, 'READY_TO_WORK');
  const git = (...args) => spawnSync('git', args, { cwd: f.root, encoding: 'utf8', windowsHide: true });
  assert.equal(git('rev-parse', 'feat/010-tooling-example').stdout.trim(), source);
  assert.equal(git('rev-parse', 'HEAD').stdout.trim(), git('rev-parse', 'origin/development').stdout.trim());
  assert.notEqual(git('rev-parse', '--abbrev-ref', '@{upstream}').status, 0, 'new branch must not track development');
  assert.equal(f.calls.some(call => ['reset', 'clean'].includes(call[1]) || call.includes('--force')), false);
});

test('publication tracks the remote feature and post-squash preparation survives its remote deletion', async t => {
  const f = await checkout(t);
  const git = (...args) => {
    const result = spawnSync('git', args, { cwd: f.root, encoding: 'utf8', windowsHide: true });
    assert.equal(result.status, 0, result.stderr); return result.stdout.trim();
  };
  const remote = join(f.root, '.agent-work/remote.git');
  git('init', '--bare', '--quiet', remote);
  git('push', remote, 'refs/remotes/origin/development:refs/heads/development');
  git('config', `url.${remote.split('\\').join('/')}.insteadOf`, 'https://github.com/example/project.git');
  const execute = (binary, args, cwd, timeout) => {
    if (binary !== 'git') return f.execute(binary, args, cwd, timeout);
    if (args[0] === 'remote' && args[1] === 'get-url') return 'https://github.com/example/project.git';
    return git(...args);
  };
  await runWorkflow(['publish', '--root', f.root, '--body-file', f.body, '--summary', 'configure remote tracking'], { execute });
  assert.equal(git('rev-parse', '--abbrev-ref', '@{upstream}'), 'origin/feat/010-tooling-example');
  const source = git('rev-parse', 'HEAD');
  const squash = git('commit-tree', 'HEAD^{tree}', '-p', 'origin/development', '-m', 'squash merge');
  git('push', remote, `${squash}:refs/heads/development`);
  git('push', remote, '--delete', 'feat/010-tooling-example');
  f.e.pr.state = 'MERGED';
  const result = await runWorkflow(['prepare-next', '--root', f.root, '--branch', 'feat/tooling-fresh'], { execute });
  assert.equal(result.head, squash);
  assert.equal(git('rev-parse', 'feat/010-tooling-example'), source);
  assert.equal(git('status', '--porcelain'), '');
});
