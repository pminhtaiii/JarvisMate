import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { copyFile, mkdir, mkdtemp, readdir, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
export const cliSource = resolve(repositoryRoot, 'scripts/agents/agent-context.mjs');
const storeSource = resolve(repositoryRoot, 'scripts/agents/agent-store.mjs');

export function git(root, args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim();
}

export async function fixture(t) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'agent-context path with spaces-')));
  t.after(async () => rm(root, { recursive: true, force: true }));
  const cliPath = join(root, 'scripts', 'agents', 'agent-context.mjs');
  const storePath = join(root, 'scripts', 'agents', 'agent-store.mjs');
  const tasksPath = join(root, 'specs', 'feature', 'tasks.md');
  const planPath = join(root, 'specs', 'feature', 'plan.md');
  const tasks = `# Tasks

## Phase 1: Setup
- [X] T001 Completed setup.

## Phase 2: US1 work
- [ ] T002 Candidate with no completion authority.
- [ ] T006 [US1] Add fulfillment recovery schema and migration in apps/api/prisma/schema.prisma and apps/api/prisma/migrations/20261007000000_fulfillment_recovery/migration.sql.
- [ ] T030 [US1] Preserve payment state in apps/web/app/checkout/[intentId]/payment/page.tsx.
- [ ] T017 [P] [US1] Add create/capture cases in apps/api/src/payment-fulfillment/payment-fulfillment.saga.spec.ts.
- [ ] T018 [US1] A different task in another file.
- [ ] T021 [US1] Define gateway contracts in apps/api/src/payment-fulfillment/ports/payment-gateway.port.ts and apps/api/src/payment-fulfillment/ports/fulfillment-gateway.port.ts.

Independent US1 test: unresolved provider outcomes remain pending until observed.

\`\`\`markdown
- [ ] T099 This fenced sample is not a canonical task.
\`\`\`

## Dependency Graph
US1 T017-T032 follows foundation.
[P] marks separate files without unmet prerequisites; it never authorizes simultaneous edits of the same file.
`;
  const plan = `# Plan

## Unrelated section
Do not include this material in task context.

## Target Structure
- apps/api/src/payment-fulfillment/{ports/payment-gateway.port.ts,ports/fulfillment-gateway.port.ts,payment-fulfillment.saga.ts}
- apps/api/src/payment-fulfillment/unrelated.service.ts

## Shared contracts
The API workflow depends only on PAYMENT_GATEWAY_PORT and FULFILLMENT_GATEWAY_PORT.
OTHER_PORT is unrelated to the selected task.

## Feature 030 database artifacts
- apps/api/prisma/schema.prisma
- apps/api/prisma/migrations/20261007000000_fulfillment_recovery/migration.sql
- apps/api/prisma/migrations/other_feature/001_seed_data.sql
This unrelated database note should not be copied into task context.

## Checkout payment route
- apps/web/app/checkout/[intentId]/payment/page.tsx
- apps/web/app/checkout/[otherId]/payment/page.tsx
`;
  await mkdir(dirname(cliPath), { recursive: true });
  await mkdir(dirname(tasksPath), { recursive: true });
  await mkdir(join(root, 'src'), { recursive: true });
  await mkdir(join(root, 'docs'), { recursive: true });
  await writeFile(join(root, '.gitignore'), '.agent-work/\n', 'utf8');
  await copyFile(cliSource, cliPath);
  await copyFile(storeSource, storePath);
  const companionModules = (await readdir(dirname(cliSource)))
    .filter((name) => /^agent-context-(?:common|assignment|resume|task|snapshot)\.mjs$/.test(name));
  for (const name of companionModules) await copyFile(join(dirname(cliSource), name), join(dirname(cliPath), name));
  await writeFile(tasksPath, tasks, 'utf8');
  await writeFile(planPath, plan, 'utf8');
  await writeFile(join(root, 'src', 'declared file.ts'), 'export const value = 1;\n', 'utf8');
  await writeFile(join(root, 'docs', 'spec.md'), '# Source\n', 'utf8');
  await writeFile(join(root, 'private.env'), 'secret=fixture-only\n', 'utf8');
  await writeFile(join(root, 'untracked.txt'), 'not declared\n', 'utf8');
  await mkdir(join(root, 'context'), { recursive: true });
  await writeFile(
    join(root, 'context', 'active-feature.md'),
    [
      '# Active Feature',
      '## Current checkpoint',
      'Stale summary says T001 is open; task checkboxes are authoritative for counts.',
      'See [verification record](../specs/feature/verification.md).',
      '## Older entry',
      'See [old record](../old.md).',
    ].join('\n'),
    'utf8',
  );
  await writeFile(
    join(root, 'context', 'workflow.md'),
    [
      '# Workflow',
      '## Step 2: Converge',
      '## Step 3: Dual-Axis Code Review',
      '## Step 4: PR / CI Verification & Convergence',
    ].join('\n'),
    'utf8',
  );
  await writeFile(join(root, 'context', 'testing.md'), '# Verification gates\n', 'utf8');
  git(root, ['init']);
  git(root, ['config', 'user.name', 'Agent Context Tests']);
  git(root, ['config', 'user.email', 'agent-context@example.invalid']);
  git(root, ['checkout', '-b', 'fixture']);
  git(root, [
    'add',
    '--',
    'scripts/agents/agent-context.mjs',
    'scripts/agents/agent-store.mjs',
    ...companionModules.map((name) => `scripts/agents/${name}`),
    '.gitignore',
    'specs/feature/tasks.md',
    'specs/feature/plan.md',
    'src/declared file.ts',
    'docs/spec.md',
    'context/active-feature.md',
    'context/workflow.md',
    'context/testing.md',
  ]);
  git(root, ['commit', '-m', 'fixture baseline']);
  return { root, cliPath, tasksPath, planPath };
}

export function run(fixtureValue, args, cwd = tmpdir()) {
  return spawnSync(process.execPath, [fixtureValue.cliPath, ...args], {
    cwd,
    encoding: 'utf8',
    windowsHide: true,
  });
}
