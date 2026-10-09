# Experiment Rules

Allowed: different CV detectors, trackers, pose models, decision models and reasoning architectures.
Record exact model names, checkpoints, hardware and settings for reproducibility.

Prohibited: using benchmark labels or private answers; inferring labels from filenames;
reading extra source frames or uploading full source videos; adding visual information beyond
the 64 canonical frames; hard-coding answers; answer-based per-ITEM threshold tuning.
Do not use the separate human demo package as modeling input or reference material.

For deterministic rules, prefer generic heuristics, published/default thresholds or
predeclared thresholds. Set and record them before evaluating these ITEMs.
Repeatedly changing thresholds after inspecting benchmark outcomes is test-set tuning;
record all such changes and report the tuned run separately rather than as an untouched comparison.

All pipelines share the same prompt semantics and frozen schemas. Preserve observable evidence
and uncertainty. Avoid unsupported claims about identity, intent, diagnosis or authorization.
Do not assume precise synchronization across camera clips.
Compare the two-view condition against the best single-view condition, not just one chosen view.

P4 uses canonical frames, with batching allowed only over that fixed visual input.
Record batching in runtime_config. Every ITEM still has 64 total frames.
The three-camera item requires assessments for all supplied cameras and a complete attention queue;
no reference ordering is supplied.

Human grading is performed separately. Submit actual results with human_grading null.
Package checks and fingerprint checks verify declared inputs, not external pipeline execution.
Keep runtime logs/source code so the input and latency boundaries can be reviewed.
