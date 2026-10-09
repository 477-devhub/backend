# 프론트 API 계약 1.2 — HACKATHON-DAY 연동 준비

현재 AI 연동 추가: development 모드의 POST /api/analysis/jobs(202),
GET /api/analysis/jobs/{job_id}, GET /api/analysis/stats.
등록 파일 MP4를 비동기 분석하여 기존 사건/검토/제외·WS에 전달한다.
기존 API1.2 의미는 유지하고 docs/ai-integration.md에 요청·응답·실패·통계 범위를 정의한다.

출처: https://www.figma.com/design/pK7WGcPjkNjP7zaAbK4c13/477?node-id=61-14&m=dev
확인: 2026-10-06. 링크 node 61:14는 API 주석 페이지 60:2의 사각형입니다.
페이지 공통 API 60:1758 및 주석 61:18, 61:115, 61:182, 62:18, 62:106, 62:200을 읽었습니다.
docs/sources/figma-api-extract.json에 관련 원문을 보관했습니다. Figma는 수정하지 않았습니다.

| API | 역할/응답 | 현재 구현 |
|---|---|---|
| GET /api/status | 상태, active_count, total_cameras, timestamp | 개발/데모 상태; 실제 477 연결 주장하지 않음 |
| GET /api/cameras | 카메라 배열 id/name/location/stream_url/status/bbox | 9개 초기 로드 |
| GET /stream/{cam_id} | 영상 bytes | 로컬 MP4, 없으면 503, unknown camera 404 |
| WS /ws/attention | 서버 순서 incidents, cameras, level_counts, active_count | 최초 snapshot + 변경 push + 15초 snapshot |
| GET /api/pipeline/stats | total/candidates/reasoned/incidents/suppressed/needs_review/stage_trace | snapshot 카운트; 실측 latency=null |
| GET /api/suppressed | id/cam_id/stage1_label/ai_verdict/reason/risk/resumed_walking | 보관 및 restored 필드 |
| GET /api/incidents/{id} | 전체 Incident | typed schema, server rank/next_id |
| GET /api/incidents/{id}/clip | clip_url/start/end/bbox_track | JSON metadata; 데모 0~10초, 실제 crop 후속 구현 |
| POST /api/incidents/{id}/ack | action/note/to_operator | 상태·audit·idempotency·WS 반영 |
| POST /api/demo/step | step 1..6 | demo에서만; 6은 5의 상세 화면용 상태 |
| POST /api/suppressed/{id}/restore | 제외 알림 복구 | 추가 보완 API, 사람 검토로 복원 |

## Figma와 다른 부분은 프론트 팀과 반드시 맞추기
- 내부 id는 CAM_08, 화면 name은 CAM 08. Figma 표시 이름을 API id로 쓰지 않습니다.
- Figma 예시 risk=94, axes=(.9,.95,.8,.85)는 식으로 계산하면 89입니다. axes를 바꾸지 않고 서버 89를 사용합니다.
- review는 UI 표시 상태이며 위험 등급과 별개입니다. level_counts는 review를 우선 집계하여 중복 카운트를 피합니다.
- 실패는 risk=null, level=UNKNOWN을 허용합니다. 프론트는 '위험도 미측정'으로 표시하고 review 카드로 유지합니다.
- risk_axes 내부 축도 미측정 null을 허용합니다. 일부 축만 측정돼도 총 risk는 null/UNKNOWN이며 review로 유지합니다.
- 원본에 없던 revision, 전체 cameras snapshot, Idempotency-Key 및 restore API를 추가했습니다.
- MP4는 파일 응답이며 RTSP/HLS 라이브 스트리밍 서버는 아닙니다. 영상은 사용자에게 공급받아야 합니다.

## ACK 의미 (원본 Figma에는 정확한 상태 전이 미정 → 본 키트의 합의 초안)
verify → acked, active queue에서 제외. dismiss → dismissed, 종결.
needs_review → open/review. confirm_review → open, review 해제(실제 위험 확정 후 다시 verify 필요).
request_dispatch → dispatch_requested=true 기록, 외부 신고/호출 없음. handover → assigned_operator 지정.
종결 dismissed에서 dismiss 외 액션은 409. handover에 to_operator 누락은 409.
잘못된 action/step은 422. 같은 key+같은 요청은 동일 응답, 같은 key+다른 요청은 409.
모든 POST는 Idempotency-Key 헤더 필수입니다. 재시도에는 같은 key, 새 행동에는 새 key 사용.
이 의미를 frontend가 구현 전에 확인하고 MAIN이 계약/테스트를 함께 고칩니다.

## WS
{event_type:'snapshot', schema_version:'1.1', revision, active_count, total_cameras:477,
 configured_cameras:9, suppressed_count, level_counts, incidents:[...], cameras:[...]}
