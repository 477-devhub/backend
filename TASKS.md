# 실제 상태 — 검증 완료 항목과 후속 과제

## 2026-10-09 백엔드 벤치마크 제거

- 사용자 요청: 백엔드 폴더에서 불필요한 벤치마크 기능 및 대용량 실험 자료 삭제.
- 범위: new_477_piprline, 477_modeling_benchmark_v1, final_candidates_v1 및 전용
  app 코드·테스트·scripts·docs·reports·handoffs, pyproject의 benchmark extra.
- 완료 기준: 대용량 폴더 삭제, API/데모/실제 local_cv 연결 보존, 전체 회귀 테스트 및 계약 검사.
- 작업 전 Git 변경 없음. Git 이력과 다른 프로젝트 폴더는 보존.
- 하단 벤치마크 진행 기록은 과거 이력이며 현재 기능·재실행 안내가 아님.
- 검증 결과: handoffs/backend-benchmark-cleanup.md 참조.

## 2026-10-07 순차 실행 기록

**최종 현 상태:**00~09 직접 읽기/순차 진행 및 각 역할 실제 생성·review 확인 완료.
공통1.1·전처리·CV관측·평가하네스·개발통합 기술PASS, 최종212 tests/hash/pip/CLI/API smoke PASS.
04 사건분류/05Clef/06VLM/실제07validation/09test는 실제 데이터·provider/권한·선택근거 부재로BLOCK.
`/root/stage09_reviewer` 최종 차단 판정PASS. 상세 reports/final-status.md/final-test.md.
optional_parallel 미실행; 실제 데이터lock/test/API를 mock으로 완료 처리하지 않았다.

추가 사용자 계약 차이(진행 중03): 기본1.1/축별null/review/GT전용annotations.
실제 `/root/stage03_delta_evaluation` 완료: 평가37 passed. MAIN delta focused53/full166 passed,
`scripts/check_contracts.py`match. `/root/stage03_delta_reviewer` 독립53/full166/hash PASS; 상세는
`handoffs/03_contract_delta.md`. 실제 영상·제공사·접근·팀 합의 BLOCK은 그대로 유지한다.

04 파일을 직접 읽고 `/root/stage04_local_cv` (model_engineer) 순차 실행 중.
범위 local_cv.py/helper, tests/models/test_local_cv*.py; 실제 영상 이벤트 검증은BLOCK.

07 공유 요청: MAIN execution.failure_assessment(preprocessing_error) 추가,
focused16/full190/hash PASS 및 재동결 후 같은 평가 담당 재개.
재개 직후 서비스 usage-limit 오류로 종료했으나 interrupted diff에서 새07 변경0개 확인.
기존03 평가 delta 보존, 같은 `/root/stage07_evaluation` 실제 retry가 정상 도구 호출로 재개됨.
MAIN이 evaluation 역할을 대신 수행하지 않았다.

사용자 지시에 따라 `prompts/00_audit.txt`부터 `09_frozen_test.txt`까지 숫자순으로 검토한다.
역할별 실제 서브에이전트를 순차 실행하며 MAIN은 공통 파일·계약·통합을 담당한다.
`optional_parallel.txt`는 실행하지 않는다. 선행 BLOCK에 의존하는 작업은 진행하지 않고 독립 작업만 계속한다.

| 단계 | 상태 | 실제 에이전트 / 근거 |
|---|---|---|
| 00 audit | PASS (감사 목록) | `/root/stage00_explorer`, `/root/stage00_reviewer` 순차 완료; 실제 준비는 BLOCK |
| 01 contract | 기술 PASS / 팀 합의 BLOCKED | MAIN P0 수정·해시 갱신, `/root/stage01_reviewer` PASS |
| 02 backend | 기술 PASS / 실제 연결 BLOCKED | `/root/stage02_reviewer` 재검토 PASS; full86 PASS/hash PASS |
| 03 provider/data | 전처리·1.1 delta 기술 PASS / 실제 BLOCKED | `/root/stage03_reviewer`, `/root/stage03_delta_reviewer` PASS; full166/hash PASS |
| 04 local_cv | 관측 기술 PASS / 사건 검증 BLOCKED | `/root/stage04_local_cv`, `/root/stage04_reviewer`; focused22/full188/hash PASS |
| 05 clef | BLOCKED / 차단 처리 PASS | `/root/stage05_clef`, `/root/stage05_reviewer`; focused2/full188/hash PASS |
| 06 vlm | BLOCKED / 차단 처리 PASS | `/root/stage06_vlm`, `/root/stage06_reviewer`; focused39/full188/hash PASS |
| 07 validation | 하네스 기술 PASS / 실제 BLOCKED | `/root/stage07_reviewer` 수정 재검토PASS; eval57/full210/hash PASS |
| 08 integrate | MAIN 개발 통합 기술 PASS / 실제 BLOCKED | `/root/stage08_reviewer` PASS; full212/hash 및 CLI/API/install smoke PASS |
| 09 frozen test | 선행 조건 BLOCKED / 차단 판정 PASS / 실제 미실행 | `/root/stage09_reviewer`; guard7/full212/hash PASS; reports/final-test.md |

