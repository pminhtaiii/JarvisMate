# Skill retrieval branch review

Reviewed `codex/011-skill-retrieval` from base
`bd1f5fa8cd9277b21028f40af4f5f19091310b4e` on 2026-11-11.
This is CPU and metadata evidence, not a planner quality or GPU latency qualification.

## Findings and fixes

- Catalog compatibility compared source-byte SHA-256, rejecting the original
  dataset's JSON-equivalent catalogs. Validation now compares schema version and
  canonical JSON SHA-256. Repository source hashes remain in the library; actual
  dataset source hashes remain in metadata and run identity. Enabled identity also
  records the canonical hash. Semantic changes and missing fingerprints fail closed.
- Prompts included retrieval IDs, evidence, titles and verbose eligibility metadata.
  Rendering now projects operational instructions only, retaining dependencies,
  constraints and completion conditions. It also restores the authored
  `dependency_flow`, which the original retrieval object omitted. Added prompt tokens
  are bounded to 1,536, with initial observation headroom and per-step refitting.
  Whole lower-priority branches are removed instead of clipping safety conditions.
- Fixed initial guidance could overflow later despite a fitting baseline prompt.
  Growing-observation tests now cover fitting, branch removal, unmodified tool results
  and context rejection when the baseline itself is too large. CPU native KV tests
  compare generated token IDs/actions to fresh prefill across guidance removal.
- Accentless ASR `dat xe cong nghe den san bay` could mistake the noun phrase
  `cong nghe` for a listening action and directional `den` for a light. The noun
  phrase no longer emits an action signal. Synthetic tests cover recognition word
  substitutions, insertions, deletions, repetition, segmentation, code switching,
  negation and conservative fallback when critical object/channel cues disappear.
- Worker startup trusted the factory's reported library identity without comparing
  it to the actual library. These must now match. Disabled workers also ignore any
  library supplied by a custom factory. Tests cover disabled config/prompt behavior,
  eligible tools, E/S/H gating, provenance and incompatible resume identities.

## Reproduction

Run from `D:\JarvisMate_Harness\JarvisMate`. The Python environment below has
PyTorch `2.9.0+cu128`, Transformers `4.57.1` and LM Format Enforcer `0.11.3`.
The tokenizer path supplies tokenizer files only; tests instantiate small random
CPU models. Production model weights are not loaded or modified.

```powershell
$py = 'D:\JarvisMate_5\JarvisMate\.venv-llm\Scripts\python.exe'
$env:PYTHONPATH = 'python/src;python/tests'
$env:PYTHONIOENCODING = 'utf-8'
$env:CUDA_VISIBLE_DEVICES = ''
$env:LIFEMATE_NATIVE_TOKENIZER = 'D:\JarvisMate_5\JarvisMate\resources\models\qwen3-4b-instruct-2507'
$env:LIFEMATE_SKILL_DATA_ROOT = 'D:\JarvisMate_Harness\DATA_JarvisMate\train+public_test'
$tests = @(
  'test_skills', 'test_integration_config', 'test_worker_skill_identity',
  'test_qwen_native', 'test_qwen_kv', 'test_agent', 'test_artifacts',
  'test_asr_once', 'test_audio', 'test_checkpoint', 'test_cli', 'test_dataset',
  'test_inference', 'test_integration_diagnostics', 'test_integration_early_stop',
  'test_integration_pipeline', 'test_integration_supervisor', 'test_kv_benchmark',
  'test_runtime', 'test_selection'
)
& $py -m unittest @tests -q
& $py -m lifemate.skill_preflight --data-root $env:LIFEMATE_SKILL_DATA_ROOT --repository-catalogs tools
```

Recorded CPU results:

| Check | Result |
|---|---|
| Focused skill/catalog/config/worker/native/KV/pipeline selection | 100 tests passed, no skips, 92.927 s |
| Expanded inference/runtime/supervisor selection above | 265 tests passed, no skips, 164.860 s |
| Follow-up budget-cap, real-tokenizer headroom and enabled-identity checks | 3 tests passed, no skips, 5.580 s |
| `git diff --check` | Passed |

The expanded run preceded the final budget-cap unit test; the follow-up includes
that new test and reruns the two affected checks. The command above now collects
266 tests. CPU SFT training tests and separately enabled real-dataset inference
smokes were outside this review's selection.

The first expanded run in the restricted Windows sandbox could not terminate an
orphan worker in the existing supervisor crash-recovery test. It returned
`RUN_OWNERSHIP`, followed by a locked trace-file cleanup error. The same isolated
test reproduced both errors on the untouched base commit. Outside the sandbox,
the isolated test passed in 3.139 s and the complete expanded run passed as recorded
above. The three orphan test process trees were terminated. No supervisor code or
test assertions were relaxed; Windows runs need permission to terminate their own
test worker trees.

## Catalog evidence

Metadata-only preflight passed for all **1,545 Train** and **634 Public Test**
records. Both catalogs have schema version `2.7.0`. No models, ASR or runtime were
loaded; no ToolEnv was created. Environment files received existence checks only.
The actual-dataset regression guards against hidden environment reads and runtime
or model factory invocation. No Public Test requests were used to select guidance
or tune retrieval; those checks inspect catalog and input metadata only.

| Split | Repository raw SHA-256 | Dataset raw SHA-256 | Shared canonical SHA-256 |
|---|---|---|---|
| Train | `3895a315a24e1ed04ad063ccc71ee4d70afa0a80fee9552f71dbf0d3e05f9a2f` | `a994984bb580d7e0d60166641858901d428549682ba3614dbf9269037a33cce0` | `68629fab8a38b23ce8946081663fb6efad842a5e06f179072feffc6daccd4d4d` |
| Public Test | `42a3d0f0e69fdf30da78652292ee85ef7295c666600a06221827bb4fae5eea36` | `c8f46c278a7495d36905ac28fc5b85b67aad22bc2ac0b29ba9ac6455ad9daf5d` | `313a0b74c4c2b9246189234c92f2339a8aa304d68c985e0f7ad84144ede7c87e` |

The canonical algorithm is the project's strict `jsonio.dumps`: sorted object
keys, compact separators, literal Unicode and UTF-8. Array order remains meaningful;
this is not a claim of general RFC 8785 numeric normalization.

## Prompt evidence

Using the local Qwen tokenizer, the synthetic request
`Huy goi xem phim roi mo playlist` with Train subscriptions/music/sys tools selected
`S11.B02` and `S18.B01`. Baseline length was 2,154 tokens. Guidance overhead fell
from **1,244 to 864 tokens** (30.5%) while restoring dependency flow. This is one
controlled example, not an aggregate dataset or latency result. Disabled message
rendering and effective config records were also compared directly with the base
commit's functions and matched exactly. Full run identity still changes with code
provenance, as intended.

## Remaining qualification

- No GPU inference, production-weight changes, ToolEnv edits, decoding changes or
  merge into main were performed.
- No ASR WER, paired planner quality/state-hash score, real GPU KV parity, A30 timing
  or end-to-end accuracy claim is established by these checks.
- Retrieval remains a conservative lexical heuristic. Severe recognition errors can
  lose a match; ambiguous surviving words can still select irrelevant guidance.
  Missing guidance falls back to the original planner path.
- Guidance removal changes the prompt prefix and can reduce KV reuse. Per-step
  tokenization adds CPU work; measure the complete 30-second path on the target GPU.
- Large baseline requests or growing tool observations can still exhaust the context.
  The context and generation limits remain unchanged.
