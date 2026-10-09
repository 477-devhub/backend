# 백엔드 연동 준비 인계 — HACKATHON-DAY · 2026-10-09

프론트 저장소는 수정하지 않았다. 실제 연동은 후속 작업이다.
최신 계약은 docs/api-contract.md, 실행 예제는 docs/api-examples-v1.2.json.
예제는 실제 TestClient 응답이지만 사건은 synthetic이며 실제 모델 성능 수치가 아니다.

백엔드 추가:
- GET /api/snapshot: WS와 같은 전체 상태, server_instance_id + revision.
- API 계약1.2; 모델 schema_version1.1은 유지.
- configured_cameras(등록), observed_cameras(이 서버에서 받아 처리한 입력의 camera 수),
  target_camera_capacity(목표477)를 구분. total_cameras는 legacy 목표값이다.
- development의 미분석 camera는 unobserved/not_analyzed. idle은 처리 이력이 있지만
  활성 사건이 없다는 뜻으로 안전 확정이 아니다. demo 상태는 synthetic이다.
- 카메라 media_available/video_source로 MP4 구성 여부를 알 수 있지만 live 연결 상태는 아니다.
- ACK 결과 rank는 행동 시점의 최신 순서. acked/dismissed는 rank/next_id=null.
  idempotent replay는 최초 응답을 그대로 돌려주므로 이후 최신 순서는 snapshot을 사용.
- clip은 원본 파일의 window/실측 가능한 duration을 제공. crop_available=false.
- 등록된 사건 근거에만 /api/incidents/{id}/frames/{index} 제공. 미등록/없는 이미지의
  frame_url은 null. 빈 timeline/related_views/bbox를 실제 근거처럼 채우지 않는다.
- 공통 error.code/message/fields 추가. 기존 detail도 유지. validation은 request input을 echo하지 않음.
- 영상 없으면503, ID없으면404, 유효하지 않은 요청422, idempotency/상태충돌409.

프론트 후속 합의:
- CAM_08/서버사건ID 사용, confidence와risk_axes0–1을 화면에서만 백분율로 변환.
- 서버 rank/risk 사용. UNKNOWN/null을0점 또는 정상으로 변환하지 않음.
- 첫 snapshot 또는 server_instance_id 변경이면 local revision 기준을 초기화.
- 같은 실행ID에서는 낮은revision을 무시. 재연결 첫snapshot은 항상 전체 상태.
- source timestamps milliseconds와 clip seconds를 source video start 기준으로 변환.
- 임의의 정지 이미지 clock을 실제 영상 시각처럼 표시하지 않음.
- request_dispatch는 사람 요청 의도 기록만이며 외부 신고 없음.
- 이전 full pipeline CLI와API의 모델 연결은 별개. 이번 작업은 ingestion HTTP endpoint/DB/auth를 추가하지 않음.

Python3.12 .venv-test로 회귀 검증. 로컬 Python3.14에서는 FastAPI/Pydantic 초기화 호환 문제가 관찰됐다.
테스트 명령과 최종 결과는 TASKS.md의 이번 작업 항목에 기록한다.