MAIN이 실행한 초기 검증:
- 기본 `python -m pytest -q`: pytest 미설치로 실행 불가. 기본 Python은 외부 Hermes 환경이었다.
- `py -3.11 -m venv .venv`, `.venv/Scripts/python.exe -m pip install -e ".[dev]"`: 성공.
- `.venv/Scripts/python.exe -m pytest -q`: **41 passed**, 1 TestClient deprecation warning, 0.91s.
- `.venv/Scripts/python.exe scripts/check_contracts.py`: **Frozen contracts match.**
- `.venv/Scripts/python.exe -m app.eval.runner --adapter mock_local_cv --input fixtures/model_input.json`: exit 0, mock=true, uncertain/review, risk_axes=null.
- 같은 runner의 `local_cv`, `clef_direct`, `general_vlm`: 각각 exit 2, provider_error, mock=false, uncertain/review, risk_axes=null. 실제 모델 검증 완료가 아니다.

초기 외부 의존성: `media/`, `data/`, `outputs/`에 실자료 없음; `.env` 없음.
확인한 실행 환경의 `OPENAI_API_KEY`, `CLEF_API_KEY`, `VLM_MODEL`, `CLEF_MODEL`, `ASSET_MAP`은 미설정(값 출력하지 않음).
프론트 ACK/UNKNOWN/카메라ID/WS/Idempotency 합의 및 데이터 담당자 납품·계약 확인 자료가 없다.
시작 전에 존재하던 `.codex/agents/*.toml` 수정은 보존한다.
등록된 역할의 모델/추론 설정은 TOML과 일치한다. 실행 중 유효 모델·sandbox를 조회하는 도구는 없어 sandbox 강제 적용까지 독립 인증하지 않는다.

00 reviewer 추가 검증: `.venv/Scripts/python.exe -m pytest tests/models tests/backend tests/eval -q` → 32 passed, 1 warning, 1.01s.
P0 결함: `app/models/execution.py`가 기존 Pydantic 출력 객체를 재검증하지 않는다.
`model_copy(update={"event_confidence": 2.0})` 출력이 error_code=None으로 통과하여 normal/0축이면 suppressed가 된다.
reviewer와 MAIN 모두 실제 재현했다. 01에서 MAIN이 실행 경계 및 공통 회귀 테스트를 수정하고 재검증하기 전 의존 단계는 BLOCK이다.
정답 텍스트 관측 누수, manifest/config 외 input/cache/weight/code freeze, 1회 test 정책도 실평가 전에 검증해야 한다.

01 MAIN 수정: 공통 ContractModel의 `revalidate_instances="always"`로 출력 및 중첩 인스턴스 검증 우회를 차단했다.
`tests/contracts/test_execution_validation.py`의 16 회귀 사례는 수정 전 11 failed/5 passed, 수정 후 모두 PASS.
focused contracts/models/integration: 39 passed; full: 57 passed; freeze_contracts 및 check_contracts 성공.
JSON shape와 schema_version 1.0 유지. 프론트/데이터 전달 안내 및 공통 계약 변경점을 handoffs/에 작성했고 직접 전송하지 않았다.
필요한 팀 확인·실제 납품·provider 정보를 한 번에 비동기 요청했다. 답변 없는 합의를 완료 처리하지 않는다.

