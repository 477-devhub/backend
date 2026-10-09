# Baseline improvement checkpoint — 2026-10-08

## Final execution checkpoint

All planned actual runs and isolated JSON-label pilot have completed. Current
results supersede earlier RUNNING/PLANNED checkpoint entries below. See
`handoffs/benchmark-improvement-results.md` and `reports/benchmark-improvement-final.md`.
MAIN full386 PASS/contracts match; canonical pipeline7/7, direct6/7; separate
  pose-off whole2/3 (Clef real freequota429); v3 target1/1. Final independent
result review PASS. No more paid calls: cumulative reservation$4.99158528.

MAIN owns this checkpoint. Original completed baseline is preserved at
`runs/baseline-final`; no restart/reset of earlier stages or paid ledger.

## Completed audit / shared preparation

- Actual sequential agent `/root/improvement_audit`, explorer configuration
  applied: read-only, no file changes/API/model calls/tests/installation.
- Confirmed Clef6 failures were local65536byte check, not provider account quota.
  Actual bodies85573/67683bytes below196608. Provider context65536 is tokens.
- Timestamp13 failures each include a ref ~0.066667seconds from supplied frame,
  outside existing1/30 threshold. One-decimal output is suspected; no proof of
  semantic event error and no frame decoding discrepancy found.
- CV measured median47.60s: detect19.52s, pose17.57s, imports4.92s,
  load.46s, track.17s. No evidence that ByteTrack is the speed bottleneck.
- Original data/media contain .gitkeep only; both video packages contain no GT,
  normal negatives or zone/authorization labels. These metrics remain N/A.
- MAIN registry now supports explicit pose_enabled=False without changing
  detector/resolution/threshold. CLI --cv-profile records supplemental scope
  and checks worst-case paid calls before execution. $5 ledger never reset.
- Tests: registry6 passed; MAIN full328 passed in36.71s (existing warning1);
  `scripts/check_contracts.py`: Frozen contracts match. Shared lock re-frozen.

## Remaining sequential work

Real canonical64 and separate pose-off experiments, final analysis/review/report.
All three adapter changes, evaluator, MAIN gates and independent readiness review
are complete. Execution plan: docs/benchmark-improvement-plan.md.

## Clef adapter checkpoint

- Actual `/root/improvement_clef` (model_engineer) changed only its adapter and
  tests. Removed65536byte proxy, retained196608bytebody/$5/timeout protections.
  Transformation metadata distinguishes bytes and65536providercontexttokens;
  token usage reported separately; truncation unknown.
- Focused25 passed in.81s; MAIN full331 passed in40.92s (existing warning1);
  contracts match. No actual API or model calls by agent.
- Next actual writer `/root/improvement_vlm_grounding`, DeepSeek transport only.

## VLM transport checkpoint

- `/root/improvement_vlm_grounding` completed only DeepSeek adapter/tests:
  exact float repr, neutral frame_index, explicit copy instruction, v2 profile
  and hashes. Original64 RGB/JPEG80/prompt/schema unchanged; no output repairs.
- Focused38 passed in6.92s; MAIN full340 passed in40.09s (existing warning1),
  contract match. Additional MAIN CLI budget-preflight/duplicate tests2 passed.
- Next actual writer `/root/improvement_cv_profile`, truthful YOLO profile metadata.

## CV profile / local preflight checkpoint

- `/root/improvement_cv_profile` finished only YOLO adapter/worker/tests.
  Pose-off reports yolo26s.pt+ByteTrack, pose-always includes pose checkpoint;
  actual profile/config/checkpoints/ByteTrack settings/limitations recorded.
  Detector/tracker/pose inference algorithms and64 budget unchanged.
- Focused20 passed in13.13s; MAIN full344 passed in43.54s (existing warning1),
  contracts match. Agent made no new real model/API calls.
- MAIN local actual7×64 VLM serialization passed: maximum41220664bodybytes,
  maximum11938textbytes, JPEG80 originaldimensions64allframes; protected snapshot
  unchanged, paidcalls0. Previous Clef ITEM03/06 actual CVstates now allowed at
  85573/67683bytes; noAPIcalls/reservations, globalledgerstill59/3.45235968.
- Next actual writer `/root/improvement_pipeline_evaluation`, evaluator only:
  full-chain counters, fail-closed suppression, knownstagecost accounting/tests.
- MAIN host check: Win32_VideoController reports AMD Radeon (TM) Graphics,
  AdapterRAM2147483648bytes, driver31.0.21024.2004. WMI value is not a measured
  model-usable VRAM budget. Existing torch2.9.1+cpu has noCUDA; noGPU rental or
  driver/package changes. Real experiments remain CPU.

## Evaluator / integration checkpoint

- `/root/improvement_pipeline_evaluation` completed only evaluator/tests.
  Final validated output differs from whole_pipeline_validated; upstream errors
  force incomplete. New stage metrics distinguish reservation, response,
  knownusage and unknownbilling. Timeout/cancel ledger evidence preserved.
- No normal assessment proof exists in currentCV, so actual route never suppresses
  an uncertain event. Synthetic omission tests use explicit mock policy boundary.
- Focused tests/eval94 passed in9.78s; MAIN full355 passed in44.19s
  (existing warning1); contracts match. No agent actual model/API calls.
- MAIN saved-baseline analysis smoke exit0 independently reproduced16/21 direct,
  13/21 finalpipeline,9/21 fullchain; pipeline knowncost.099961824, direct.161795712,
  paid57+separateprobe2, unknownbilling0, original206filesdigestunchanged.
- Actual `/root/improvement_readiness_review` is now checking read-only readiness.
  Paid experiments have not started; globalledger still59/3.45235968.

## Independent readiness gate

- `/root/improvement_readiness_review`: PASS for approved execution scope.
  Directly checked contract match,206 originalartifactdigest,37 protectedfiles,
  sharedledger arithmetic and accounting smoke. Credentialscan213files0matches.
  Reviewer made no edits/pytest/model/API calls. This PASS is not model accuracy.
- MAIN is starting14 canonical64 attempts, then3 separatepose-off attempts;
  maximumplannedadditional27paidrequests/1.48047360reserved. No further model
  or price changes after this readiness gate.

## External work

Provide actual event/normal labels and human evidence rubric linked by neutral
sample/camera/frame IDs; ROI/authorization/loiter thresholds; permitted event
taxonomy mapping; GPU host if needed; per-provider billing for actual costs.
No guessed GT or semantic accuracy. Pose-off is speed-only until GT is available.

## Actual canonical64 suite completed

- Native run session59755 finished exit0. Actual14/14attempts: pipeline7/7
  whole_pipeline_validated, direct6/7validated. One directITEM04 malformedJSON
  retained, summary=incomplete. No canonicaltimestamp failures in parsed outputs.
- CV7success, Clef7HTTPresponses (including actual03/06formerlyblocked), VLM14
  HTTPresponses; ITEM04content syntaxerror remains provider_schema_error.
- Suite ended ledger80requests /4.63271424reserved /0.483876324usagepeakestimate.
  All80usageknown; actualinvoiceNone; protectedinputs unchanged.
- Pose-off3 realpipeline attempts are starting, with originalv2transport unchanged.
- Separate v3 JSON-label target plan appended before targetresults. OnlyITEM04
  VLM1call after freshcode/test/reviewgate, outputmax4096, reserve.058752;
  globaltotalmax4.99158528. Existingcohort/criteria/results will not be rewritten.
