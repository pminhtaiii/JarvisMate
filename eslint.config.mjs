import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';

const nodeJavaScript = [
  'scripts/**/*.mjs',
  'tests/agents/**/*.mjs',
  'tests/ci/**/*.mjs',
];

export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      '.agent-work/**',
      '.agent-test-tmp/**',
      '.tmp-ci-checks/**',
      'coverage/**',
    ],
  },
  {
    ...js.configs.recommended,
    files: nodeJavaScript,
    languageOptions: {
      ...js.configs.recommended.languageOptions,
      globals: globals.nodeBuiltin,
    },
    rules: {
      ...js.configs.recommended.rules,
      'no-unused-vars': ['error', {
        argsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_',
        destructuredArrayIgnorePattern: '^_',
        ignoreRestSiblings: true,
        varsIgnorePattern: '^_',
      }],
    },
  },
  {
    files: ['**/*.{ts,tsx,mts,cts}'],
    extends: [
      tseslint.configs.eslintRecommended,
      ...tseslint.configs.strict,
      ...tseslint.configs.stylistic,
    ],
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/explicit-module-boundary-types': 'error',
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'separate-type-imports' },
      ],
      'prefer-const': 'error',
    },
  },
  {
    files: ['src/**/*.{js,mjs,cjs,ts,tsx,mts,cts}'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: 'ImportExpression[source.type="Literal"][source.value=/(?:^|\\/)tests\\/runtime\\/support(?:\\/|$)/]',
          message: 'Production code cannot dynamically import runtime test support.',
        },
      ],
      'no-restricted-properties': [
        'error',
        { property: 'transitionContexts', message: 'Production code must use the public StatePort API.' },
      ],
      'no-restricted-imports': [
        'error',
        {
          patterns: [{
            group: [
              '**/tests/runtime/support',
              '**/tests/runtime/support/**',
              'tests/runtime/support',
              'tests/runtime/support/**',
            ],
            message: 'Production code cannot import runtime test support.',
          }],
        },
      ],
    },
  }
);
