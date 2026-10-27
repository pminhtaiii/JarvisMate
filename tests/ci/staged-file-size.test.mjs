import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmod, copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { installGitHooks } from '../../scripts/agents/install-git-hooks.mjs';

const checker = resolve(dirname(fileURLToPath(import.meta.url)), '../../scripts/ci/check-staged-file-size.mjs');
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

async function repository(t) {
  const root = await mkdtemp(join(tmpdir(), 'staged-size-guard-'));
  assert.equal(dirname(root), resolve(tmpdir()));
  t.after(() => rm(root, { recursive: true, force: true }));
  const env = { ...process.env, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: join(root, 'empty.gitconfig') };
  await writeFile(env.GIT_CONFIG_GLOBAL, '');
  const runGit = (cwd, ...args) => spawnSync('git', args, { cwd, env, encoding: 'utf8', windowsHide: true });
  const git = (...args) => {
    const result = runGit(root, ...args);
    assert.equal(result.status, 0, result.stderr);
    return result.stdout.trim();
  };
  git('init', '--quiet');
  git('config', 'user.name', 'Guard test');
  git('config', 'user.email', 'guard@example.test');
  git('commit', '--quiet', '--allow-empty', '-m', 'baseline');
  const check = (...args) => spawnSync(process.execPath, [checker, '--root', root, ...args], { cwd: root, encoding: 'utf8', windowsHide: true, timeout: 30_000 });
  const commit = () => git('commit', '--quiet', '-m', 'fixture change');
  return { root, env, git, runGit, check, commit };
}

test('the checker uses staged index bytes and allows exactly 20,000 bytes', async (t) => {
  const { root, git, check } = await repository(t);
  const unsupportedScope = check('--base', 'HEAD');
  assert.equal(unsupportedScope.status, 1, 'the checker does not accept a tree-range mode');
  assert.match(unsupportedScope.stderr, /Usage:/);

  const file = join(root, 'source with spaces.ts');
  await writeFile(file, 'x'.repeat(20_000));
  git('add', '--', 'source with spaces.ts');
  assert.equal(check().status, 0, 'the 20,000-byte boundary is allowed');

  await writeFile(file, 'x'.repeat(30_000));
  assert.equal(check().status, 0, 'unstaged working-tree bytes are ignored');

  await writeFile(file, 'x'.repeat(20_001));
  git('add', '--', 'source with spaces.ts');
  await writeFile(file, 'x');
  const result = check();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /source with spaces\.ts/);
  assert.match(result.stderr, /20,001 bytes/);
  assert.match(result.stderr, /Split each file along a cohesive responsibility/);
  assert.match(result.stderr, /pnpm run check:staged-size/);
});

test('known generated outputs, lockfiles, and binary blobs are skipped without exempting contracts', async (t) => {
  const { root, git, check } = await repository(t);
  const tooLarge = Buffer.from('a'.repeat(20_001));
  const skipped = [
    'nested/pnpm-lock.yaml', 'node_modules/vendor/file.ts', 'dist/bundle.js', 'coverage/report.txt',
    'src/api.generated.ts', 'src/schema.g.ts',
  ];
  for (const path of skipped) {
    const file = join(root, path);
    await mkdir(dirname(file), { recursive: true });
    await writeFile(file, tooLarge);
    git('add', '--', path);
  }
  const binary = Buffer.concat([tooLarge, Buffer.from([0])]);
  await mkdir(join(root, 'src/contracts'), { recursive: true });
  await writeFile(join(root, 'src/binary.dat'), binary);
  await writeFile(join(root, 'src/contracts/authored.ts'), tooLarge);
  git('add', '--', 'src/binary.dat', 'src/contracts/authored.ts');

  const result = check();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /src\/contracts\/authored\.ts/);
  for (const path of skipped) assert.doesNotMatch(result.stderr, new RegExp(path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.doesNotMatch(result.stderr, /binary\.dat/);
});

test('the unchanged Spec Kit 1.2.3 helper is allowed but edits and other paths remain checked', async (t) => {
  const { root, git, check } = await repository(t);
  const relativePath = '.specify/scripts/powershell/common.ps1';
  const upstream = (await readFile(join(repoRoot, relativePath), 'utf8')).replace(/\r\n/g, '\n');
  await mkdir(join(root, '.specify/scripts/powershell'), { recursive: true });
  await writeFile(join(root, relativePath), upstream);
  git('add', '--', relativePath);
  assert.equal(check().status, 0, 'the pinned upstream helper is unchanged');

  await writeFile(join(root, relativePath), `${upstream}\n# local modification\n`);
  git('add', '--', relativePath);
  assert.equal(check().status, 1, 'changes to the helper remain subject to the size limit');

  await writeFile(join(root, relativePath), upstream);
  await writeFile(join(root, 'other-helper.ps1'), upstream);
  git('add', '--', relativePath, 'other-helper.ps1');
  const result = check();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /other-helper\.ps1/);
  assert.doesNotMatch(result.stderr, /"\.specify\/scripts\/powershell\/common\.ps1"/);
});

