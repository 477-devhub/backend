# 프론트 담당자 계약 확인 요청

기준: `docs/api-contract.md`, schema_version 1.1, `docs/contracts.lock.json`.
이 안내는 MAIN이 작성한 전달 자료이며 직접 전송하지 않았다. 프론트 담당자의 확인은 아직 없다.

다음 규약을 화면/클라이언트에서 수용하는지 확인해 주세요.

1. 실패·미측정은 risk=null, level=UNKNOWN이며 review 카드에 '위험도 미측정'으로 유지합니다.
   risk_axes 각 축도 null일 수 있으며 하나라도 누락되면 총점은null입니다.
   camera id는 CAM_08, 표시 name은 CAM 08입니다. 예시 위험축의 서버 계산은 89입니다.
2. 모든 POST에 Idempotency-Key가 필요합니다. 같은 행동 재시도는 같은 key, 새 행동은 새 key입니다.
   같은 key에 다른 요청은 409입니다.
3. verify→acked, dismiss→dismissed, needs_review→open/review, confirm_review→open/review 해제,
   handover→assigned_operator. request_dispatch는 사람의 요청 의도만 기록하며 자동 신고하지 않습니다.
   이 ACK 의미는 팀 확인이 필요한 초안입니다.
4. WS는 revision이 있는 전체 snapshot입니다. 재연결 첫 snapshot으로 상태를 복원하고
   낮은 revision은 무시합니다. cameras 배열도 포함합니다.
5. clip API는 JSON metadata이며 stream URL로 로컬 MP4를 요청합니다. 실제 crop/live streaming은 미완료입니다.
6. suppressed restore API로 알림을 UNKNOWN/review 상태로 복구합니다.

회신에는 수용 여부, 변경 필요한 필드/상태 의미, 확인 담당자와 날짜를 기록해 주세요.
확인 없는 기술 해시를 팀 합의 완료로 표시하지 않습니다.
