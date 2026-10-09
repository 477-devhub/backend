# Actual baseline results — 2026-10-08

MAIN executed the real suite after all sequential implementation agents,
326 full tests, frozen-contract verification and reviewer execution-readiness PASS.
Command:
`.venv-benchmark/Scripts/python.exe -B scripts/run_benchmark_baseline.py --mode suite --repeats 3 --output runs/baseline-final`.
Postprocessing:
`.venv-benchmark/Scripts/python.exe -B scripts/analyze_benchmark_baseline.py --run runs/baseline-final`.

42/42 planned attempts executed. Direct VLM21 and pipeline21; CV21 successful,
DeepSeek42 valid-JSON responses, Clef15 responses and6 pre-POST local payload
rejections. All21 pipeline samples reached VLM; routing exclusions0.
Schema+canonical evidence: direct16/21, pipeline13/21. Of the latter,4 use
Clef fallback, so all stages and final contract succeed9/21. Preserve original
summary status=incomplete and the failed acceptance result.

Runtime p50/p95 direct16.42/22.46seconds, pipeline68.22/78.45seconds;
all42 under predeclared120seconds. No ground-truth/normal/evidence grades;
semantic accuracy/misses/false alarms remain null. Six unique clips reuse7items.
Source protected snapshots match; no inputs, schemas or prompt were edited.

Ledger runs/477-paid-budget.json includes43DeepSeek+16Clef=59calls, with the
separate2-call access probe. Reserved3.45235968USD; usagepeakestimate
0.286777356USD. Invoice cost is unknown. Balance3.78→3.69USD is rounded account
movement, not per-request invoice. Stage usage sums reconcile reported cost.
Credential-value scan332files and staged diff: zero matches; .env untracked.

Artifacts: model raw responses,42diagnostics/common records,29 valid frozen
submissions, CSVs, failures, analysis.json, latency.png, runtime/dependency
metadata and before/after protected snapshots. Final report:
reports/benchmark-baseline-final.md; guide docs/benchmark-baseline-run.md.

Blocked/uncompleted behavior: ROI/authorization/dwell definitions missing;
CV returns observations/candidates and unmeasured null axes. Clef state
serialization byte-bound failures on ITEM03/06 need a separately versioned
converter experiment. Provider timestamps13invalidoutputs need exact frame
grounding, not repairs. Free-form benchmark event labels are not silently
mapped to the existing6-event enumeration; all common VLM assessments go to
review. Existing ASGI configuration is separate from benchmark CLI factory.

The analysis script initially treated integer observation counts as lists;
MAIN fixed that helper and reran it successfully on the real42records.
Latest MAIN post-run full checks:326passed/1existingwarning/34.87seconds;
scripts/check_contracts.py PASS. Independent final result review by
/root/baseline_execution_reviewer: PASS for report integrity, not performance.
Reviewer independently reconciled42attempts,59requests,exactstagecosts,
29validsubmissions (fullchain9/21),21pairedinputmatches,protected snapshots,
and209generatedfiles with no credential values. No reviewer model/API calls
or additional test execution occurred during that final review.
Execution/analysis/handoff work is complete. Failed performance acceptance,
6Clef preprocessing omissions,13grounding errors,ontology alignment and
ROI/ground-truth/invoice gaps remain explicit; no synthetic success was added.