test('the supplied competition catalogs are allowed only at their original paths and revisions', async (t) => {
  const { root, git, check } = await repository(t);
  const paths = ['tools/train_tools_catalog.json', 'tools/public_test_tools_catalog.json'];
  const originals = new Map();
  await mkdir(join(root, 'tools'), { recursive: true });
  for (const path of paths) {
    const content = (await readFile(join(repoRoot, path), 'utf8')).replace(/\r\n/g, '\n');
    originals.set(path, content);
    await writeFile(join(root, path), content);
    git('add', '--', path);
  }
  assert.equal(check().status, 0, 'both original catalogs are accepted');

  for (const path of paths) {
    await writeFile(join(root, path), `${originals.get(path)}\n`);
    git('add', '--', path);
    assert.equal(check().status, 1, `edits to ${path} remain checked`);
    await writeFile(join(root, path), originals.get(path));
    git('add', '--', path);
  }

  await writeFile(join(root, 'other-catalog.json'), originals.get(paths[0]));
  git('add', '--', 'other-catalog.json');
  const result = check();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /other-catalog\.json/);
});

test('top-level tests and specs are exempt by normalized path while implementation files remain checked', async (t) => {
  const { root, git, check } = await repository(t);
  const paths = ['TESTS/foo.test.ts', 'SPECS/foo/spec.md', 'src/foo.ts', 'nested/tests/foo.test.ts'];
  for (const path of paths) {
    const file = join(root, path);
    await mkdir(dirname(file), { recursive: true });
    await writeFile(file, 'x'.repeat(20_001));
    git('add', '--', path);
  }

  const result = check();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /src\/foo\.ts/);
  assert.match(result.stderr, /nested\/tests\/foo\.test\.ts/);
  assert.doesNotMatch(result.stderr, /TESTS\/foo\.test\.ts/);
  assert.doesNotMatch(result.stderr, /SPECS\/foo\/spec\.md/);
});

test('during a merge only exact parent mode and blob pairs pass, including renamed paths', async (t) => {
  const { root, git, check } = await repository(t);
  const base = git('rev-parse', 'HEAD');

  git('checkout', '--quiet', '-b', 'incoming');
  await writeFile(join(root, 'incoming parent.ts'), 'i'.repeat(20_001));
  git('add', '--', 'incoming parent.ts');
  git('commit', '--quiet', '-m', 'incoming parent');

  git('checkout', '--quiet', '--detach', base);
  git('checkout', '--quiet', '-b', 'ours');
  await writeFile(join(root, 'head parent.ts'), 'h'.repeat(20_001));
  git('add', '--', 'head parent.ts');
  git('commit', '--quiet', '-m', 'head parent');
  git('merge', '--no-ff', '--no-commit', 'incoming');
  git('mv', '--', 'head parent.ts', 'renamed head parent.ts');

  const exactParents = check();
  assert.equal(exactParents.status, 0, exactParents.stderr);

  await copyFile(join(root, 'incoming parent.ts'), join(root, 'mode mismatch.ts'));
  git('add', '--', 'mode mismatch.ts');
  git('update-index', '--chmod=+x', '--', 'mode mismatch.ts');
  const wrongMode = check();
  assert.equal(wrongMode.status, 1);
  assert.match(wrongMode.stderr, /mode mismatch\.ts/);
  assert.doesNotMatch(wrongMode.stderr, /incoming parent\.ts|renamed head parent\.ts/);

  git('rm', '--cached', '--force', '--quiet', '--', 'mode mismatch.ts');
  assert.equal(check().status, 0, 'the exact parent mode and blob pairs stay exempt');
});

