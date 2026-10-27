import { globSync } from 'node:fs';

function normalized(files) {
  return files.map(file => file.replaceAll('\\', '/')).sort();
}

export function contributorTestFiles(root) {
  // Keep the active gate focused on CI harness checks and the current JarvisMate PR helper.
  // Legacy slop-loop agent tests remain available for manual runs, but are not product CI.
  const selected = normalized([
    ...globSync('tests/ci/**/*.test.*', { cwd: root }),
    'tests/agents/open-pr.test.mjs',
  ]);
  const unsupported = selected.filter(file => !file.endsWith('.test.mjs'));
  if (unsupported.length) throw new Error(`Contributor helper tests must use .test.mjs: ${unsupported.join(', ')}`);
  if (!selected.length) throw new Error('No contributor helper tests found.');
  return selected;
}

export function runtimeTestFiles(sourceFiles, emittedFiles) {
  const sources = normalized(sourceFiles.map(file => file.replaceAll('\\', '/')));
  const emitted = normalized(emittedFiles.map(file => file.replaceAll('\\', '/')));
  const unsupported = sources.filter(file => !/^tests\/runtime\/.+\.test\.ts$/.test(file));
  if (unsupported.length) throw new Error(`Runtime source tests must use .test.ts: ${unsupported.join(', ')}`);
  if (!sources.length && !emitted.length) throw new Error('No runtime source tests found.');

  const expected = sources.map(file => file.replace(/^tests\/runtime\//, 'dist/tests/runtime/').replace(/\.test\.ts$/, '.test.js'));
  const sourceSet = new Set(expected);
  const emittedSet = new Set(emitted);
  const missing = expected.filter(file => !emittedSet.has(file));
  const unexpected = emitted.filter(file => !sourceSet.has(file));
  if (missing.length || unexpected.length || sourceSet.size !== expected.length || emittedSet.size !== emitted.length) {
    throw new Error(`Runtime test source/emission mismatch; missing emitted: ${missing.join(', ') || 'none'}; unexpected emitted: ${unexpected.join(', ') || 'none'}.`);
  }
  return emitted;
}
