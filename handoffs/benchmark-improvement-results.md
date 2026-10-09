# Sequential improvement handoff — 2026-10-08

MAIN kept protected benchmark/data folders and original baseline results unchanged.
This is an executed development benchmark, not validated CCTV event accuracy.

## Actual agents and gates

| Sequential agent | Owned task | Focused result |
|---|---|---|
| /root/improvement_audit | Read-only data/failure/bottleneck audit | Analysis only; no tests/API |
| /root/improvement_clef | Clef adapter and its tests |25 PASS|
| /root/improvement_vlm_grounding | DeepSeek v2 adapter and its tests |38 PASS|
| /root/improvement_cv_profile | YOLO adapter/worker and its tests |20 PASS|
| /root/improvement_pipeline_evaluation | Baseline evaluator and its tests |94 PASS|
| /root/improvement_readiness_review | Read-only execution gates |PASS before canonical/speed and v3 pilot|
| /root/improvement_vlm_json_labels | DeepSeek v3 adapter and its tests |67 PASS|

Registered explorer/model_engineer/evaluation_engineer/reviewer configurations
were applied. No nested delegation. MAIN owns shared registry/CLI/contracts/tests,
installation/integration, actual execution, analysis scripts and documents.
Final MAIN verification: `.venv/Scripts/python.exe -B -m pytest -q` →386 PASS,
warning1,54.61s; `-B scripts/check_contracts.py` →Frozen contracts match.

## Executed commands and artifacts

```
.venv-benchmark/Scripts/python.exe -B scripts/run_benchmark_baseline.py --mode suite --repeats 1 --cv-profile pose-always --output runs/improved-canonical64
.venv-benchmark/Scripts/python.exe -B scripts/run_benchmark_baseline.py --mode pipeline --repeats 1 --items ITEM_03 ITEM_06 ITEM_02 --cv-profile pose-off --output runs/improved-pose-off
.venv-benchmark/Scripts/python.exe -B scripts/run_benchmark_baseline.py --mode vlm --repeats 1 --items ITEM_04 --vlm-transport deepseek_json_labels_v3 --output runs/improved-json-labels-item04
.venv-benchmark/Scripts/python.exe -B scripts/analyze_benchmark_baseline.py --run runs/improved-canonical64
.venv-benchmark/Scripts/python.exe -B scripts/analyze_benchmark_baseline.py --run runs/improved-pose-off
.venv-benchmark/Scripts/python.exe -B scripts/analyze_benchmark_baseline.py --run runs/improved-json-labels-item04
.venv-benchmark/Scripts/python.exe -B scripts/analyze_benchmark_improvements.py --output runs/improvement-analysis
```

All three inference commands and all analysis commands exited0; exit0 does not
mean every provider or benchmark criterion passed. Summary/diagnostics preserve failures.

- Canonical64:14 actual attempts, pipeline7/7 whole-stage/output PASS,
  standalone6/7 PASS; ITEM_04 malformed JSON remains failure.
- Pose-off:3 attempts, final output3/3 PASS but whole-stage2/3 PASS. ITEM_02
  Clef HTTP429/code4006 daily free10,000Neurons exhausted; no retry or plan upgrade.
- Isolated v3 ITEM_04:1 actual attempt/HTTP200/schema+canonical evidence PASS,
 24.917s. Same64 RGB/JPEG and source prompt/schema hashes. No output repair.
  Output cap4096 differs from v2=8192. Do not merge pilot into original6/7 cohort.
- Matched pose CV3items median reduction34.54%; whole-chain paired2successful
  items total median reduction22.39%. Detection/track observations match;
  semantic non-regression unknown because pose removed and no GT.
- Cumulative87 reservations, $4.99158528 retained; known86 usage estimate
  partial sum$0.523827864; one unknown429 usage, full total/invoice null.
  Paid execution stopped; remaining$0.00841472 cannot cover another model call.

Final reports: `reports/benchmark-improvement-final.md`,
`reports/benchmark-improvement-next-actions.md`, `docs/benchmark-improvement-run.md`.
Comparison JSON/CSV/plot under `runs/improvement-analysis`; all raw responses,
common assessments, diagnostics and validated submissions under each new run.

## Unresolved items

Actual GT/normal negatives, per-camera ROI/authorization/dwell policy, common event
taxonomy mapping and semantic evidence grading unavailable. Event accuracy,
misses/false alarms/risk accuracy and pose-off semantic regression unmeasured.
Provider billing invoice and429 usage unknown; account free quota needs dashboard
check/reset. Fresh videos, dense-frame tracking, warm-worker/GPU evaluation,
conditional pose accuracy and actual ASGI provider slot integration not performed.
These items cannot be completed by invented labels, mock output or budget reset.

Final independent result/integrity review: **PASS** from
`/root/improvement_readiness_review`. Independently revalidated all18saved
diagnostics against schema/context/actual input references and submissions,
paired timings/detector observations, budget and immutable files. Credential
scan333files0matches, contract checker PASS. No edits/API/GPU calls. MAIN386
pytest result was reviewed as reported evidence, not independently rerun.
This PASS validates integration/report integrity, not event accuracy.

Post-execution MAIN read-only verification: original206file digest matches,
protected37snapshot matches, credentials scanned264files/matches0, actual.env
not tracked, frozen contracts match. No new model/API requests during these checks.

MAIN-only follow-up: `reports/477-benchmark-explained.html` explains the frozen
benchmark, actual CSV columns/examples, added pipelines and current limitations.
Self-contained; static JS syntax/IDs/local links checked. No subagent/provider
calls or protected source modifications. Interactive controls were not separately
verified in a real browser; no browser test PASS is claimed.

MAIN follow-up diagnosis: `reports/clef-effectiveness-diagnosis.md`. Verified
fixed actual routing and no CV/Clef-to-VLM feature transfer, successful Clef7
proposals6human_review/1invoke_vlm, all7 incomplete CV states, sameVLM transport
composition7/7. Removing observed Clef stage is only an offline timing estimate,
not an actual CV+VLM experiment. No API/test/behavior changes; GT and budget
continue to block semantic/no-Clef paid comparison. Report gives prioritized fixes.

MAIN-only follow-up: existing explanation HTML now includes #yolo, per-ITEM
actual64-frame camera allocation/temporal intervals and evaluation scope. Selected
image detection needs exhaustive GT boxes/classes; tracking/action require temporal
identity/event truth and separate dense-frame tests. Sources: official YOLO val
docs and ByteTrack paper. Static HTML checks PASS; no real accuracy claims,
new paid calls, benchmark/data changes or dense experiment execution.
