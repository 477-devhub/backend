# 02 backend 통합 — 2026-10-07

## 실제 담당

`/root/stage02_backend_engineer`: app/api/**, app/services/**, app/repositories/memory.py, tests/backend/** 범위만 위임.
등록 TOML 역할 model gpt-6.1-sol/medium을 사용했다. 중첩 위임·병렬 writer·git 쓰기·설치 없음.
MAIN은 worker 종료 후 shared main/settings/문서/hash/통합 테스트를 순차 수정했다.
유효 sandbox 강제 여부는 실행 도구로 독립 조회할 수 없다는 기존 한계를 유지한다.

## 변경 파일

worker: `app/services/incidents.py`, `app/repositories/memory.py`, `tests/backend/test_assessment_service.py`.
MAIN: `app/config.py`, `app/main.py`, `.env.example`, `tests/integration/test_model_ingestion.py`,
`docs/model-contract.md`, `docs/api-contract.md`, `docs/contracts.lock.json`, `TASKS.md`, 관련 handoffs.

## 결과와 최소 연결 설계

`apply_assessment(store, mi, assessment) -> AppliedAssessment(decision, record, changed)`는 execute에서 검증된 출력만 저장한다.
MAIN의 `create_app(..., adapter=...)` 및 `app.state.ingest_model_input(mi)`가 registry→execute→policy→
Incident/Suppressed→MemoryStore→WS snapshot을 연결한다. 추가 추론 HTTP endpoint는 없다.
모델 호출은 lock 밖이며 변경 저장과 snapshot publish는 lock 안이다.
같은 입력 replay는 ACK/dismiss/restored 및 revision을 보존하고, 같은 ID의 다른 입력/unknown camera는 거부한다.
수정 후 완료 replay는 execute 전 조회로 재추론하지 않으며 동일 ID 동시 호출은 별도 sample lock으로 직렬화한다.
provider 내부 retry/cancellation/restart 이후 비용/요청 idempotency까지 주장하지 않는다.
ledger는 단일 memory worker용이며 demo reset/restart 시 초기화된다.

MODEL_ADAPTER 기본 local_cv는 미설정 real slot이며 조용한 mock 대체가 없다.
MODEL_TIMEOUT_SEC는 양수 유한 값이어야 한다. provider SDK는 routes에 추가하지 않았다.
stage1_label/resumed_walking 관측이 없으면 null로 보관한다.

## 실제 명령과 결과

| 실행자 / 명령 | 결과 |
|---|---|
| worker `.venv/Scripts/python.exe -m pytest tests/backend -q` | 19 passed, 1 warning, 0.55s |
| MAIN `.venv/Scripts/python.exe -m pytest tests/backend tests/integration -q` | 31 passed, 1 warning, 0.72s |
| MAIN `.venv/Scripts/python.exe -m pytest -q` | 77 passed, 1 warning, 1.22s |
| MAIN `.venv/Scripts/python.exe scripts/freeze_contracts.py` | Contract hashes written |
| MAIN `.venv/Scripts/python.exe scripts/check_contracts.py` | Frozen contracts match. |
| MAIN TestClient 실제 응답 캡처 | handoffs/frontend.md에 14개 API/WS 응답 저장 |

검증은 명시 mock_local_cv, synthetic 계약 test double, 미설정 real slot 및 synthetic demo의 연결 검증이다.
실제 영상 추론·모델 정확도/비용 평가가 아니다. 실제 media가 없으므로 503/available=false를 유지한다.
프론트 각 endpoint·WS 첫 snapshot 예제를 저장했지만 팀원에게 직접 전송하지 않았다.

## blocker / 검토

프론트 계약 합의, 실제 데이터/영상/asset map, provider 접근과 Clef capability는 계속 BLOCKED.
실제 evidence media URL/clip sampling/live ingestion은 후속 단계이며 이번 완료에 포함하지 않는다.
reviewer가 ACK 중복/rank/UNKNOWN/재연결/suppression restore 및 소유권을 검토한 뒤 기술 판정을 후속 기록한다.

## 첫 reviewer BLOCK

`/root/stage02_reviewer`가 suppressed 입력의 같은 sample replay에서 새 invalid 출력이 가려지는 것을 재현했다.
execute의 schema_or_contract/review 출력이 생겼지만 apply_assessment가 최초 suppressed decision을 반환하여
active_count=0, suppressed_count=1을 유지한다. 77개 기존 테스트로 커버되지 않은 안전 결함이다.
기존 입력 결과를 execute 전에 조회하고 같은 ID의 동시 추론도 직렬화하여 새 실패를 발생시킨 뒤 무시하지 않아야 한다.
backend-owned 조회 helper는 실제 backend agent에게 재위임하며 MAIN은 호출/동시성/회귀를 수정한다.
수정 및 재검토 PASS 이전에는 다음 의존 단계로 진행하지 않는다.

## BLOCK 수정 결과

같은 실제 `/root/stage02_backend_engineer`가 `lookup_assessment(store, mi) -> AppliedAssessment | None`을 추가했다.
known camera 및 전체 input fingerprint를 조회 단계에서 검증한다. worker 수정은 incidents.py와 backend 테스트에 한정했다.
실제 backend focused: 24 passed/1 warning, 0.51s.
MAIN은 조회를 execute 앞에 두고 sample별 별도 lock으로 동시 동일 입력도 한 번만 추론하도록 연결했다.
사용하지 않는 sample lock은 weak reference로 해제되며 state mutation lock과 분리된다.
MAIN 회귀는 완료 replay 호출수=1, concurrent 호출수=1, concurrent ID/input conflict 거부,
새 sample의 schema 오류→UNKNOWN/review 및 모델 대기 중 state lock 접근을 확인한다.
수정 후 focused backend/integration 40 passed/1 warning/1.07s, full86 passed/1 warning/1.62s.
freeze_contracts 재실행 및 check_contracts Frozen contracts match.
최초 BLOCK은 이력으로 유지하며 reviewer 재검토 결과를 별도 기록한다.

## 최종 기술 판정

동일 실제 `/root/stage02_reviewer` 재검토 **PASS**. 변경 파일 없음.
직접 실행한 backend/integration/output regression focused56 passed/1 warning/1.03s 및 hashPASS.
이전 replay defect, 동시 호출, ACK/rank/UNKNOWN/재연결/restore/missing media를 확인했다.
전체86은 MAIN 실행 결과이고 reviewer 자체 실행은56개이다. 실제 모델/영상/팀 합의/fairness는 여전히 BLOCKED.
