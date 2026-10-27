import assert from 'node:assert/strict';
import { access, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { pathToFileURL } from 'node:url';
import { cliSource, fixture, git, run } from './support/agent-context-fixture.mjs';

test('legacy UC assignment fails closed without requiring an obsolete delegation map', async (t) => {
  const current = await fixture(t);
  const result = run(current, ['assignment', '--uc', 'UC-03']);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Legacy UC assignment is disabled for LifeMate/);
  assert.match(result.stderr, /GitHub issue or PR/);
  const malformed = run(current, ['assignment', '--uc', 'UC3']);
  assert.equal(malformed.status, 1);
  assert.match(malformed.stderr, /Legacy UC assignment is disabled for LifeMate/);
  assert.doesNotMatch(malformed.stderr, /UC-03/);
  assert.equal(git(current.root, ['diff', '--', 'specs/feature/tasks.md']), '');
});

test('handoff derives canonical counts and workflow pointers from source docs', async (t) => {
  const current = await fixture(t);
  const result = run(current, ['handoff', '--tasks', 'specs/feature/tasks.md']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Canonical tasks: 1 checked; 6 open; 7 total/);
  assert.match(result.stdout, /First unchecked candidate \(not authorization\): - \[ \] T002/);
  assert.match(result.stdout, /specs\/feature\/verification\.md/);
  assert.match(result.stdout, /Step 2: Converge -> Step 3: Dual-Axis Code Review -> Step 4:/);
  assert.doesNotMatch(result.stdout, /T099/);
  assert.doesNotMatch(result.stdout, /Stale summary says/);
});

test('resume reports checkout, ledger frontier, evidence pointers and worker state without writes or granting work', async (t) => {
  const current = await fixture(t);
  const tasks = `# Tasks

## Phase 1: Foundation
- [x] T001 Complete the prerequisite.
  - **Dependencies**: None.
- [ ] T002 Ready candidate.
  - **Dependencies**: T001.
- [ ] T003 Wait for T002.
  - **Dependencies**: T002.
- [ ] T004 Wait for an external gate.
  - **Dependencies**: X04-STATE.
- [ ] T005 Missing dependency declaration.
`;
  await writeFile(current.tasksPath, tasks, 'utf8');
  await mkdir(join(current.root, 'specs/feature/contracts'), { recursive: true });
  await writeFile(join(current.root, 'specs/feature/contracts/decisions.md'), '# Decisions\n', 'utf8');
  await writeFile(join(current.root, 'docs/authorization.md'), '# Authorization source\n', 'utf8');
  await writeFile(join(current.root, 'docs/authorization-follow-up.md'), '# Follow-up source\n', 'utf8');
  const statePath = join(current.root, '.agent-work/state/active-tasks.json');
  await mkdir(dirname(statePath), { recursive: true });
  const entries = [
    {
      owner: 'worker-ready', task: 'T002', role: 'worker', status: 'active', checkout: current.root,
      summary: 'Assigned candidate', next: 'Wait for coordinator authorization',
      verification: `${'Focused pass; '.repeat(40)}full run failed; required check not run; see docs/verification/focused.md`,
      result: 'https://example.invalid/runs/42', updatedAt: '2026-10-20T10:00:00.000Z',
    },
    {
      owner: 'worker-blocked', task: 'T004', role: 'worker', status: 'blocked', checkout: current.root,
      summary: 'External dependency', next: 'Wait for X04-STATE', verification: 'Required check not run',
      updatedAt: '2026-10-20T09:00:00.000Z',
    },
    {
      owner: 'coordinator', task: 'resume-report', role: 'coordinator', status: 'active', checkout: current.root,
      summary: 'Current coordinator work', next: 'Inspect current state', verification: 'docs/verification/current.md',
      updatedAt: '2026-10-20T11:00:00.000Z',
    },
  ];
  await writeFile(statePath, `${JSON.stringify(entries, null, 2)}\n`, 'utf8');
  const stateBefore = await readFile(statePath, 'utf8');

  const result = run(current, [
    'resume', '--tasks', 'specs/feature/tasks.md',
    '--authorization', 'docs/authorization.md',
    '--authorization', 'docs/authorization-follow-up.md',
  ]);
  assert.equal(result.status, 0, result.stderr);
  assert.ok(result.stdout.includes(`Checkout: ${current.root}`));
  assert.match(result.stdout, /Branch: fixture/);
  assert.match(result.stdout, /HEAD: [0-9a-f]{40}/);
  assert.match(result.stdout, /T002 \[Phase 1: Foundation\] deps: T001 checked/);
  assert.match(result.stdout, /T003: T002 open/);
  assert.match(result.stdout, /T004: X04-STATE unresolved/);
  assert.match(result.stdout, /T005: dependencies unspecified/);
  assert.match(result.stdout, /specs\/feature\/contracts\/decisions\.md/);
  assert.match(result.stdout, /docs\/authorization\.md/);
  assert.match(result.stdout, /docs\/authorization-follow-up\.md/);
  assert.match(result.stdout, /no grant is inferred/);
  assert.match(result.stdout, /worker-ready\/T002 \[active\]/);
  assert.match(result.stdout, /worker-blocked\/T004 \[blocked\]/);
  assert.match(result.stdout, /active 1; blocked 1/);
  assert.match(result.stdout, /full run failed/);
  assert.match(result.stdout, /required check not run/);
  assert.match(result.stdout, /Required check not run/);
  assert.match(result.stdout, /focused\.md/);
  assert.match(result.stdout, /https:\/\/example\.invalid\/runs\/42/);
  assert.match(result.stdout, /never authorizes work/);
  assert.equal(await readFile(statePath, 'utf8'), stateBefore);
});