test('an oversized edited merge resolution is still checked', async (t) => {
  const { root, git, runGit, check } = await repository(t);
  await mkdir(join(root, 'src'));
  await writeFile(join(root, 'src/merge.ts'), 'base');
  git('add', '--', 'src/merge.ts');
  git('commit', '--quiet', '-m', 'base resolution');
  const base = git('rev-parse', 'HEAD');

  git('checkout', '--quiet', '-b', 'incoming');
  await writeFile(join(root, 'src/merge.ts'), 'i'.repeat(20_001));
  git('add', '--', 'src/merge.ts');
  git('commit', '--quiet', '-m', 'incoming resolution');

  git('checkout', '--quiet', '--detach', base);
  git('checkout', '--quiet', '-b', 'ours');
  await writeFile(join(root, 'src/merge.ts'), 'o'.repeat(20_001));
  git('add', '--', 'src/merge.ts');
  git('commit', '--quiet', '-m', 'ours resolution');
  const merge = runGit(root, 'merge', '--no-ff', '--no-commit', 'incoming');
  assert.equal(merge.status, 1, merge.stdout + merge.stderr);
  assert.match(merge.stdout + merge.stderr, /CONFLICT/);

  await writeFile(join(root, 'src/merge.ts'), 'r'.repeat(20_001));
  git('add', '--', 'src/merge.ts');
  const result = check();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /src\/merge\.ts/);
  assert.match(result.stderr, /20,001 bytes/);
});

test('matching a parent blob outside a merge does not grant an exemption', async (t) => {
  const { root, git, check } = await repository(t);
  const contents = 'p'.repeat(20_001);
  await writeFile(join(root, 'parent.ts'), contents);
  git('add', '--', 'parent.ts');
  git('commit', '--quiet', '-m', 'large parent file');
  await copyFile(join(root, 'parent.ts'), join(root, 'new copy.ts'));
  git('add', '--', 'new copy.ts');

  const result = check();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /new copy\.ts/);
});

test('the checker uses a linked worktree MERGE_HEAD path', async (t) => {
  const { root, git, runGit } = await repository(t);
  const base = git('rev-parse', 'HEAD');
  git('checkout', '--quiet', '-b', 'incoming');
  await writeFile(join(root, 'large incoming.ts'), 'w'.repeat(20_001));
  git('add', '--', 'large incoming.ts');
  git('commit', '--quiet', '-m', 'incoming large file');

  const worktree = join(root, 'linked-worktree');
  const added = runGit(root, 'worktree', 'add', '--quiet', '--detach', worktree, base);
  assert.equal(added.status, 0, added.stderr);
  const merge = runGit(worktree, 'merge', '--no-ff', '--no-commit', 'incoming');
  assert.equal(merge.status, 0, merge.stdout + merge.stderr);

  const gitPath = runGit(worktree, 'rev-parse', '--git-path', 'MERGE_HEAD');
  assert.equal(gitPath.status, 0, gitPath.stderr);
  const mainGitPath = runGit(root, 'rev-parse', '--git-path', 'MERGE_HEAD');
  assert.equal(mainGitPath.status, 0, mainGitPath.stderr);
  assert.notEqual(resolve(worktree, gitPath.stdout.trim()), resolve(root, mainGitPath.stdout.trim()));
  const result = spawnSync(process.execPath, [checker, '--root', worktree], {
    cwd: worktree, encoding: 'utf8', windowsHide: true, timeout: 30_000,
  });
  assert.equal(result.status, 0, result.stderr);
});