02 backend_engineer: assessment 저장 seam/입력 replay ledger 추가, focused backend 19 passed.
02 MAIN: registry/settings/main 의존성 주입, `app.state.ingest_model_input`, 통합 회귀 11개 추가.
focused backend/integration 31 passed, full 77 passed, freeze/check_contracts 성공.
모델 호출은 state lock 밖, 저장/WS publish는 lock 안이다. replay는 ACK/dismiss/restore 상태를 유지한다.
기본 MODEL_ADAPTER=local_cv는 명시적 미설정 real slot이며 mock fallback은 없다.
실제 API/WS 캡처 14개를 handoffs/frontend.md에 저장했다(모두 synthetic demo, 영상 없음).
02 reviewer BLOCK: 정상 suppression 후 같은 입력을 다시 execute하면 새로운 schema 오류/review 결과가
service의 기존 decision replay에 가려진다. 테스트77pass만으로 이를 검증하지 못했다.
backend 역할에 기존 입력 조회 preflight helper를 추가 위임하고 MAIN이 per-sample 실행 직렬화/회귀를 추가해야 한다.
02 BLOCK 수정 완료: 같은 backend agent가 lookup_assessment/공통 fingerprint/helper 테스트를 추가했다(backend24pass).
MAIN이 execute 전 조회와 sample별 실행 lock을 추가하여 replay·동시 동일 입력의 중복 모델 호출을 막았다.
새 sample의 invalid 출력은 UNKNOWN/review로 저장되고, 추론 대기 중에도 operator state lock을 사용할 수 있다.
focused40pass/full86pass/hashPASS, 실제 reviewer 재검토 대기.
02 reviewer 재검토 PASS: focused backend/integration/output regression 56 passed, 1 warning, 1.03s; hashPASS.
기술 fixture 연결은 완료했지만 실제 media resolver/URL/라이브 입력은 미완료다.
03 explorer: Clef 제품/제공사 미식별 BLOCKED; 신경망/CV 패키지 없음, FFmpeg 실행 가능, GPU 확인 근거 없음.
03 model_engineer: ingestion.py와 전처리 테스트만 수정, 실제 FFmpeg 합성 영상/child lifecycle 25 passed (skip 없음).
03 MAIN: asset-map/byte-budget/memory-frame resolver 및 선택 constructor 주입, 공통 경계/통합 테스트 추가.
focused35pass/full121pass/hashPASS. 중립 window grid·실제 PTS·raw temporal reset·checksum/profile/time를 기록한다.
실제 validation 납품이 없어 manifest 검사/모델 지원 범위 선정/실측 비교는 BLOCKED. preprocessor는 이벤트 모델이 아니다.
03 reviewer actualfocused35pass/0skip/1warning/hashPASS, 독립 전처리 기술PASS.
사용자 추가 MP4+annotations JSON 요구는 기존 단계에 반영한다. annotations/caption/cot/answer/bbox/frame_id는 평가 전용.
동일 사건 c1/c2 scenario_group을 공유하고 정답으로 sampling/관측을 생성하지 않는다.
공통 schema 기본1.1/각risk축null을 MAIN이 변경했으며 backend/eval 영향은 실제 담당 역할에 순차 위임 후 재검증/동결한다.

## 하네스 v2에서 완료
- [x] 공통 typed I/O, opaque media refs, bounds/extra 필드 검증
- [x] shared execution: timeout/schema/provider/evidence/input-mutation 실패 → review
- [x] mock 이름 분리와 real 미설정 명시
- [x] fixture → adapter → assessment → Incident → GET vertical slice
- [x] demo 1..6, ACK 상태/audit/idempotency, WS push/reconnect snapshot
- [x] suppressed restore API, UNKNOWN 위험 표현
- [x] source/scenario/hash 기반 manifest validation + batch evaluator 기본 metrics
- [x] MAIN + 5 role ownership, handoff, 계약 변경 hash 검사
- [x] 한국어 단계별 prompts/시작 안내/평가 보고서

## 순서대로 남은 작업
- [ ] P0 사용자 환경에서 설치/pytest/Codex 에이전트 로딩 확인
- [ ] P0 frontend 담당자에게 UNKNOWN/카메라ID/WS/ACK/Idempotency 의미 확인
- [ ] P0 실제 모델→repository 실행 wiring + 실제 evidence media URL
- [ ] P1 Clef provider/API 접근/입력 modality/SDK 공식 문서 확인 (진행 전 명확히)
- [ ] P1 data/asset-map ingestion + fixed frame sampling + neutral cache/provenance
- [ ] P1 local_cv 실제 구현 + decode/track/pose 워커 + 지원 이벤트 검증
- [ ] P1 clef_direct 실제 구현; 접근 불가면 BLOCKED 기록
- [ ] P1 general_vlm 실제 구현 + schema constrained output
- [ ] P2 동일 validation 샘플 세 모델 run + 오류/비용/전처리 coverage
- [ ] P2 dataset/run-config/코드·weight/cache 고정 후 test 1회
- [ ] P2 후보 누락을 포함하는 pipeline end-to-end 평가
- [ ] P3 실제 video clipping/bbox/frame evidence, SQLite/PostgreSQL transactions/outbox
- [ ] P3 operator auth, audit retention, multi-worker load/camera throughput
- [ ] Stretch router→VLM, multi-camera merge

실제 모델/실제 데이터 완료는 mock 테스트 통과로 체크하지 않습니다.

## 2026-10-07 신규 benchmark v1 모델 선정 — 1단계