test('resume preserves porcelain status columns and formats staged renames with spaces', async (t) => {
  const current = await fixture(t);
  await writeFile(join(current.root, 'docs/spec.md'), '# Unstaged edit\n', 'utf8');
  git(current.root, ['add', '--', 'untracked.txt']);

  const first = run(current, ['resume'], current.root);
  assert.equal(first.status, 0, first.stderr);
  assert.match(first.stdout, /^ {3}M docs\/spec\.md$/m);
  assert.match(first.stdout, /^ {2}A {2}untracked\.txt$/m);

  git(current.root, ['mv', '--', 'src/declared file.ts', 'src/renamed file.ts']);
  const renamed = run(current, ['resume'], current.root);
  assert.equal(renamed.status, 0, renamed.stderr);
  assert.match(renamed.stdout, /Working tree: 4 changed path\(s\)/);
  assert.match(renamed.stdout, /^ {2}R {2}src\/declared file\.ts -> src\/renamed file\.ts$/m);
  assert.doesNotMatch(renamed.stdout, /^ {2}src\/declared file\.ts$/m);
});

test('resume canonicalizes aliased checkouts, skips missing checkouts, and reports reassigned workers', async (t) => {
  const current = await fixture(t);
  const alias = current.root + '-alias';
  await symlink(current.root, alias, process.platform === 'win32' ? 'junction' : 'dir');
  t.after(async () => rm(alias, { recursive: true, force: true }));

  const statePath = join(current.root, '.agent-work/state/active-tasks.json');
  await mkdir(join(current.root, '.agent-work/state'), { recursive: true });
  const entries = [
    {
      owner: 'aliased-worker', task: 'T002', role: 'worker', status: 'handed-off', checkout: alias,
      summary: 'Assignment recorded through a path alias', next: 'Await review',
    },
    {
      owner: 'missing-checkout', task: 'resume-report', role: 'coordinator', status: 'active',
      summary: 'Legacy record has no checkout', next: 'Retain as evidence only',
    },
    {
      owner: 'reassigned-worker', task: 'T002', role: 'worker', status: 'reassigned', checkout: current.root,
      summary: 'Assignment has a terminal reassigned status', next: 'No further work',
    },
  ];
  await writeFile(statePath, JSON.stringify(entries, null, 2) + '\n', 'utf8');

  const result = run(current, ['resume', '--tasks', 'specs/feature/tasks.md'], current.root);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /handed-off 1; completed 0; reassigned 1/);
  assert.match(result.stdout, /aliased-worker\/T002 \[handed-off\]/);
  assert.doesNotMatch(result.stdout, /missing-checkout\/resume-report/);
  assert.doesNotMatch(result.stdout, /reassigned-worker\/T002/);
});

