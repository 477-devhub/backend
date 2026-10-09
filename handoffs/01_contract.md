# 01 계약 검토 — 2026-10-07

담당: MAIN `/root`. 공통 수정 및 계약 hash 갱신을 직접 수행했다.
완료 기준: 안전 계약 검토, 전달 자료 작성, P0 출력 검증 우회 수정, focused/full/hash PASS,
reviewer 판정. 팀 합의와 실제 자료는 별도 외부 blocker이다.

## 변경 파일

`app/schemas/model.py`, `docs/model-contract.md`, `docs/contracts.lock.json`,
`tests/contracts/test_execution_validation.py`, `scripts/freeze_contracts.py`, `TASKS.md`,
`handoffs/contracts.md`, `handoffs/frontend-contract.md`, `handoffs/data-contract.md`, 이 파일.

## 실제 검증

| 명령 | 결과 |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests/contracts/test_execution_validation.py -q --tb=no` (수정 전) | 11 failed, 5 passed, 1 warning, 0.19s |
| `.venv/Scripts/python.exe -m pytest tests/contracts tests/models tests/integration -q` (수정 후) | 39 passed, 1 warning, 0.30s |
| `.venv/Scripts/python.exe -m pytest -q` | 57 passed, 1 warning, 0.82s |
| `.venv/Scripts/python.exe scripts/freeze_contracts.py` | Contract hashes written |
| `.venv/Scripts/python.exe scripts/check_contracts.py` | Frozen contracts match. |

Windows의 freeze가 lock 키를 역슬래시로 바꾸는 것을 실제 diff에서 확인했다.
freeze_contracts.py의 경로 표현을 as_posix()로 고정하고 재동결/검사하여 OS 간 전달 가능한 기존 slash 키를 유지했다.

전달 자료는 파일로만 작성하고 팀원에게 전송하지 않았다.
schema_version 1.0 및 JSON 구조는 유지했다. 기술 hash 동결을 팀 합의라고 표시하지 않는다.
모든 서브에이전트는 동일 `handoffs/contracts.md` 및 lock을 기준으로 작업해야 한다.

## 외부 blocker / 실제·mock 구분

프론트 UNKNOWN/ACK/WS/ID/Idempotency 합의와 데이터 담당자 전달 규격 확인을 한 번에 요청했다.
실제 영상/manifest/asset-map/DATA_CARD/provider 정보와 권한도 요청했다. 응답을 추정하지 않는다.
실제 모델은 모두 미설정이고 fixture/mock/데모 테스트만 검증되었다.
정답 텍스트 누수와 input/cache/weight/code/test-once의 실평가 검증은 여전히 미완료이다.

## 판정

MAIN 코드 검증 PASS, `/root/stage01_reviewer` 기술 게이트 **PASS**, 팀 합의 BLOCKED (확인 대기).
reviewer 실제 실행: focused 39 passed, full 57 passed/1 warning, check_contracts Frozen contracts match.
파일 쓰기 없는 model_construct 우회 3개와 정상 인스턴스 1개 검증도 통과했다.
lock 13개 경로에 역슬래시가 없고 변경 hash는 스키마/모델 문서 2개뿐임을 확인했다.
reviewer 변경 파일 없음. 본 PASS는 독립 fixture 기술 게이트이며 실제 모델/팀 합의 인증이 아니다.
팀 합의에 의존하지 않는 backend fixture/실패 경로 작업은 기술 계약 검토 PASS 후 진행할 수 있다.
