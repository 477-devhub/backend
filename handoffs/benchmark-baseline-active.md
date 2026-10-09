# Baseline execution handoff — 2026-10-08

User-selected models: yolo26s.pt + ByteTrack, optional yolo26s-pose.pt;
Cloudflare Clef; DeepSeek deepseek-flash via API. Paid inference is authorized
up to $5 total. No benchmark, final-candidate, data or media files may change.

The predeclared plan is docs/benchmark-baseline-plan.md. Seven ITEMs reuse six
clips and have no ground-truth labels: semantic accuracy, false alarms and
evidence correctness cannot be scored. All failures remain in denominators.

Completed sequential agents:
- /root/baseline_run_preflight: read-only data/provider/environment preflight.
- /root/baseline_yolo26_bytetrack: CV adapter/worker and 15 focused tests.

MAIN added the immutable benchmark bridge, execution boundary, persistent paid
budget and protected-input snapshot helpers. MAIN verification:
`.venv/Scripts/python.exe -B -m pytest -q`: 237 passed, one existing warning.
`python -B scripts/check_contracts.py`: Frozen contracts match.
Actual model inference and API access are not yet verified.

Installation is isolated in .venv-benchmark. CPU torch 2.9.1+cpu and torchvision
0.24.1+cpu are installed; benchmark extras are being installed. Model weights
will be stored under artifacts/models; results under runs. Existing .venv is
retained. No paid call has occurred at this checkpoint.

Remaining sequential work: Clef adapter, DeepSeek adapter, evaluation runner,
MAIN integration/downloads/real runs, independent review and final analysis.

Integration checkpoint: all three adapters and evaluator implemented. MAIN
full 322 tests and contract check passed. Real provider probe returned HTTP200
for both providers; ledger 2 calls, reserved $0.10003968, usage estimate
$0.02501982, invoice unknown. Pixel-preserving serialization preflight found
JPEG90 over body limits for three ITEMs; fixed JPEG80 passes all seven. The
same DeepSeek agent applied the owned-file fix and focused31 passed.

Independent agent /root/baseline_execution_reviewer tested 103 new focused
and 90 existing safety regressions, but returned BLOCK for floating boundary
comparison at exactly one source-frame period. MAIN fixed shared mapper and
the evaluation owner is fixing its corresponding check. Criteria are unchanged.
Full paid suite remains unrun until revalidation and reviewer PASS.

Final closure: the numerical fix passed, MAIN326tests/contracts passed and
reviewer readiness PASS preceded the real42-attempt suite. Results and the
independent final report-integrity PASS are in
handoffs/benchmark-baseline-results.md and reports/benchmark-baseline-final.md.
Execution is complete; model acceptance is failed/incomplete as documented,
with no alteration to the original results or protected inputs.
