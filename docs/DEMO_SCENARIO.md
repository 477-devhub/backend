# 다각도 녹화 영상 시나리오

**HACKATHON-DAY · 2026-10-09**

판단 출처는 scripted_not_ai입니다. AI 추론/자동 사건 연결/대표 카메라 자동 선택은 구현하거나 검증한 것이 아닙니다.

## 실행
```powershell
cd C:\477\backend
$env:APP_MODE="demo"
$env:DEMO_SCENARIO_PATH="config/demo-scenario.json"
.\.venv-test\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```
.env.example만 수정해도 환경변수는 자동 적용되지 않습니다. 실제 .env를 사용하려면 uvicorn --env-file .env와 해당 의존성을 준비하세요. 현재 설정은 명시적인 환경변수로 실행할 수 있습니다.

config/demo-scenario.json:
- CAM01/02/03: region A, event-a 동기화 그룹. 사건 SCENE-A 하나, 대표 CAM02, 보조 CAM01/03.
- CAM04-09: 서로 다른 지역, 영상 내용의 role은 unassigned.
- SCENE-CANDIDATE: CAM06 위험도 기반 사건 후보 임시 예시. enabled=false로 후보를 없애거나 primary_cam과 members를 다른 독립 CAM으로 함께 변경할 수 있습니다. 영상 실제 분류가 아닙니다.
- min_step: 상단 단계 메뉴에서 사건 등장 시점. 3은 다각도 사건,4부터 임시 후보. 5/6에서도 유지합니다.
- offset_sec: 공통 재생 시계에 더하는 해당 영상 원본의 시작 초. 초기0은 미보정 값이며 영상 수령 후 같은 사건 시점으로 맞춰야 합니다.

## 영상 제공
MEDIA_ROOT(기본 media)에 CAM_01.mp4 ~ CAM_09.mp4를 놓습니다. 입력 영상은 복제하거나 다운로드하지 않았습니다. 실제 파일이 없으면 합성 스틸 또는 미디어 없음으로 표시되며 재생 검증을 완료한 것으로 보지 않습니다.
카메라 번호에 해당하는 파일명만 사용합니다. 임의 외부 파일 경로는 설정하지 않습니다.

GET /api/demo/scenario는 설정 메타데이터만 전달합니다. API1.2 사건의 primary_cam/related_cams 계약을 그대로 사용합니다.
대표 CAM에만 incident/review 상태를 적용합니다. 보조 CAM 테두리 없음은 정상/안전 판정이 아닙니다.
ACK는 사건 하나에 적용되며 같은 사건의 모든 화면에서 강조가 함께 해제됩니다.
미측정 위험은 UNKNOWN/null/review이며 현재 서버 정책에 따라 수치 위험 사건보다 앞에 정렬될 수 있습니다.
개발 모드에서는 scripted 설정과 demo step이 활성화되지 않습니다.

## AI 팀 연결 계약
향후 사건 통합 계층에서 동일 사건 ID, primary_cam, related_cams, risk/axes/confidence/review, 실제 입력 evidence/frame/timestamp를 공급해야 합니다.
CAM별 독립 모델 출력을 기존 ingest_model_input에 넣는 것만으로 동일 사건 자동 통합이 되지는 않습니다. 이 통합과 대표 선택 품질 검증은 후속 AI 범위입니다.
대표 변경 시 같은 사건 ID를 유지할지와 갱신 입력 ID 정책도 후속 합의가 필요합니다.

## 검증
백엔드 전체633PASS/1SKIP 및 contracts match. 마지막 완전하지 않은 risk_axes 검증 강화 후 focused4PASS.
대표CAM만강조/한사건등록/ACK해제/후보비활성화/잘못된CAM참조/경로거부/development차단 확인.
실제 프론트 proxy API에서 SCENE-A 대표CAM02/relatedCAM01,03, CAM06 numeric risk candidate 및 나머지 unobserved 확인.
실제 영상 동기화 오차·브라우저 렌더링·모델 품질은 Not verified.

HACKATHON-DAY 사용자 확정: 노란 사건 후보 테두리는 risk > 65에 적용합니다(65 미포함). 현재 CAM06 시나리오는 risk71/confidence0.89/reviewfalse인 합성 예시입니다. 실제영상 결과가 아닙니다. 이 기준은 프론트 표시 정책이며 서버 suppression/ACK/위험등급 정책을 변경하지 않습니다. 미측정/별도검토는 유지합니다.