- 범위: `final_candidates_v1/`와 `477_modeling_benchmark_v1/` 직접 조사, 공식 근거에 따른 Local CV/VLM 우선 후보와 대안 추천, Clef 기능 확인. 기존 구현/공통 계약/동결 패키지는 유지한다.
- 사용자 제한: 최종 모델·실행 환경 전달 전 모델 다운로드, 유료 GPU 생성, 유료 추론, 학습 금지. 2·3단계 baseline 구현·실제 모델 평가는 대기한다.
- 등록 역할/TOML/소유 범위 확인 완료. MAIN은 문서·TASKS·통합, 조사와 검토는 실제 에이전트에 순차 위임한다. 모델/effort와 지시문을 적용하며 OS sandbox 강제 여부는 별도 보증하지 않는다.
- IN PROGRESS: `/root/benchmark_v1_inventory` (`explorer`) — 패키지/코드/스키마/실영상/입력 구성/정답 유무/검사 실행을 읽기 전용 조사.
- `.env`의 CLEF_API_TOKEN/CLEF_ACCOUNT/CLEF_MODEL 키 존재·비어 있지 않음 및 selector `clef`만 확인했다. 인증값을 출력하거나 API 호출하지 않았다. 실제 인증 성공은 미검증이다.
- 최종 산출물 예정: `reports/model-selection-v1.md`, `handoffs/benchmark-v1-selection.md`. 완료/막힌 항목과 실제 검사 명령은 결과 확인 후 기록한다.
- PASS: `/root/benchmark_v1_inventory` 조사 종료·파일 변경0. MAIN도 package validator 7×64=448 RGB frames, metadata inspector, 데모 MP4 checksum 6/6을 재검증했다. `reports/benchmark-v1-data-audit.md`에 코드/스키마/정답 유무/차이를 기록했다.
- PASS: `/root/benchmark_v1_cv_selection` (`model_engineer`) 공식 자료 조사 종료·파일 변경/다운로드/모델 실행0. 우선 `yolo26s-pose.pt`, 대안 `yolo11s-pose.pt`; pose+timestamp 추적+규칙 필요. MAIN 공식표 및 원논문 확인. 실제477성능은 미측정이다.
- IN PROGRESS: `/root/benchmark_v1_vlm_selection` (`model_engineer`) — VLM 후보/GPU·양자화/64프레임 변환/예상 비용 조사. CV 에이전트 종료 후 순차 생성했다.
- MAIN 기존 회귀 검사: `.venv/Scripts/python.exe -B -m pytest -q` →212 passed, warning1,18.00s; `scripts/check_contracts.py` → Frozen contracts match.
- 후속 구현 BLOCK: 공개 패키지에 GT/정상 negative reference가 없고, frozen prediction은 risk 숫자 필수·prediction null 불가로 기존 미측정-null 계약과 충돌한다. 원본 패키지/기존 계약 변경 또는 임의 숫자 채움은 하지 않았다.
- PASS: `/root/benchmark_v1_vlm_selection` 조사 종료·파일 변경/설치/다운로드/추론0. 우선 `Qwen/Qwen3-VL-4B-Instruct`, 대안8B-Instruct. 24GB/48GB GPU 및양자화는계획치이며 실제477메모리·속도미측정. MAIN config/parameter metadata 독립확인.
- PASS: `/root/benchmark_v1_clef_capabilities` 조사 종료·파일 변경/인증/추론0. `@cf/cloudflare/clef`와 selector `clef`, typed questions/이미지4장 제한/자유문생성불가를 공식검증. Hosted REST와openweights영상지원구분. 이미지serializer·계정접근·quota는미검증.
- MAIN contract probe: RAM의명시syntheticfixture만사용(제출/저장0). null severity schema거부와noncanonical0.123초를원contextvalidator가허용함을재현. 후속runner추가근거검사가필요하다.
- `reports/model-selection-v1.md` 초안 완료. 최종 reviewer 순차 검토 후1단계완료기록을확정한다. 2·3단계는사용자의최종모델/환경전달전실행하지않는다.

### 최종 상태 — 2026-10-08

- **1단계 완료 / reviewer PASS**: `/root/benchmark_v1_selection_reviewer`의 독립 검사 22 passed(경고1,5.57s), 계약 match, lock 23/23·영상 복사본 6/6 일치. 수정이 필요한 BLOCK급 문제 없음. 모델 성능 승인은 아님.
- MAIN 최종 검사: `.venv/Scripts/python.exe -B -m pytest -q` → **212 passed**, 기존 경고1,22.24s; `scripts/check_contracts.py` → **Frozen contracts match**.
- 산출물: `reports/model-selection-v1.md`, `reports/benchmark-v1-data-audit.md`, `handoffs/benchmark-v1-selection.md`, 감사용 contact sheets7개. 등록된 실제 에이전트5개를 순차 실행·종료하고 MAIN이 결과와 검사를 확인했다. 모든 에이전트 파일 변경0.
- **2·3단계 대기**: 최종 CV/VLM 모델과 GPU/환경 정보, benchmark owner의 미측정 위험축·실패 제출 정책이 필요하다. 실제 정답 비교에는 private GT/평가 rubric이 필요하다. Clef ID/기능은 이번에 확인됐으며 계정 접근·serializer·실응답은 다음 실행 단계에서 검증한다.
- 모델 다운로드·설치·유료 GPU 생성·API 추론·학습·실제 measured submission 모두0. 기존 하네스와 두 동결 입력 패키지 및 공통 계약은 유지했다. 전체212통과를 새 모델 정확도로 해석하지 않는다.
# Active baseline execution — 2026-10-08

- IN PROGRESS: User-authorized real YOLO26/ByteTrack, Clef and DeepSeek baseline;
  protected benchmark/data folders remain read-only. $5 persistent budget cap.
