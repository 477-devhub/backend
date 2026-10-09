# 00 감사 — 2026-10-07

## 담당과 실행 조건

MAIN: `/root`. 실제 순차 서브에이전트: `/root/stage00_explorer` 완료 → `/root/stage00_reviewer` 완료.
두 역할은 읽기 전용이다. writer는 아직 생성하지 않았다. 중첩 위임·병렬 실행·optional_parallel 실행 없음.
역할의 TOML 모델/추론 설정과 등록된 agent_type이 일치한다. 실행 도구에는 유효 모델/sandbox 조회 기능이 없어 sandbox 강제 적용은 독립 인증할 수 없다.
기존 `.codex/agents/*.toml` 수정 사항을 보존했다.

## 확인한 파일과 완료 기준

`AGENTS.md`, `시작하기.md`, `TASKS.md`, `docs/ownership.md`, 모델/API/데이터/평가 계약,
`reports/assessment-ko.md`, 기존 app·tests·scripts를 검토한다.
완료 기준: 기존 하네스 유지, 실제/mock/미구현 분리, 코드·계약의 구체적 불일치 목록,
재현 가능한 테스트 결과, 외부 blocker, 소유권과 의존 순서 기록, reviewer 판정.
MAIN 수정 범위는 이번 감사에서 `TASKS.md`, `handoffs/00_audit.md`이다.

## MAIN 실제 명령과 결과

| 명령 | 실제 결과 |
|---|---|
| `python -m pytest -q` | 기본 Hermes Python에 pytest 없음 |
| `python scripts/check_contracts.py` | Frozen contracts match. |
| `py -3.11 -m venv .venv` | exit 0 |
| `.venv/Scripts/python.exe -m pip install -e ".[dev]"` | 설치 성공 |
| `.venv/Scripts/python.exe -m pytest -q` | 41 passed, 1 Starlette TestClient deprecation warning, 0.91s |
| `.venv/Scripts/python.exe scripts/check_contracts.py` | Frozen contracts match. |
| `.venv/Scripts/python.exe -m app.eval.runner --adapter mock_local_cv --input fixtures/model_input.json` | exit 0; is_mock=true; uncertain, review; axes=null |
| 같은 runner, `local_cv` | exit 2; provider_error; is_mock=false; uncertain, review; axes=null |
| 같은 runner, `clef_direct` | exit 2; provider_error; is_mock=false; uncertain, review; axes=null |
| 같은 runner, `general_vlm` | exit 2; provider_error; is_mock=false; uncertain, review; axes=null |

네 runner의 input_sha256은 모두 `25e08f353c7201ab753c48aee9be88474ec959cc4da762453291fdffebf8e44f`이다.
mock fixture 연결 검증은 실제 영상 추론/정확도 검증이 아니다.

## Explorer 결과

`/root/stage00_explorer`는 파일을 수정하지 않았고 자체 테스트를 실행하지 않았다.
위 테스트는 MAIN이 직접 실행했다. 위험 공식·suppression·실패 review·mock 분리는 계약과 일치한다.

| 우선순위 | 근거 | 미완료 및 수락 조건 |
|---|---|---|
| P0 | `app/main.py`, `app/models/media.py`, `TASKS.md` | 실제 모델→repository wiring 없음. 실제 미디어를 resolver/execution으로 처리하여 Incident 및 유효 evidence에 연결해야 함 |
| P0 | `docs/api-contract.md` | ACK 의미는 초안. 프론트 담당자의 UNKNOWN/ID/WS/ACK/Idempotency 합의 기록 필요 |
| P1 | `app/models/registry.py`, `app/models/adapters/unconfigured.py` | 세 real slot 모두 미설정. 실제 adapter·실입력·재현 결과 필요 |
| P1 | `media/`, `data/`, `docs/dataset-handoff.md` | 영상/manifest/inputs/asset-map/DATA_CARD/checksums 납품 없음 |
| P1 | `AGENTS.md`, `docs/model-contract.md` | Clef 제품·제공사·공식 API·모델·권한·modality 미확정. 추정 구현 금지 |
| P1 | `docs/evaluation-contract.md` | 기존 freeze는 manifest/config만 검사. 최종 평가에 code commit·weight/cache checksum 보관 필요 |
| P1 | `docs/model-contract.md` | 자유 텍스트의 의미상 정답 누수는 자동 키 검사만으로 검증 불가. extractor provenance·실제 입력 표본 검토 필요 |

확인 시 `media/`, `data/`, `outputs/`는 placeholder만 있었다. `.env` 없음.
실행 환경에서 확인한 키/모델/asset-map 변수는 미설정이며 비밀 값은 출력하지 않았다.
제공되지 않은 자료에 대한 추정·실측 완료 선언은 하지 않는다.

## 소유권과 다음 단계

MAIN: schemas, models/base·execution·registry·media, config.py, main.py, repositories/protocol.py,
pyproject, docs, contracts lock, fixtures, scripts, prompts, .codex, TASKS, tests/contracts·integration, 최종 handoffs.
backend_engineer: app/api/**, app/services/**, app/repositories/memory.py, tests/backend/**.
model_engineer: app/models/adapters/**, tests/models/**; 한 작업에서 adapter 하나만.
evaluation_engineer: app/eval/**, tests/eval/**.
explorer/reviewer: 읽기 전용. shared 파일 변경 요청은 MAIN이 순차 반영한다.

의존 순서: 00 감사 판정 → 01 계약/팀 확인 → 02 backend 연결 → 03 provider/data 준비 →
04 Local CV → 05 Clef 또는 명시 BLOCKED → 06 VLM → 07 validation → 08 통합 → 09 frozen test.
외부 의존성으로 막힌 작업은 완료 처리하지 않으며, 해당 blocker에 의존하지 않는 작업만 계속한다.

## Reviewer 판정

**감사 목록 PASS / 실제 구현·평가 준비 BLOCK.** reviewer는 파일을 수정하지 않았다.
자체 실행: `.venv/Scripts/python.exe -m pytest tests/models tests/backend tests/eval -q` → 32 passed, 1 warning, 1.01s.

P0 실제 결함: `app/models/execution.py`의 `ModelAssessment.model_validate(raw)`는 기존 Pydantic 인스턴스를 재검증하지 않는다.
valid normal 객체의 `model_copy(update={"event_confidence": 2.0})`가 error_code=None으로 통과하고
0 위험축·유효 evidence이면 `decide()`가 suppressed를 반환한다. 같은 객체의 dict 출력은 ValidationError가 된다.
MAIN도 독립 실행으로 `{'error_code': None, 'confidence': 2.0, 'disposition': 'suppressed'}`를 재현했다.
01에서 MAIN이 반환 인스턴스를 실제 재검증하도록 수정하고, 공통 회귀 테스트로 invalid→schema_or_contract/null/review를 확인해야 한다.
수정 전 의존 단계 진행 금지.

reviewer의 실제 관측 누수 probe: `description: 'Ground truth is collapse; critical=True'`는 key blacklist를 통과한다.
의미상 누수 자동 보장을 주장하지 않으며 실평가에 trusted extractor/provenance 및 표본 검토가 필요하다.
frozen guard는 manifest/config만 보호하며 입력/cache/weight/code, test 1회 실행은 별도 검증이 필요하다.
비용·전처리·프레임 budget·모델/장비 version을 기록하기 전 공정성이 실증되었다고 표시하지 않는다.
현재 테스트는 안전 정책·ACK·WS·오류 분모를 확인한 개발 하네스 검사이며 실제 모델 성능은 검증하지 않았다.
