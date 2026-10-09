# 현재 AI 모델 연동 v1

등록 MP4 → 실제 PTS 기반 native-resolution 64장 → Cheap CV → P1 → P4 →
ModelAssessment → 기존 Incident/검토/제외 저장 → snapshot/WS를 연결한다.
모델 고도화 및 기존 frozen Test 재평가는 수행하지 않는다.

## 실행

백엔드 Python3.12 가상환경: `uv pip install --python .venv/Scripts/python.exe -e ".[dev,local-cv,ai-provider]"`.
CV 런타임은 기존 `D:/projects/477/experiments/p0_cv_only/.venv/Scripts/python.exe`를 재사용한다.
원본 가중치는 복사하지 않고 명시 경로로 지정하며 고정 SHA256을 검증한다.

```dotenv
APP_MODE=development
MODEL_ADAPTER=cascade_v1
AI_MODE=shadow
AI_PYTHON=D:/projects/477-backend/.venv/Scripts/python.exe
AI_CV_PYTHON=D:/projects/477/experiments/p0_cv_only/.venv/Scripts/python.exe
AI_WEIGHTS=D:/projects/477/experiments/p0_cv_only/models/yolo26n-pose.pt
AI_STAGE_TIMEOUT_SEC=300
AI_TOTAL_TIMEOUT_SEC=1200
AI_MAX_RETRIES=2
ANALYSIS_QUEUE_SIZE=8
ANALYSIS_MAX_JOBS=1000
ASSET_ROOT=D:/projects/477/benchmark_v1/media
ASSET_MAP=data/asset-map.json
# OPENAI_API_KEY: 설정된 환경 또는 로컬 .env에만 보관
```

신뢰된 asset-map 예: `{"ASSET_0001":"asset_01.mp4"}`.
FFmpeg/FFprobe를 PATH에 설치한다. 서버: `.venv/Scripts/python.exe -m uvicorn app.main:app --env-file .env --host 127.0.0.1 --workers 1`.
설정 예제의 benchmark media는 현재 로컬 검증 입력이며 백엔드에 benchmark 기능/데이터를 복사하지 않는다.

## 분석 요청과 조회

`POST /api/analysis/jobs`, `Idempotency-Key` 필수:

```json
{"camera_id":"CAM_02","clip_ref":"ASSET_0001","start_ms":0,"end_ms":10000}
```

202와 job_id를 반환한다. `GET /api/analysis/jobs/{job_id}`로 진행 상황과
incident_id/suppressed_id/needs_review/stage_trace를 조회한다.
상태 queued/preparing/cv/p1/p4/completed/failed. 모델 실패를 검토 사건으로 저장한 경우
작업은 completed이며 needs_review=true다. 작업 실행 자체가 불가능하면 failed다.
`GET /api/analysis/stats`는 실제 job·단계별 시도/비용/시간을 제공한다.
기존 `/api/pipeline/stats`의 legacy snapshot 값과 구분한다.
동일 키/동일 body는 최초 접수 응답을 재사용한다. 현재 상태는 GET으로 조회한다.
같은 키 다른 body는409. 새 키는 새 분석/과금 요청이다.

파일 기반 등록 MP4만 API에서 받는다. 임의 path/URL/메모리 clip은 거절한다.
최대64MiB, 최대10분 구간, native resolution 최대1920×1080, 구간 내64개 이상 frame이 필요하다.
실제 PTS를 원본 영상 milliseconds로 보존하며 provider 시간은 구간 상대 시간이다.
전처리 오류는 risk=null/UNKNOWN/검토 사건으로 기록한다.
근거는 실제 P4 인용 frame_ref에만 연결하고 설명·frame_url을 제공한다.

## 라우팅과 계약

shadow 기본값은 P1 gate를 기록하고 모든 입력을 P4로 보낸다.
`frozen_cascade_v1`은 기존 gate(p_incident≤.01, no_clear_incident, confidence≥.90,
refusal 없음/review 없음)에 백엔드의 완전 측정 risk<20 조건을 함께 적용한다.
따라서 원본 offline policy와 실행 수가 반드시 같지는 않다.
P1 제외에는 구간 관측만 기록하며 frame citation을 만들지 않는다. 복구 시 원본 clip/window를 보존한다.
P1 실패→P4, CV/P4 실패→검토, no-clear/경계 의미 미확인→검토다.
score 거절 시 실험의 대체값0.5 대신 backend 해당 축null; confidence를 risk에 곱하지 않는다.
최종 사건 이름 collapse/conflict는 의심 분류이며 모델 설명에서 확정으로 바꾸지 않는다.

공통 모델JSON 1.1에 optional routing/evidence_descriptions/metadata.stage_trace를 추가했다.
기존 API1.2/프론트 사건 필드는 유지한다. 새 분석 API가 additive extension이다.
서버 내부 analysis_diagnostics[job_id]에 raw/normalized decision, 입력 hash/profile,
CV generator provenance를 보존하며 credential/base64/provider 오류 원문은 보관하지 않는다.
각 frozen port 파일과 가중치 hash를 실행 전 검증한다.

## 검증 도구와 제한

전체 pytest 및 `scripts/check_contracts.py`. 실제 smoke는 명시적 `--live`가 있어야 호출한다:

```powershell
.venv/Scripts/python.exe -m scripts.smoke_ai_integration --asset-root D:/projects/477/benchmark_v1/media --asset asset_01.mp4 --weights D:/projects/477/experiments/p0_cv_only/models/yolo26n-pose.pt --cv-python D:/projects/477/experiments/p0_cv_only/.venv/Scripts/python.exe --key-env-file D:/projects/477/experiments/.env --budget-usd 2 --output outputs/ai-live-smoke --live
```

외부 전송과 예산 승인을 받은 경우에만 사용한다. 같은 output에 attempt가 있으면 재호출을 거절한다.
smoke는 retries0, P1 입력 크기 제한, P4 동일 payload의 공식 token-count preflight,
maxoutput32000 기준 비용 상한 검증 후 각1회 호출한다.
가격 근거: https://developers.openai.com/api/docs/models/gpt-6.1-sol
토큰 계산: https://developers.openai.com/api/docs/guides/token-counting

단일 메모리 서버이며 restart 시 작업/사건/진단이 소실된다. 인증·영구DB·RTSP/HLS·다중카메라 병합·477대 scaling은 미구현이다.
CV는 현재 단계마다 새 프로세스를 실행하므로 cold load/warmup을 포함한다.
진행 중 취소는 child process tree를 회수하되 이미 서버에 전달된 유료 요청의 과금 취소를 보장하지 않는다.
라이선스: 원본 YOLO/Ultralytics 사용조건은 별도 배포 전에 확인해야 한다.