- DONE: Actual sequential preflight and CV agents; CV focused 15 tests PASS.
- DONE: MAIN shared bridge/budget/media guard; full 294 tests PASS, contract PASS.
- DONE: Clef/DeepSeek actual agents and focused tests; official weights downloaded.
- DONE: Actual CV ITEM_01 and actual Clef/DeepSeek HTTP 200 access checks; same
  $5 ledger has 2 calls, $0.10003968 reserved, $0.02501982 usage-based estimate.
- DONE: Evaluation agent, fixed JPEG 80 compatibility adjustment, numerical
  boundary fix. MAIN full 326 tests PASS; contract PASS; reviewer focused35 PASS.
- DONE: Actual 7 ITEM × 3 repetitions × 2 conditions suite, 42/42 attempts;
  raw/diagnostics/common/evaluation/analysis/plot artifacts under runs/baseline-final.
- DONE: Real CV 21 successes, VLM 42 responses, Clef 15 responses. Protected
  input snapshots match. Credential scan332files/stageddiff: zero matches.
- FAILED ACCEPTANCE: Selected-frame grounding direct16/21, pipeline13/21;
  full3stage+output9/21. JSON structure42/42; latency42/42under120s.
- INCOMPLETE: Clef6 client-side payload_limit cases (ITEM03/06); VLM13 evidence
  timestamp errors; free event labels map to common uncertain/humanreview.
- COST:59paidrequests incl2probe, reserved3.45235968USD; usagepeakestimate
  0.286777356USD. Actualinvoiceunavailable; global5USDledger retained.
- DONE: Independent final report-integrity review PASS and final handoff.
  Reviewer independently reconciled42attempts/59calls/costs/21pairedinputs/
  preservedfailures and scanned209generatedfiles with zero credential matches.
  Performance acceptance remains FAIL, semanticmetricsN/A, summary=incomplete.
  Report reports/benchmark-baseline-final.md; handoff
  handoffs/benchmark-baseline-results.md. Latest326testsPASS/contractPASS.
- BLOCKED METRICS: No ground-truth or normal labels; accuracy/false alarms and
  semantic evidence correctness cannot be measured. See
  docs/benchmark-baseline-plan.md and handoffs/benchmark-baseline-active.md.

# Active baseline improvement — 2026-10-08

- DONE / PARTIAL: User-authorized input guard correction, failure analysis, speed
  improvement and additional real whole-pipeline experiments. Prior results kept.
- PLAN: docs/benchmark-improvement-plan.md; source/data folders read-only,
  existing $5 ledger retained, max additional reservation $1.48047360.
- ACTUAL AGENT: /root/improvement_audit (explorer), read-only analysis; sequential.
- DONE: Audit confirmed client byte/token mismatch, timestamp failures and CPU
  detector/pose bottleneck; no real GT/normal/zone labels available.
- MAIN GATE: explicit pose-off registry/CLI plus planned budget check; registry6
  tests PASS, full328 PASS (warning1), contract hashes re-frozen and match.
- DONE: /root/improvement_clef removed byte/token proxy while retaining bounded
  request and paid budget; focused25 PASS, MAIN full331 PASS/contract match.
- ACTUAL AGENT: /root/improvement_vlm_grounding, DeepSeek exact-copy transport;
  only its adapter/tests, sequential after Clef gate passed.
- DONE: DeepSeek v2 transport/exactcopy, focused38 PASS; MAIN full340 PASS /
  contract match, no timestamp repair. MAIN CLI cost-preflight focused2 PASS.
- ACTUAL AGENT: /root/improvement_cv_profile, truthful pose-off metadata/tests.
- DONE: CV profile focused20 PASS; MAIN full344 PASS/contract match. Actual7×64
  VLM serializer and previous Clef03/06states passed local preflight with zero API.
- ACTUAL AGENT: /root/improvement_pipeline_evaluation, pipeline safety/metrics.
- DONE: Eval focused94 PASS, MAIN full355 PASS/contract match; whole-chain vs
  fallback metrics and safe suppression/billing checks integrated.
- ACTUAL AGENT: /root/improvement_readiness_review, read-only pre-execution gate.
- DONE: Independent readiness PASS, original206files/protected37 unchanged,
  credentialscan213files0, ledger arithmetic and contracts independently checked.
- DONE: actual canonical64 suite7×1×2 then separate pose-off pipeline3×1.
- DONE: canonical64 14actualattempts, wholepipeline7/7, direct6/7. One direct
  malformedJSON retained; source unchanged. Ledger80/4.63271424reserved.
- DONE: pose-off3 final outputs valid, whole-chain2/3; ITEM_02 actual Clef429
  daily-free-allocation exhausted; fallback not counted as full pipeline success.
