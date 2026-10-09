# 477 Modeling Benchmark v1

This package is the public modeling subset of the frozen
477-reasoning-v1 benchmark.

Purpose: Compare multiple AI pipelines under the same visual input,
prompt semantics and output schema.

This package intentionally excludes all private labels,
annotations, human references and evaluation answers.

## Common contract
- 7 ITEMs, 6 opaque media assets.
- 64 total canonical RGB frames per ITEM, including all cameras combined.
- Generic camera IDs and clip-relative timestamps.
- One frozen prompt, prediction schema and result schema for every pipeline.
- `iter_model_frames(item_id)` is the **only canonical visual input entry point**.
  This applies to CV and VLM implementations alike.

Start with [QUICKSTART.md](QUICKSTART.md), then read [PIPELINE_ASSIGNMENT.md](PIPELINE_ASSIGNMENT.md)
and the protocols in `docs/`.

## Public item mapping
| ITEM | Input |
|---|---|
| ITEM_01 | Single-camera |
| ITEM_02 | Single-camera |
| ITEM_03 | Single-camera |
| ITEM_04 | Three-camera attention ranking |
| ITEM_05 | Single-camera multi-view condition A |
| ITEM_06 | Single-camera multi-view condition B |
| ITEM_07 | Two-camera multi-view condition AB |

## Environment
Python 3.10+, `ffmpeg` and `ffprobe` on PATH, `jsonschema` and `referencing`.
`referencing` is a dependency of recent `jsonschema`; install both explicitly for clarity.
The package installs no AI frameworks. Each implementer chooses their own dependencies.
`scripts/benchmark_common.py` is the unchanged public utility needed by the unchanged validator.

## Submission compatibility
The frozen result schema uses `run_id`, `model_id`, and a `pipeline` enum containing
`cv_llm` and `vlm_only`. It does not have top-level `run` or `model` fields.
P0–P3 use the `cv_llm` compatibility envelope; P4 uses `vlm_only`.
For P0, this envelope does not claim that an LLM was used: record
`runtime_config.pipeline_id = "P0_CV_ONLY"` and a null decision model.
All pipelines record their precise assignment and component/checkpoint details in `runtime_config`.
The frozen schemas remain unchanged.

Fingerprint validation checks declared indices and hashes. It cannot prove what frames an external
implementation actually consumed; submit code and runtime configuration for that audit.
The package lock detects file changes relative to the included lock; it is not a digital signature.
The lock covers all distributed regular files except `PACKAGE_LOCK.json` itself, which cannot
hash its own contents. Submission directories start empty; later user-generated outputs are not
locked benchmark inputs. Verify the externally supplied ZIP SHA256 when receiving the package.

## What to submit
1. Source code (preferably including `run_all.py`).
2. `requirements.txt` or `environment.yml`.
3. Runtime configuration, including model names/checkpoints and threshold choices.
4. `run_ITEM_01.json`.
5. `run_ITEM_02.json`.
6. `run_ITEM_03.json`.
7. `run_ITEM_04.json`.
8. `run_ITEM_05.json`.
9. `run_ITEM_06.json`.
10. `run_ITEM_07.json`.

Each JSON is a measured result, not just a prediction. Set `human_grading` to null.
Evaluator-side grading is performed separately after submission.
