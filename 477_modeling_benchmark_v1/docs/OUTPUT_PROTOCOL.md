# Output Protocol

Submit one result JSON per ITEM under your assignment directory:
```
submissions/p1_clef_flash/
    run_ITEM_01.json
    run_ITEM_02.json
    run_ITEM_03.json
    run_ITEM_04.json
    run_ITEM_05.json
    run_ITEM_06.json
    run_ITEM_07.json
```
No example predictions or measured results are included in this package.

## Frozen result envelope
All fields required by `schemas/result.schema.json`:
- `benchmark_version`: `477-reasoning-v1`
- `pipeline`: `cv_llm` for P0–P3; `vlm_only` for P4
- `run_id`: nonempty identifier for the actual run
- `item_id`: the corresponding public ITEM ID
- `model_id`: actual principal model/version or rule engine identifier
- `runtime_config`: actual pipeline configuration object
- `input_fingerprint`: exactly `load_item(item_id)["input_fingerprint"]`
- `prediction`: frozen task-specific prediction schema
- `latency_ms`: measured end-to-end milliseconds
- `input_tokens`, `output_tokens`, `estimated_cost_usd`: actual measured values or null
- `human_grading`: **null** at submission

The top-level schema forbids extra fields. Do not add top-level `model`, `run`,
`api_cost_usd`, or alternative pipeline values. The compatibility envelope for P0 does
not imply an LLM: its actual assignment and null decision model are explicitly recorded below.

## runtime_config
Record `pipeline_id` as one of `P0_CV_ONLY`, `P1_CV_CLEF_FLASH`, `P2_CV_JEV`,
`P3_CV_CLEF`, `P4_STRONG_VLM`. Include actual component model IDs and checkpoint versions:
`cv_detector`, `tracker`, `pose_model`, `decision_model`; absent components are null.
Include `device`, `precision`, `batch_size`, `frame_protocol = "uniform_total64_v1"`,
threshold values/source, batching, stage timing definitions, and relevant provider settings.
Use nested metadata here because the frozen schema allows this object without changing its contract.

## Prompt semantics and prediction
Use `model_input/prompt_v1.txt` unchanged. P0 does not have to call an LLM but must
respect the same scope: observable evidence only; do not infer identity, intent,
medical diagnosis or legal authorization beyond visible support.
Use `load_item(item_id)["response_schema"]` for the task branch.
For ITEM_04 include each camera's assessment and a full attention queue.

## Fingerprint validation
Record the exact prompt/schema/media hashes, protocol ID and frame indices returned
by the loader. The public validator rejects mismatched declarations.
Fingerprint matching is a consistency check, not proof of actual consumption: submit code
for review of the canonical entry point and any intermediate caches.

## End-to-end latency
Measure with a monotonic clock from canonical frame decode through result serialization:
- P0: decode + CV inference + feature aggregation + rules + result serialization.
- P1–P3: decode + CV + aggregation + API serialization/upload + decision inference
  + response parsing + result serialization.
- P4: decode + visual request preparation/upload + VLM inference + parsing + result serialization.

Do not report a single stage as end-to-end. Include response waiting and all batches.
Declare warm-up, caching and retry policies. Serialize the result within the timed interval;
then fill the measured `latency_ms` value and document any final envelope write excluded from timing.

## Cost
Use actual API usage when available. Otherwise token and estimated-cost fields are null.
If you calculate cost, use official provider pricing and actual measured usage;
record pricing date/source and the calculation in `runtime_config`.
Never invent tokens or cost values.
For P0, absence of API spend does not mean free compute. Prefer
`estimated_cost_usd: null` unless a documented compute estimate is available; record
`runtime_config.api_cost_usd: 0`, `local_compute_device` and measured latency separately.
For API pipelines distinguish direct API cost from local compute and document the estimate scope.

Validate before submission:
```
python -B scripts/validate_prediction.py submissions/p1_clef_flash/run_ITEM_01.json --result
```
This unchanged validator checks frozen schemas, camera/time context and fingerprint equality.
It also supports evaluator-graded envelopes; submission policy additionally requires
`human_grading` to be null, which the submitter must ensure.
