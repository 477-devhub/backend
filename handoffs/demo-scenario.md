# HACKATHON-DAY: scripted demo handoff
Source: config/demo-scenario.json; GET /api/demo/scenario.
Existing Incident primary_cam is representative; related_cams are auxiliary views.
Only primary camera gets active incident/review status. related cameras are not safe by omission.
Representative selection/group membership are explicit scripted settings until AI integration.
No actual video files or model calls were introduced.
Backend tests633PASS/1SKIP, focused4PASS, contracts match; frontend15unitPASS/1liveIntegrationPASS/buildPASS.
Video reproduction and browser visual QA Not verified. See docs/DEMO_SCENARIO.md.

HACKATHON-DAY 사용자 확정: 노란 사건 후보 테두리는 risk > 65에 적용합니다(65 미포함). 현재 CAM06 시나리오는 risk71/confidence0.89/reviewfalse인 합성 예시입니다. 실제영상 결과가 아닙니다. 이 기준은 프론트 표시 정책이며 서버 suppression/ACK/위험등급 정책을 변경하지 않습니다. 미측정/별도검토는 유지합니다.