- ACTUAL AGENT: /root/improvement_vlm_json_labels, model_engineer, only adapter/tests.
- DONE: isolatedv3 JSON-label ITEM04 target1call/4096outputtokens/.058752reserve;
  planned before target results, focused67 PASS, MAIN386 PASS/contract match,
  /root/improvement_readiness_review follow-up PASS before paid execution.
- DONE: actual v3 ITEM04 schema/evidence pass1/1, 24.917s; existing6/7 cohort
  failure retained. All18 new attempts executed; protected inputs/original results unchanged.
- DONE: paired CV median time reduction34.5% (3items); successful whole-chain
  paired total median reduction22.4% (2items). Semantic non-regression unmeasured.
- DONE: cumulative87reservations/$4.99158528, known86 usage sum$0.523827864;
  one usage unknown, full cost estimate/invoice null. Additional paid calls stopped.
- RESULTS: reports/benchmark-improvement-final.md; next user actions and commands
  in reports/benchmark-improvement-next-actions.md and docs/benchmark-improvement-run.md.
- DONE: /root/improvement_readiness_review final result/integrity PASS;
  independently revalidated18/18saved diagnostics, paired timings, ledger,
  original206/protected37hashes, credentials333files0, contracts match.
  No further paid execution. Semantic accuracy and external inputs remain blocked.
- BLOCKED METRICS: semantic accuracy/false alarms require real GT and negatives;
  no current model integration PASS can substitute for those metrics.

## Benchmark explanation HTML — 2026-10-08

- DONE: MAIN only, no subagents: `reports/477-benchmark-explained.html`.
- Explains original7ITEM/64frames, suggested vs actual pipelines, real CSV
  fields/examples, final-vs-whole-stage validation, measured results and blockers.
- Self-contained HTML/CSS/JS, CSV example filters/time-unit toggle, print action.
- Static check: inline JavaScript syntax PASS, duplicate IDs0, broken links0,
  external asset dependencies0. No provider calls or benchmark/data edits.

## Clef effectiveness diagnosis — 2026-10-08

- DONE: MAIN read-only code/raw-response analysis, no new provider execution.
- Found actual VLM route fixedTrue; CV/Clef features not sent to VLM; sameVLM
  transport composition7/7; Clef proposals6human_review/1invoke_vlm/0no_action.
- All7 CV states incomplete: no ROI/event classifier/measured risk axes.
- Report: `reports/clef-effectiveness-diagnosis.md`. CV+VLM ablation not run;
  semantic accuracy superiority unproved. Stage-removal timing explicitly simulated.
- Priority: GT/taxonomy/operational rules, CV role definition, fair no-Clef ablation,
  then independent Clef routing value verification. No behavior/contract changes.

## YOLO64-frame evaluation scope — 2026-10-08

