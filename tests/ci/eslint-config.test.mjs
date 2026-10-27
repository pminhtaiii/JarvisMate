import assert from 'node:assert/strict';
import test from 'node:test';
import { ESLint } from 'eslint';

test('repository lint config covers tooling and CI tests without applying TypeScript rules to JavaScript', async () => {
  const eslint = new ESLint();

  for (const file of [
    'scripts/agents/active-task.mjs',
    'scripts/ci/check-context.mjs',
    'tests/agents/active-task.test.mjs',
    'tests/ci/check-context.test.mjs',
  ]) {
    const config = await eslint.calculateConfigForFile(file);

    assert.ok(config, `${file} should be included in the lint config`);
    assert.equal(config.rules['no-unused-vars'][0], 2, `${file} should check unused variables`);
    assert.equal(config.rules['no-undef'][0], 2, `${file} should check unresolved names`);
    assert.equal(config.rules['@typescript-eslint/no-explicit-any'], undefined, `${file} should not receive TypeScript-only rules`);
  }
});

test('mock-private transition contexts and runtime support imports are restricted only in source', async () => {
  const eslint = new ESLint();
  const dotAccess = await eslint.lintText(
    'export function leak(port: { transitionContexts: object }) { return port.transitionContexts; }',
    { filePath: 'src/agent-output-lint-fixture.ts' },
  );
  const computedAccess = await eslint.lintText(
    'export function leak(port: { transitionContexts: object }) { return port["transitionContexts"]; }',
    { filePath: 'src/agent-output-lint-fixture.ts' },
  );
  const privateImport = await eslint.lintText(
    "import { MemoryStatePort } from '../tests/runtime/support/uc03/memory-state.js'; export { MemoryStatePort };",
    { filePath: 'src/agent-output-lint-fixture.ts' },
  );
  const privateDynamicImport = await eslint.lintText(
    "export const load = () => import('../tests/runtime/support/uc03/memory-state.js');",
    { filePath: 'src/agent-output-private-dynamic-fixture.ts' },
  );
  const ordinaryDynamicImport = await eslint.lintText(
    "export const load = () => import('./public-port.js');",
    { filePath: 'src/agent-output-ordinary-dynamic-fixture.ts' },
  );
  const computedDynamicImport = await eslint.lintText(
    "const specifier = './public-port.js'; export const load = () => import(specifier);",
    { filePath: 'src/agent-output-computed-dynamic-fixture.ts' },
  );
  const publicPort = await eslint.lintText(
    "import type { StatePort } from './contracts/foundation/uc03/ports.js'; export function load(value: unknown) { const port = value as StatePort; return port.loadTask('task-1'); }",
    { filePath: 'src/agent-output-public-fixture.ts' },
  );
  const mockImplementation = await eslint.lintText(
    "import { MemoryStatePort } from '../support/uc03/memory-state.js'; export function createMock() { return new MemoryStatePort({ transitionContexts: {} }); }",
    { filePath: 'tests/runtime/unit/agent-output-mock-fixture.ts' },
  );
  const mockDynamicImport = await eslint.lintText(
    "export const load = () => import('../support/uc03/memory-state.js');",
    { filePath: 'tests/runtime/unit/agent-output-dynamic-mock-fixture.ts' },
  );

  for (const [label, results] of [
    ['dot access', dotAccess],
    ['computed string access', computedAccess],
  ]) {
    assert.ok(results[0].messages.some((message) => message.ruleId === 'no-restricted-properties'), `${label} should be rejected`);
  }
  assert.ok(privateImport[0].messages.some((message) => message.ruleId === 'no-restricted-imports'), 'source import from runtime support should be rejected');
  assert.ok(
    privateDynamicImport[0].messages.some((message) => message.ruleId === 'no-restricted-syntax'),
    'literal source dynamic import from runtime support should be rejected',
  );
  for (const [label, results] of [
    ['public StatePort wrapper', publicPort],
    ['mock implementation', mockImplementation],
    ['ordinary source dynamic import', ordinaryDynamicImport],
    ['computed source dynamic import', computedDynamicImport],
    ['test mock dynamic import', mockDynamicImport],
  ]) {
    assert.equal(results[0].messages.some((message) => [
      'no-restricted-properties',
      'no-restricted-imports',
      'no-restricted-syntax',
    ].includes(message.ruleId)), false, `${label} should remain allowed`);
  }
});