test('resume without a ledger or shared state reports the absence without creating state', async (t) => {
  const current = await fixture(t);
  const result = run(current, ['resume']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Task ledger: not supplied/);
  assert.match(result.stdout, /shared store not present/);
  await assert.rejects(access(join(current.root, '.agent-work')), { code: 'ENOENT' });
});

test('resume retries a busy shared store once and leaves its lock untouched', async (t) => {
  const current = await fixture(t);
  const stateDirectory = join(current.root, '.agent-work/state');
  const statePath = join(stateDirectory, 'active-tasks.json');
  const lockPath = join(stateDirectory, 'active-task.lock');
  await mkdir(stateDirectory, { recursive: true });
  await writeFile(statePath, '[]\n', 'utf8');
  await writeFile(lockPath, 'another writer\n', 'utf8');

  const result = run(current, ['resume']);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /being updated|changed during the read/);
  assert.equal(await readFile(lockPath, 'utf8'), 'another writer\n');
});

test('explicit root works when the CLI is dispatched from another checkout', async (t) => {
  const current = await fixture(t);
  const result = spawnSync(
    process.execPath,
    [cliSource, 'handoff', '--tasks', 'specs/feature/tasks.md', '--root', current.root],
    { cwd: tmpdir(), encoding: 'utf8', windowsHide: true },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.ok(result.stdout.includes(`Checkout: ${current.root}`));
});

test('CLI runs through a path alias and stays inert when imported with an unresolved argv path', async (t) => {
  const current = await fixture(t);
  const importer = join(current.root, 'import-agent-context.mjs');
  await writeFile(
    importer,
    'process.argv[1] = "missing-agent-context.mjs";\nawait import(' +
      JSON.stringify(pathToFileURL(current.cliPath).href) + ');\n',
    'utf8',
  );
  const imported = spawnSync(process.execPath, [importer], {
    cwd: current.root,
    encoding: 'utf8',
    windowsHide: true,
  });
  assert.equal(imported.status, 0, imported.stderr);
  assert.equal(imported.stdout, '');

  let aliasPath;
  if (process.platform === 'win32') {
    const separator = current.cliPath.lastIndexOf('\\');
    const aliasDirectory = current.cliPath.slice(0, separator + 1).replace(/[A-Za-z]/g, (letter) =>
      letter === letter.toLowerCase() ? letter.toUpperCase() : letter.toLowerCase(),
    );
    aliasPath = aliasDirectory + current.cliPath.slice(separator + 1);
  } else {
    aliasPath = current.cliPath + '.alias';
    await symlink(current.cliPath, aliasPath);
    t.after(async () => rm(aliasPath, { force: true }));
  }
  const invoked = spawnSync(process.execPath, [aliasPath, '--help'], {
    cwd: current.root,
    encoding: 'utf8',
    windowsHide: true,
  });
  assert.equal(invoked.status, 0, invoked.stderr);
  assert.equal(invoked.stdout.match(/Usage:/g)?.length, 1);
});

test('task context is limited to the requested task, its phase notes, matching plan lines, and referenced ports', async (t) => {
  const current = await fixture(t);
  const taskLedger = await readFile(current.tasksPath, 'utf8');
  await writeFile(
    current.tasksPath,
    taskLedger.replace(
      '- [ ] T018 [US1] A different task in another file.',
      '- [ ] T018 [US1] A different task in another file.\n  - **Dependencies**: T017.',
    ),
    'utf8',
  );
  const selected = run(current, [
    'task',
    '--tasks',
    'specs/feature/tasks.md',
    '--task',
    'T017',
    '--plan',
    'specs/feature/plan.md',
  ]);
  assert.equal(selected.status, 0, selected.stderr);
  assert.match(selected.stdout, /Phase: ## Phase 2: US1 work/);
  assert.match(selected.stdout, /Canonical task line:\n- \[ \] T017 \[P\] \[US1\]/);
  assert.match(
    selected.stdout,
    /Independent US1 test: unresolved provider outcomes remain pending/,
  );
  assert.doesNotMatch(selected.stdout, /\*\*Dependencies\*\*: T017/);
  assert.match(selected.stdout, /US1 T017-T032 follows foundation/);
  assert.match(selected.stdout, /payment-fulfillment\.saga\.ts/);
  assert.doesNotMatch(selected.stdout, /A different task in another file/);
  assert.doesNotMatch(selected.stdout, /Do not include this material/);
  assert.doesNotMatch(selected.stdout, /unrelated\.service\.ts/);

  const dependencyOwner = run(current, [
    'task',
    '--tasks',
    'specs/feature/tasks.md',
    '--task',
    'T018',
  ]);
  assert.equal(dependencyOwner.status, 0, dependencyOwner.stderr);
  assert.match(dependencyOwner.stdout, /\*\*Dependencies\*\*: T017/);

  const database = run(current, [
    'task',
    '--tasks',
    'specs/feature/tasks.md',
    '--task',
    'T006',
    '--plan',
    'specs/feature/plan.md',
  ]);
  assert.equal(database.status, 0, database.stderr);
  assert.match(database.stdout, /schema\.prisma/);
  assert.match(database.stdout, /20261007000000_fulfillment_recovery\/migration\.sql/);
  assert.doesNotMatch(database.stdout, /001_seed_data\.sql/);
  assert.doesNotMatch(database.stdout, /unrelated database note/);

  const checkout = run(current, [
    'task',
    '--tasks',
    'specs/feature/tasks.md',
    '--task',
    'T030',
    '--plan',
    'specs/feature/plan.md',
  ]);
  assert.equal(checkout.status, 0, checkout.stderr);
  assert.match(checkout.stdout, /checkout\/\[intentId\]\/payment\/page\.tsx/);
  assert.doesNotMatch(checkout.stdout, /\[otherId\]/);

  const ports = run(current, [
    'task',
    '--tasks',
    'specs/feature/tasks.md',
    '--task',
    'T021',
    '--plan',
    'specs/feature/plan.md',
  ]);
  assert.equal(ports.status, 0, ports.stderr);
  assert.match(ports.stdout, /PAYMENT_GATEWAY_PORT/);
  assert.match(ports.stdout, /FULFILLMENT_GATEWAY_PORT/);
  assert.doesNotMatch(ports.stdout, /OTHER_PORT/);
});

test('task IDs must be canonical and present, and duplicate canonical IDs fail', async (t) => {
  const current = await fixture(t);
  const invalid = run(current, ['task', '--tasks', 'specs/feature/tasks.md', '--task', 'T17']);
  assert.equal(invalid.status, 1);
  assert.match(invalid.stderr, /Invalid task ID T17/);
  const unknown = run(current, ['task', '--tasks', 'specs/feature/tasks.md', '--task', 'T999']);
  assert.equal(unknown.status, 1);
  assert.match(unknown.stderr, /Unknown task ID T999/);
  assert.match(unknown.stderr, /Canonical IDs: T001, T002, T006, T030, T017, T018, T021/);
  const unknownOption = run(current, [
    'handoff',
    '--tasks',
    'specs/feature/tasks.md',
    '--surprise',
  ]);
  assert.equal(unknownOption.status, 1);
  assert.match(unknownOption.stderr, /Unknown option or positional argument: --surprise/);

  await writeFile(current.tasksPath, '# Tasks\n- [ ] T017 first\n- [x] T017 duplicate\n', 'utf8');
  const duplicate = run(current, ['handoff', '--tasks', 'specs/feature/tasks.md']);
  assert.equal(duplicate.status, 1);
  assert.match(duplicate.stderr, /Duplicate canonical task ID T017/);
});

test('snapshot hashes only declared files and verifies unchanged files across unrelated HEAD drift', async (t) => {
  const current = await fixture(t);
  const created = run(current, ['snapshot', '--files', 'src/declared file.ts', 'docs/spec.md']);
  assert.equal(created.status, 0, created.stderr);
  const snapshot = JSON.parse(created.stdout);
  assert.equal(snapshot.schemaVersion, 1);
  assert.equal(snapshot.root, current.root);
  assert.equal(snapshot.branch, 'fixture');
  assert.equal(snapshot.files.length, 2);
  assert.deepEqual(
    snapshot.files.map((entry) => entry.path),
    ['src/declared file.ts', 'docs/spec.md'],
  );
  assert.equal(created.stdout.includes('private.env'), false);
  assert.equal(created.stdout.includes('untracked.txt'), false);
  const snapshotPath = join(current.root, 'snapshot.json');
  await writeFile(snapshotPath, `\uFEFF${JSON.stringify(snapshot, null, 2)}`, 'utf8');

  await writeFile(join(current.root, 'unrelated.txt'), 'unrelated commit\n', 'utf8');
  git(current.root, ['add', '--', 'unrelated.txt']);
  git(current.root, ['commit', '-m', 'unrelated change']);
  const verified = run(current, ['verify', '--snapshot', 'snapshot.json']);
  assert.equal(verified.status, 0, verified.stderr);
  assert.match(verified.stdout, /HEAD drift:/);
  assert.match(verified.stdout, /2\/2 unchanged/);

  await writeFile(
    join(current.root, 'src', 'declared file.ts'),
    'export const value = 2;\n',
    'utf8',
  );
  const stale = run(current, ['verify', '--snapshot', 'snapshot.json']);
  assert.equal(stale.status, 1);
  assert.match(stale.stderr, /Changed: src\/declared file\.ts/);
  assert.match(stale.stderr, /Snapshot is stale/);
});

test('verify rejects missing files, malformed snapshots, workspace mismatch, and escaping paths', async (t) => {
  const current = await fixture(t);
  const created = run(current, ['snapshot', '--files', 'docs/spec.md']);
  assert.equal(created.status, 0, created.stderr);
  const snapshot = JSON.parse(created.stdout);
  const snapshotPath = join(current.root, 'snapshot.json');

  await writeFile(snapshotPath, '{', 'utf8');
  const malformed = run(current, ['verify', '--snapshot', 'snapshot.json']);
  assert.equal(malformed.status, 1);
  assert.match(malformed.stderr, /Invalid snapshot JSON/);

  snapshot.files[0].path = 'missing.md';
  await writeFile(snapshotPath, JSON.stringify(snapshot), 'utf8');
  const missing = run(current, ['verify', '--snapshot', 'snapshot.json']);
  assert.equal(missing.status, 1);
  assert.match(missing.stderr, /Missing: missing\.md/);

  snapshot.files[0].path = '../outside.md';
  await writeFile(snapshotPath, JSON.stringify(snapshot), 'utf8');
  const escaping = run(current, ['verify', '--snapshot', 'snapshot.json']);
  assert.equal(escaping.status, 1);
  assert.match(escaping.stderr, /escapes the checkout root/);

  snapshot.files[0].path = 'docs/spec.md';
  snapshot.root = join(current.root, 'another-checkout');
  await writeFile(snapshotPath, JSON.stringify(snapshot), 'utf8');
  const mismatch = run(current, ['verify', '--snapshot', 'snapshot.json']);
  assert.equal(mismatch.status, 1);
  assert.match(mismatch.stderr, /Snapshot workspace mismatch/);
});