- DONE: MAIN verified all7ITEM actual camera sampling from saved CV raw metadata.
- Added explanation to existing `reports/477-benchmark-explained.html` (#yolo):
  detection vs tracking/action proof, per-ITEM counts/intervals/limitations,
  exhaustive bbox GT requirement and separate dense temporal evaluation plan.
- Official YOLO validation documentation/ByteTrack paper checked and cited.
- Static HTML IDs/local links/JS syntax PASS. No new model/API/test execution,
  no protected source change. Accuracy remains unmeasured, dense evaluation unrun.

## New standalone full pipeline benchmark — 2026-10-08

- IN PROGRESS: `new_477_piprline/` isolated handoff package; MAIN owns contracts,
  scripts, README, portable export, integration and generated artifacts.
- DONE: actual explorer `/root/new_pipeline_inventory` read-only inventory:
  6 matching MP4s, absent exhaustive boxes/private labels/routing truth. No edits/calls.
- DONE: 12 predeclared representative items, source count1..6, 768 total slots;
  neutral video copies and frame manifests frozen; original hashes unchanged.
- DONE: actual evaluator `/root/new_pipeline_metrics` focused38PASS; MAIN425 full
  tests PASS; shared execution boundary refrozen and contract match; portable44PASS.
- DONE: `/root/new_pipeline_contract_review` initial BLOCK fixed (strict route bool,
  CV output gate, metric error propagation, execution-blocked vs skipped distinction).
  Rereview PASS, independent46+56PASS,791 frozen inputs mismatch0, inherited ledger match.
- DONE: MAIN rerun432 fullPASS57.98s/contracts match/portable56PASS; preflight12PASS,
  forecast reservation1.08251136USD vs remaining0.00841472USD,0paid calls.
- DONE: `/root/new_pipeline_cv` model_engineer config, only new CV adapter/tests;
  focused15PASS, MAIN447fullPASS59.21s/contracts match/portable72PASS.
- DONE: `/root/new_pipeline_clef` model_engineer config, source-scoped real
  typed-question serializer/routing, focused38PASS; MAIN485fullPASS59.23s,
  contracts match/portable111PASS. No agent API calls.
- DONE: `/root/new_pipeline_vlm` model_engineer config, source-resolved
  DeepSeek64JPEG adapter/tests43PASS28.54s; MAIN528fullPASS92.88s/contracts match,
  standalone154PASS45.06s. No real APIs yet.
- IN PROGRESS: final readiness rereview `/root/new_pipeline_contract_review`, then
  MAIN will freeze evaluator and execute actual12items with authorizedpaid profile.
- BLOCKED: scored detection/routing/event/evidence quality needs reviewed GT; README
  prose retained only as non-scored reference. Initial API block from cumulative5USD
  ledger was superseded by explicit user additional authorization below; no reset/refund.
- NEW INPUT OBSERVATION: selected final frames of SRC05/SRC06 visually black;
  keep frozen selection and flag input quality, do not replace favorable frames.
- UPDATE: user explicitly removed previous cost restriction for current DeepSeek/Clef
  calls. MAIN recorded scoped additional authorization in new folder, preserving
  prior87reservations. Provider quota/auth restrictions remain external, no invented pass.
- RESUMED: `/root/new_pipeline_cv` interrupted with no owned files written;
  MAIN inspected and resumed same owner. Portable worker only adapts SRC01..06
  and local COCO weights; original worker/media/benchmark unchanged.
- DONE: MAIN corrected newly authored truth-schema JSON syntax before API,
  schema regression9PASS/preflight12PASS; paid authorization honored (no fixedtotalcap).
- PLANNED REAL PROFILE: config/full_pipeline.json invokes VLM on every non-ok Clef
  result (including model/conversion errors and skipped after YOLO failure), with
  explicit upstream-error/fallback, no fabricated skipped source output.
- DONE: final reviewer found CV invalid-worker raw response overwrite; sequential
  `/root/new_pipeline_cv` preserved raw response plus separate transport record,
  focused16PASS2.61s. MAIN reexport, full529PASS92.27s/contracts match/
  standalone155PASS32.33s. Final reviewer rechecking before real execution.
- DONE: readiness reviewer PASS; independentCV16PASS2.38s/contracts match.
  MAIN froze evaluation.lock.json and actual final preflight12PASS,0paid calls,
  forecast reservation1.08251136USD, remainingnull under explicit additional approval.
- RUNNING: MAIN sequential actual12items under results/full_pipeline_v1, CPU
  yolo26s.pt/ByteTrack + existingClef + DeepSeek-flash, one repeat, raw responses retained.
- INTERRUPTED FOR FIX: actual P001 YOLO ok and VLM fallback ok; Clef rejected
  CV-derived input before API (input_contract_invalid, benchmark category). MAIN
  stopped run before dependent items; partial full_pipeline_v1 preserved (1 CSV row,
  actual VLM usage estimate0.0200322USD, invoiceunknown). P002 incomplete artifacts
  are not a completed result. Sequential Clef owner diagnosing actual mismatch.
- DONE: Clef actual-input contract bug fixed: single-observation unknown gap stays
  null; other invalid numeric/multi-observation null gaps rejected. Actual P001
  offline serializerPASS27980bytes; focused43PASS0.60s. MAIN534fullPASS92.34s/
  contracts match/portable160PASS32.50s; sequential reviewer rechecking beforev2.
- DONE: reviewer v2 readiness PASS; independentClef43PASS0.82s andactualP001
  serializer27980bytesPASS/API0. MAIN confirmed official Clef/DeepSeek pricing;
  at15:32UTC Oct08 DeepSeek off-peak applies (0.15/0.003/0.60USDperM).
- RUNNING: MAIN full_pipeline_v2 fresh12items; v1 retained separately. Runtime
  config records off-peak usage-estimate tariff; invoice cost remainsunknown.
- DONE: full_pipeline_v2 actual12items complete; YOLO12ok/Clef12ok/VLM12actual
  responses, finalpolicyok2/error10. Schema12/12+inputreference12/12, humanreview
  policyinvalid18sourceoccurrences; semanticGTscoringstillBLOCKED (0reviewedtruth).
- DONE: CSV12rows, originalraw36pairs, compactCSVmax8477characters, actualauditPASS
  768JPEGhashes/maps/unchangedconvertedoutputs,791input+7evaluator+243originalhashes;
  secretvalues3/textfiles254,nohits. Original87ledgeridentical; new13DeepSeek+12Clef.
- DONE: actualv2 usageestimate0.186942456USD, invoiceunknown; v1partialretained.
  CSVreader128KiB defaultlimit fixed inofflinehelpers; nofrozen scoringchange.
- DONE: finalMAINfull534PASS88.06s/contractsFrozenmatch/portable163PASS30.71s.
  Finalreadonly actualresultsreview PASS; README+RESULTS handoff updated.
- DONE 2026-10-09 KST: user resumed interrupted final reviewer after agentusage
  limit; same actual `/root/new_pipeline_contract_review` completed FINALPASS
  technical integrity/handoff (not model performance). IndependentCSV12rows/
  raw36pairs/768JPEG/791input+7evaluator+243originalhashes andpolicy18violations
  verified; independentCSV3testsPASS0.14s. AdditionalAPI/modelcalls0.
- HANDOFF READY: new_477_piprline/README.md, DESIGN.md, ground_truth pendingfiles,
  results/full_pipeline_v2/results_readable.csv + all referenced raw/normalized
  responses, RESULTS.md. Existing benchmark/data/originalbaseline protected.
- STILL BLOCKED: reviewed bbox/routing/event/evidence truth and normal controls/
  operating zones/policy; precision/recall/mAP/event/route/evidence quality N/A.
  Actual output-policy pass2/12, not a claim all12models passed performance.

## 2026-10-09 정답 확보·팀원 CSV 자동 채점 요청

- RUNNING MAIN: 기존12문제/64프레임 유지, 직접 영상 프레임 검수로 사건/라우팅 정답 작성.
  전문가 gold GT로 표시하지 않고 AI visual-reviewed demo reference로 출처 기록.
- RUNNING sequential `/root/annotation_detector` model_engineer: 독립 RT-DETR-L
  박스 초안 도구+테스트 2파일만. MAIN 공식 자산 rtdetr-l.pt 다운로드 완료66,511,432bytes.
  평가 YOLO26s를 자체 정답으로 재사용하지 않음. 24프레임 박스 초안 후 직접 검수.
- PLANNED: ground_truth 검수/동결 → 팀 입력/빈CSV/자동채점Python 패키지 → 기존결과 재채점
  → 정답/라우팅이 준비된 뒤 파이프라인 오류 개선. 기존원본/실행결과 유지.


## 2026-10-09 HACKATHON-DAY — 백엔드 API 연동 준비
- Scope: app/api/{contracts,errors,media,routes}.py, app/main.py, repositories/memory.py,
  services/incidents.py, backend tests, API doc/examples, frontend handoff. 프론트변경없음.
- 완료 기준: 기존API보존, snapshot/WS실행ID, nullable단위/미분석상태,
  ACK최신rank, trusted근거이미지/영상window, 공통오류, synthetic예제, 계약hash/회귀PASS.
- Focused: Python3.12 .venv-test, tests/backend + tests/integration/test_model_ingestion.py: 61PASS.
- Python3.14환경은FastAPI/Pydantic초기화에서실패;3.12전용환경으로검증.
- 최종: Python3.12 .venv-test + 기존 FFmpeg를 테스트 프로세스 PATH에만 지정. 전체 549 PASS / 52.75초; 신규 계약 15 PASS; contracts match; diff check PASS. 실제 provider 호출 없음.

- MAIN 최종 코드 리뷰 PASS: 등록 camera 수 동적 집계, ACK 행동 시점 순위, HTTP/WS snapshot 일치,
  입력 provenance에 속한 evidence만 제공, root 밖 video 차단, 미측정 수치 null 유지.
- 프론트 tracked 파일 변경 없음. 기존 미추적 .vite/는 그대로 유지.
- 계약 hash는 현재 Windows 작업 사본 기준으로 재동결했다. 기존 모델 코드의 의미 변경은 없고
  변경 없는 파일의 hash 차이는 클론의 줄바꿈 형식과 관련된다.
- 한계: 메모리/1worker/인증 없음, crop/실시간 영상/실제 bbox 추적/단계별 실측 집계는 미구현.
  준비만 하고 ingest하지 않은 frame resolver는 앱 메모리에 남을 수 있어 운영용 cache lifecycle은 후속 과제.
## 2026-10-09 HACKATHON-DAY — scripted multi-camera demo
- Scope: app/demo, config/demo-scenario.json, config/main/memory/routes, backend tests, docs/DEMO_SCENARIO and handoff. No AI or dataset execution.
- Completion: grouped SCENE-A/CAM01-03, primaryCAM02 only highlight, editable independentCAM06 review example, development disabled, safe camera filenames, metadata endpoint. PASS.
- Python3.12 + existingFFmpeg processPATH: full633PASS1SKIP102.71s/contracts match. Final incomplete-axis guard: focused4PASS0.16s.
- Actual Vite→API metadata/2events/CAM02incident/CAM06review/restunobserved verified. Frontend15unit+1integration+buildPASS.
- Config/API docs hashes updated deliberately; model/incident frozen schemas and benchmark originals unchanged.
- Missing input video and browser runtime prevent actual media synchronization/visual QA; Not verified. Details: handoffs/demo-scenario.md. No commits/push.

## HACKATHON-DAY — candidate threshold >65
- User selected strict >65 yellow representative-camera border, no fixed CAM06 review.
- Scripted CAM06 numericrisk71/confidence0.89/reviewfalse; no model call.
- Frontend17unitPASS/1actualAPIintegrationPASS/buildPASS; backend633PASS1SKIP98.41s/contracts match.
- API doc hash re-frozen after explicit display policy update. Server risk/ranking/suppression/ACK preserved. Visual browser QA still Not verified.