클라이언트는 전체 snapshot으로 덮어쓰고 revision이 낮은 메시지는 무시합니다.
새 연결/재연결 첫 snapshot은 완전한 현재 상태입니다. cameras를 다시 GET할 필요가 없습니다.
같은 revision의 heartbeat는 무시해도 됩니다. 큐는 1개만 보관하여 느린 client에게 최신 상태를 전달합니다.
현재 event별 delta가 아니라 전체 snapshot으로 안정성을 우선했습니다.

## 실행 제한
memory repository 단일 프로세스, --workers 1. restart 시 incidents/audit/idempotency 초기화됩니다.
영구 DB·outbox·인증·rate limit·실시간 CV ingestion이 없는 개발용 서버입니다.
production 모드는 지원하지 않습니다. 외부 공유/운영 전에 docs/extension-plan.md 과제를 수행하세요.

## 개발 모델 연결

`app.state.ingest_model_input(ModelInput)`는 HTTP endpoint가 아닌 내부 연결입니다.
모델 실행 후 상태 잠금 안에서 Incident/Suppressed를 저장하고 변경 snapshot을 발행합니다.
같은 sample_id/같은 입력 재전송은 기존 ACK/dismiss/restore 상태와 revision을 보존합니다.
같은 sample_id/다른 입력 또는 미등록 camera는 거절합니다. 새 관측에는 새 sample_id가 필요합니다.
완료된 입력 재전송은 실행 전에 저장 판정을 조회하여 재추론하지 않습니다.
동일 sample_id의 동시 호출도 별도 실행 lock으로 직렬화하며 상태 lock을 잡은 채 모델을 기다리지 않습니다.
memory cache 밖의 provider 재시도/취소/재시작 후 요청·과금 idempotency는 보장하지 않습니다.
memory ledger는 demo reset/restart 때 초기화됩니다. 실제 모델·영상·실측 pipeline의 완료를 뜻하지 않습니다.
모델로 만든 suppressed의 미측정 stage1_label/resumed_walking은 null입니다.
프론트 확인 시 이 null 확장도 포함해야 합니다. 실제 응답 예제는 `handoffs/frontend.md`에 저장합니다.

## 1.2 추가 계약 — 2026-10-09 HACKATHON-DAY (이 절이 이전 예시보다 우선)

API의 api_contract_version은1.2, 기존 모델 schema_version은1.1이다.
기존 경로/응답 필드를 유지하고 아래 사항을 추가했다. 응답 타입은 app/api/contracts.py와
OpenAPI /docs에서 확인한다. 예제는 docs/api-examples-v1.2.json에 실제 TestClient로 생성했다.
개발 fixture 예제이며 실제 model 성능·실시간 CCTV 연결을 뜻하지 않는다.

### 수량·camera 상태
total_cameras와 stats.total의477은 legacy 제품 목표다. 실제 연결 수로 사용하지 않는다.
target_camera_capacity=477, configured_cameras는 등록된 camera수, observed_cameras는
현재 서버에서 접수·처리한 ModelInput의 camera수를 뜻한다. live connection 수는 측정하지 않는다.
camera의 media_available/video_source는 로컬MP4 존재 여부다.
analysis_status=demo/not_analyzed/analyzed. development에서 아직 입력 없는 camera는
status=unobserved, 처리 이력이 있고 active incident가 없으면 idle이다.
idle/없는 파일/검출누락을 정상 또는 안전 판정으로 표시하지 않는다.
demo의 기존normal 상태는 synthetic 표시와 함께 사용한다.

### 초기 조회 및 재연결
GET /api/snapshot은 WS와 같은 전체 상태를 반환한다.
server_instance_id는 서버 MemoryStore 수명 동안 고정이며 restart에 새로 생성한다.
demo reset은 같은instance에서revision을 올린다.
instance가 바뀌거나 새 연결의 첫snapshot이면 프론트의revision 기준을 초기화한다.
동일instance 내에서 낮은revision을 무시하고, 서버순서rank를 유지한다.
ACK 응답의incident rank/next_incident_id는 행동 시점 최신값; acked/dismissed는null.
Idempotency replay는 최초응답을 그대로 반환한다. 이후 전체 상태는snapshot을 다시 사용한다.

