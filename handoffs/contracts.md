# 계약 전달 기준 — 2026-10-07

최신 기본 schema_version: **1.1** (2026-10-07 사용자 추가 요구). 소스는 `app/schemas/`와 `docs/model-contract.md`, `docs/api-contract.md`,
`docs/dataset-handoff.md`, `docs/evaluation-contract.md`이다. 기술 해시는 `docs/contracts.lock.json`에 보관한다.
기술적 동결은 프론트/데이터 팀의 합의 완료를 뜻하지 않는다. 두 팀의 확인 자료는 아직 없다.

## 01 변경점과 설계

기존 Pydantic 출력 객체를 그대로 신뢰하면 `model_copy`로 confidence/축/비용의 검증을 우회할 수 있었다.
MAIN이 공통 ContractModel에 `revalidate_instances="always"`를 적용하여 출력 및 중첩 인스턴스를 재검증한다.
선택 근거: 출력만 dict로 dump하는 방식보다 dict 내부의 잘못된 중첩 객체까지 동일하게 검증하며,
adapters별 검증을 추가하는 방식보다 모든 adapter에 하나의 실행 계약을 제공한다.
JSON 필드와 버전은 바뀌지 않는다. 잘못된 출력은 기존 execution 경계에서 schema_or_contract로 기록하고
risk_axes=null, risk=null, level=UNKNOWN, 사람 검토가 된다. 위험 계산에 confidence를 곱하지 않는다.

수정: `app/schemas/model.py`, `docs/model-contract.md`, `tests/contracts/test_execution_validation.py`, 계약 lock.
Windows에서도 lock 경로 키를 동일하게 전달하도록 `scripts/freeze_contracts.py`가 POSIX slash 경로를 저장한다.
16개 출력 우회 회귀 사례를 확인했다. 수정 전 11 failed/5 passed, 수정 후 전체 57 passed.
실제 모델·미디어·dataset 검증 결과가 아니다.

## 모든 역할의 고정 기준

추가 요구의 차이: RiskAxes 각각 0..1 또는 null. 하나라도 null이면 총 risk=null/UNKNOWN/review.
schema_version 1.0 legacy input/완전 측정 output은 읽을 수 있지만 축별null output은 1.1 필수다.
MP4 동봉 JSON의 annotations 전체는 평가자 전용이며 caption/cot/answer/bbox/frame_id를 추론에 복사하지 않는다.
자세한 변경은 `handoffs/03_contract_delta.md` 및 최신 model/API/dataset 계약을 따른다.
아래 01/02/03 기록 중 버전1.0은 당시 이력이며 현재 writer는1.1을 사용한다.

- 모든 모델 호출은 `app/models/execution.py`의 `execute()`로 통과시킨다.
- 미측정/실패/mock/낮은 확신은 review이며 UNKNOWN을 임의 0/50으로 대체하지 않는다.
- suppression은 명시 normal + confidence >= .90 + measured risk <20만 허용하고 복구 경로를 유지한다.
- evidence는 실제 입력의 frame_id/timestamp에 속해야 한다. 데모는 synthetic으로 표시한다.
- provider SDK/요청 직렬화는 `app/models/adapters/`에만 둔다. adapter는 event loop를 차단하지 않는다.
- real slot은 mock으로 대체하지 않는다. Clef 제품·API·modality는 확인 전 추정하지 않는다.
- 정답/manifest/라벨 경로는 추론에 넣지 않는다. source/scenario/hash 그룹은 split을 넘지 않는다.
- 각 역할은 docs/ownership.md의 허용 경로만 수정하고 공유 변경은 MAIN에게 handoff한다.
- 사용자 지시로 서브에이전트는 순차 실행하며 중첩 위임·optional_parallel은 실행하지 않는다.

## 계약 확인 대기

03 기술 변경: ASSET_MAP/ASSET_ROOT 선택 설정, MediaResolver.from_asset_map/read(max_bytes)/with_assets,
create_app(media_resolver=...) → MediaIngestion constructor 주입 및 내부 prepare_model_input을 추가했다.
전처리는 고정 window grid만 사용하고 실제 PTS와 JPEG bytes에 연결된 새 evidence를 만든다.
PreparedMedia에 input/resolver/hash/profile/decoder-version/preprocessing_ms가 있으며 supplied temporal_state는 초기화한다.
실제 모델 슬롯이 sampler를 자동 소비하거나 라이브 영상이 연결된 것은 아니다. feature/disk cache도 미완료다.
실제 media/manifest가 없어 팀 납품 검사 및 모델 성능/fairness 검증은 BLOCKED다. 새 shared hash를 동결했다.

02 기술 변경: Settings에 MODEL_ADAPTER(기본 local_cv)/MODEL_TIMEOUT_SEC(기본5, 양수 유한)를 추가했다.
MAIN create_app의 adapter 주입 및 app.state.ingest_model_input 내부 연결, execute→저장→WS가 fixture에서 작동한다.
sample_id는 immutable input을 식별하며 replay는 기존 사람의 ACK/dismiss/restore 상태를 보존한다.
새 관측에는 새 sample_id를 사용한다. 완료 replay는 추론 전 cache 조회, 동일 ID 동시 요청은 별도 실행 lock으로 조정한다.
provider 내부 재시도·취소·재시작 후 과금 idempotency는 보장하지 않는다.
모델 suppressed의 stage1_label/resumed_walking은 미측정 null이다. 프론트 팀 확인 대기 항목이다.
MODEL_ADAPTER=mock_*는 명시적 mock 연결 확인이고 real 모델 슬롯은 여전히 미설정 실패다.
설정/문서 해시는 MAIN이 재동결했다. 전체77pass/hashPASS; actual model/media completion을 뜻하지 않는다.

프론트: `handoffs/frontend-contract.md`의 null/UNKNOWN, ID, ACK, WS, Idempotency-Key, clip/restore 규약.
데이터: `handoffs/data-contract.md`의 실제 미디어·manifest·asset map·group·라벨/관측 분리 규약.
명시 답변 없이 팀 간 합의를 완료 처리하지 않는다. 변경 합의가 생기면 MAIN이 schema/docs/tests와 hash를 함께 갱신한다.

## 검증 명령

- `.venv/Scripts/python.exe -m pytest tests/contracts tests/models tests/integration -q`: 39 passed, 1 warning, 0.30s.
- `.venv/Scripts/python.exe -m pytest -q`: 57 passed, 1 warning, 0.82s.
- `.venv/Scripts/python.exe scripts/freeze_contracts.py`: Contract hashes written.
- 해시 검사 및 reviewer 결과는 `handoffs/01_contract.md`에 후속 기록한다.
