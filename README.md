# 477 Backend

## 현재 AI 연결 v1

Cheap CV → P1 → P4를 비동기 분석 job에서 실행하고 기존 사건·WS·근거 영상·ACK에 연결한다.
개발용 등록 MP4 입력과 shadow 기본 모드. 설치/설정/분석 API는 [연동 안내](docs/ai-integration.md) 참조.
아래 과거 'real provider 미구현' 기록은 기존 슬롯 상태이며 새 `cascade_v1` 경로와 구분한다.

## 2026-10-09 벤치마크 정리

백엔드 API·데모·모델 입력 연결·로컬 CV 전처리를 유지하고, 별도 벤치마크 기능을 제거했습니다.
`new_477_piprline`, `477_modeling_benchmark_v1`, `final_candidates_v1`의 영상·가중치·실험 결과와
전용 어댑터·평가 코드·실행 스크립트·테스트·`benchmark` 선택 의존성을 삭제했습니다.
일반 입력 검증 및 평가 유틸리티는 유지합니다. 아래 과거 검증 기록의 테스트 수는 당시 기준입니다.
Git 이력은 유지되므로 `.git`에 있는 과거 대용량 파일은 이번 작업으로 줄어들지 않습니다.

한국어 실행 안내: [시작하기.md](시작하기.md)
구조·완성도 평가: [reports/assessment-ko.md](reports/assessment-ko.md)
순서별 복사 지시문: prompts/00_audit.txt부터 09_frozen_test.txt까지.


## Frontend integration preparation — HACKATHON-DAY 2026-10-09
Backend API contract 1.2: [contract](docs/api-contract.md),
[synthetic actual responses](docs/api-examples-v1.2.json),
[frontend handoff](handoffs/frontend-api-v1.2.md).
HTTP snapshot, restart identity, explicit observation/media status, safe registered evidence
and source-video metadata are available. Frontend code and real provider experiments were not changed.
Validated with Python 3.12: 549 tests passed. The locally observed Python 3.14 environment
could not initialize FastAPI/Pydantic; use the verified environment and install FFmpeg/FFprobe on PATH.
This remains a single-worker in-memory development server.
## What runs now
- Typed model contracts; safe execution/failure policy; explicit mocks.
- Fixture -> adapter -> assessment -> incident -> GET integration.
- Demo 1..6, stateful ACK/audit/idempotency, WS snapshot push/reconnect, suppression restore.
- Licensed local MP4 file serving (media files not included).
- Manifest validation, batch evaluator, contract hashing and partitioned agent ownership.

## Not implemented yet
Real CV/Clef/VLM providers, video feature extraction/cache, real-provider resolver injection,
live ingestion/model-to-repository orchestration, persistent DB/outbox, operator auth and 477-camera scaling.
This is a development harness. Real adapter names explicitly fail until implemented; no silent mocks.

## Run
```bash
python -m venv .venv
# Windows: use .venv\Scripts\python.exe; Unix: .venv/bin/python
python -m pip install -e ".[dev]"
python -m pytest -q
python scripts/check_contracts.py
python -m uvicorn app.main:app --reload --host 127.0.0.1
python -m app.eval.runner --adapter mock_local_cv --input fixtures/model_input.json
```
Use your venv Python. One ASGI worker only. Open http://127.0.0.1:8000/docs.
POST endpoints require Idempotency-Key. APP_MODE=development disables the demo switch.

## Agent roles
MAIN owns integration/shared files. explorer/reviewer read only. model_engineer owns adapters only;
evaluation_engineer owns eval only; backend_engineer owns API/services/memory only.
See docs/ownership.md. Default one writer, optional disjoint parallel work after contract freeze.
No hardcoded model IDs: agents inherit the current selected account model.

## Dependencies and provenance
pyproject.toml has package discovery/build config and bounded dependency majors.
requirements-tested.txt records tested versions on Linux/Python 3.12; it is not an all-platform lock.
Sources: supplied harness ZIP + attached files + original AI answer + Figma API annotation page read 2026-10-06.
Original AI answer is preserved as source material, not authoritative executable instructions.