### 단위 및 nullable
risk=0..100 또는null, confidence=0..1, risk_axes각축0..1 또는null.
UNKNOWN/null은미측정이다. 표시용 백분율 변환 외에는 서버점수·순위를 재계산하지 않는다.
created_at/status.timestamp는 UTC ISO8601, evidence.timestamp_ms는 source video 기준milliseconds.
clip.start/end/duration_sec는 source video 시작 기준seconds다.
bbox는 normalized_xywh, [x,y,w,h] 각0..1이며 사각형이 이미지 안에 있어야 한다.
BoxOverlay는 frame_id/timestamp_ms/xywh/coordinate_space 및 선택detection_confidence를 정의한다.
현재 영상박스추적은 미제공이므로bbox와bbox_track=[]; 임의box를 생성하지 않는다.

### 영상 및 evidence
GET /api/incidents/{id}/clip은 실제ModelInput.window를 반영하고,
demo에만synthetic0..10초를 사용한다. 구간정보가없으면start/end=null이다.
ffprobe를사용할수있고metadata를읽으면duration_sec가측정된다; 그외null/unmeasured다.
range_valid=true/false는duration측정된경우만판정, 미측정이면null이다.
available은파일존재여부이며정상재생/구간유효성보장은아니다.
delivery=full_file, crop_available=false. 프론트는 seek/구간종료를직접처리한다.
등록된trustedclip_ref MP4면 /api/incidents/{id}/video, 그외 /stream/{CAM_ID}를제공한다.
source=incident_source/camera_file. path가trustedroot를벗어나면원본파일을제공하지않는다.

GET /api/incidents/{id}/frames/{index}는해당사건의실제입력근거로등록된frame만제공한다.
index는incident.evidence배열의0-based위치다. 임의파일path/다른asset token을받지않는다.
JPEG/PNG/WebP signature만허용하고8MiB의bytes한도를적용한다.
없는이미지는detail.frame_url=null; 직접요청은503. 없는사건/근거index는404.
MediaResolver또는prepared input의resolver로등록한근거만조회한다.
timeline/related_views는실제입력근거가없으면빈배열을유지한다. 이번작업은추적/인물식별을추가하지않았다.

### 통계
기존candidates/reasoned는active+suppressed snapshot 기반legacy값이다.
counter_semantics와measurement_scope가이를명시한다. 실제단계별측정으로해석하지않는다.
accepted_inputs는서버에서최초접수해저장한sample수다.
today_summary_scope=current_snapshot_not_daily: 실제일일누적통계가아니다.
avg_latency_sec/total_latency_sec는미집계라null, stage_trace=[]이다.
과거CLI benchmark 수치를실시간관제평균으로연결하지않는다.

### 오류
모든HTTP오류는legacy detail과error={code,message,fields}를제공한다.
주요code: invalid_request(400), not_found(404), conflict(409),
validation_error(422), media_unavailable(503), media_too_large(413), internal_error(500).
validation fields는loc/type/msg만제공하고입력값·Pydantic context·credential을echo하지않는다.
서버내부Exception은일반500메시지로처리한다. WebSocket close는기존1008 정책이다.

### 개발실행과남은범위
CORS_ORIGINS에프론트실제origin을설정한다. 상대영상URL은API origin/proxy에연결해야한다.
1worker/메모리저장소한계는유지한다. restart시incident/audit/idempotency/asset연결은소실된다.
HTTP model ingestion, 영구DB, 인증, realtime RTSP/HLS는이번수정범위가아니다.

## HACKATHON-DAY: scripted multi-camera scenario
DEMO_SCENARIO_PATH=config/demo-scenario.json enables an explicitly scripted demo in APP_MODE=demo only. GET /api/demo/scenario returns configured/scenario metadata with decision_source=scripted_not_ai. This is not an AI classification endpoint. Existing incident primary_cam is the chosen representative, related_cams are other cameras of the same event; only primary_cam receives incident/review camera status. Auxiliary cameras remain unhighlighted, which does not mean they are safe. ACK applies to the event, not each view.
CAM01-03 are configured as one scripted event, primary CAM02. CAM04-09 are independent regions with unassigned data roles. CAM06 is an editable temporary review candidate example, not a classification of a received video. Its enabled flag may be disabled or its members/primary changed when data arrives. Unknown risk remains null/UNKNOWN/review.
Camera filenames are restricted to MEDIA_ROOT/CAM_XX.mp4. Shared source offsets are configuration metadata, not evidence of actual time calibration. Scenario metadata does not include media bytes or secrets. No AI requests are made by demo steps.

### HACKATHON-DAY: candidate display threshold
User-selected candidate border rule is risk > 65, strictly exclusive. CAM06 scripted example now supplies numeric risk71, confidence0.89, reviewfalse, levelHIGH. Frontend renders yellow only for the event representative above this threshold; CRITICAL retains red. Independent review is preserved rather than generated from camera number. The threshold is a presentation rule and does not suppress incidents or alter server risk/ranking. Prior CAM06 UNKNOWN/review example is superseded for this default configuration.
