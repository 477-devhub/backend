# 477 Role 1 — engineering contract v2

Scope: backend + independent local_cv / clef_direct / general_vlm testing.
Frontend and dataset acquisition belong to other team members; their handoffs are explicit.
Read docs/ownership.md, docs/model-contract.md, docs/api-contract.md and TASKS.md first.

## Invariants
- No face recognition or automatic emergency dispatch. request_dispatch records human intent only.
- Risk = round(100 * (0.35*S + 0.30*I + 0.20*E + 0.15*P)); never multiply by confidence.
- Low confidence, missing axes, mock, timeout, invalid output or invalid evidence -> human review.
- Unknown risk is null/UNKNOWN, never zero or invented 50. Frontend must support this extension.
- Only explicit normal + confidence >= .90 + risk <20 may be suppressed; preserve a restore path.
- Evidence references must belong to actual input frame/timestamp IDs. Demo scenarios are labeled synthetic.
- Provider SDK imports and request serializers live only in app/models/adapters/.
- Use app/models/execution.py for all model calls; adapters must not block the event loop.
- Ground truth never reaches inference. Freeze source/scenario groups across splits.
- Mocks are explicit mock_* names. Real model slots must not silently return mocks.
- The repository is a validated development harness, not a trained model or production deployment.

## Coordination
MAIN owns shared schemas, base/execution/registry, settings, main.py, protocol, pyproject, all docs,
contracts lock, fixtures, integration/contract tests and scripts. Writers must stay in the ownership table.
Default: one writer. Only run disjoint writers in parallel after contracts freeze and explicit MAIN task assignment.
No nested delegation. Shared edits require a handoff request; MAIN patches and re-freezes sequentially.
Do not infer disk isolation from different agent chats. Do not reset/revert another writer's files.
During parallel work, workers never run git add/commit/merge/reset or install dependencies; MAIN owns them.
If a worker is interrupted, inspect its diff before reassigning the task.
Use a new isolated worktree only when MAIN arranges branches and commits; normal prompts use disjoint paths.

## Gates
Before starting: identify exact paths and completion criteria. After each task: run focused tests, then MAIN runs
python -m pytest -q and python scripts/check_contracts.py. Reviewer returns BLOCK/PASS.
On BLOCK, fix and rerun affected checks; don't advance dependent stages.
Update TASKS.md and handoffs with commands, artifacts, assumptions and unresolved items.
Never mark real adapters/dataset evaluation completed without real input/media and reproducible results.

## Model decisions still open
Clef provider/API/model/access/modality are unverified. Do not assume it accepts images or replaces VLM.
First confirm capabilities, then implement. If unavailable, label B blocked and continue A/C; do not fabricate B.
Common JSON shape is necessary but does not guarantee fairness. Record raw-media/feature budgets and total costs.
Use fixed shared features only when extracted without labels and available at inference time; measure extractor time.