test('malformed MERGE_HEAD refs fail closed', async (t) => {
  const { root, git, check } = await repository(t);
  await writeFile(join(root, 'large.ts'), 'm'.repeat(20_001));
  git('add', '--', 'large.ts');
  const mergeHeadPath = resolve(root, git('rev-parse', '--git-path', 'MERGE_HEAD'));
  await writeFile(mergeHeadPath, 'not-a-commit\n');

  const result = check();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Invalid Git MERGE_HEAD/);
});

test('renames and copies check their destination; staged deletions are ignored', async (t) => {
  const { root, git, check } = await repository(t);
  await writeFile(join(root, 'rename old.ts'), 'r'.repeat(20_000));
  await writeFile(join(root, 'copy source.ts'), 'c'.repeat(20_000));
  await writeFile(join(root, 'delete large.ts'), 'd'.repeat(20_001));
  git('add', '--', 'rename old.ts', 'copy source.ts', 'delete large.ts');
  git('commit', '--quiet', '-m', 'oversize base files are outside the staged diff');

  git('mv', '--', 'rename old.ts', 'rename target with spaces.ts');
  await writeFile(join(root, 'rename target with spaces.ts'), 'r'.repeat(20_000) + 'x');
  await writeFile(join(root, 'copy source.ts'), 'c'.repeat(19_999) + 'd');
  await writeFile(join(root, 'copy target with spaces.ts'), 'c'.repeat(20_000) + 'x');
  git('rm', '--quiet', '--', 'delete large.ts');
  git('add', '--', 'rename target with spaces.ts', 'copy source.ts', 'copy target with spaces.ts');

  const result = check();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /rename target with spaces\.ts/);
  assert.match(result.stderr, /copy target with spaces\.ts/);
  assert.doesNotMatch(result.stderr, /delete large\.ts/);

  git('reset', '--quiet');
  git('rm', '--cached', '--quiet', '--', 'delete large.ts');
  assert.equal(check().status, 0, 'deleting an over-limit old blob is allowed');
});

test('pnpm setup installs the repository hook and preserves custom Git hook paths', async (t) => {
  const { root, env, git } = await repository(t);
  await mkdir(join(root, '.githooks'));
  await copyFile(resolve(repoRoot, '.githooks/pre-commit'), join(root, '.githooks/pre-commit'));
  await chmod(join(root, '.githooks/pre-commit'), 0o755);
  await mkdir(join(root, 'scripts/ci'), { recursive: true });
  await copyFile(checker, join(root, 'scripts/ci/check-staged-file-size.mjs'));
  assert.deepEqual(installGitHooks(root, env), { status: 'installed' });
  assert.equal(git('config', '--get', 'core.hooksPath'), '.githooks');
  assert.deepEqual(installGitHooks(root, env), { status: 'already-configured' });

  await writeFile(join(root, 'too-large.ts'), 'x'.repeat(20_001));
  git('add', '--', 'too-large.ts');
  const blocked = spawnSync('git', ['commit', '--quiet', '-m', 'must be blocked'], { cwd: root, env, encoding: 'utf8', windowsHide: true });
  assert.notEqual(blocked.status, 0, blocked.stdout);
  assert.match(blocked.stdout + blocked.stderr, /Split each file along a cohesive responsibility/);

  await writeFile(join(root, 'too-large.ts'), 'small');
  git('add', '--', 'too-large.ts');
  const allowed = spawnSync('git', ['commit', '--quiet', '-m', 'small file passes'], { cwd: root, env, encoding: 'utf8', windowsHide: true });
  assert.equal(allowed.status, 0, allowed.stderr);

  git('config', '--local', 'core.hooksPath', 'custom-hooks');
  assert.deepEqual(installGitHooks(root, env), { status: 'custom-path-preserved', path: 'custom-hooks' });
  assert.equal(git('config', '--get', 'core.hooksPath'), 'custom-hooks');
});
